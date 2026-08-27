"""Postgres SKIP-LOCKED worker for onboarding brand discovery."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import uuid
from datetime import UTC, datetime, timedelta

from app.core.config.brand_discovery import (
    BRAND_DISCOVERY_QUEUE_SPEC,
    DISCOVERY_STATUS_PROJECT_CREATED,
    DISCOVERY_STATUS_READY,
    DISCOVERY_STATUS_RUNNING,
    ERROR_BRAND_DISCOVERY,
    brand_discovery_settings,
)
from app.core.config.task_queue import (
    TASK_STATUS_FAILED,
    TASK_STATUS_RETRY_WAIT,
    TASK_STATUS_SUCCEEDED,
    TASK_TERMINAL_STATUSES,
)
from app.core.database import SessionLocal, dispose_engine
from app.core.telemetry import configure_logging, instrument_worker
from app.domain.projects.discovery import process_discovery
from app.models.discovery import BrandDiscovery, BrandDiscoveryTask
from app.orchestration.postgres_task_queue import PostgresTaskQueue
from app.workers.parent_reconcilers import reconcile_brand_discoveries

logger = logging.getLogger(__name__)


_queue = PostgresTaskQueue(SessionLocal, BRAND_DISCOVERY_QUEUE_SPEC)


async def _heartbeat(task_id, worker_id: str) -> None:
    while True:
        await asyncio.sleep(brand_discovery_settings.heartbeat_interval_seconds)
        await _queue.heartbeat(task_id=task_id, owner=worker_id)


async def _stop_heartbeat(heartbeat: asyncio.Task[None]) -> None:
    """Stop a lease heartbeat without letting cleanup failures skip finalize."""
    heartbeat.cancel()
    cleanup_error = (await asyncio.gather(heartbeat, return_exceptions=True))[0]
    if isinstance(cleanup_error, Exception):
        logger.error("Brand discovery heartbeat cleanup failed", exc_info=cleanup_error)


async def _finalize(task_id, *, worker_id: str, error: Exception | None) -> None:
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        task = await session.get(BrandDiscoveryTask, task_id, with_for_update=True)
        if task is None or task.lease_owner != worker_id:
            return
        if task.status in TASK_TERMINAL_STATUSES:
            return
        task.attempt_count += 1
        if error is None:
            task.status = TASK_STATUS_SUCCEEDED
            task.completed_at = now
            task.error_code = ""
            task.error_detail = ""
        elif task.attempt_count < task.max_attempts:
            task.status = TASK_STATUS_RETRY_WAIT
            task.available_at = now + timedelta(
                seconds=brand_discovery_settings.failure_backoff_max_seconds
            )
            task.error_code = ERROR_BRAND_DISCOVERY
            task.error_detail = str(error)[:2000]
        else:
            task.status = TASK_STATUS_FAILED
            task.completed_at = now
            task.error_code = BRAND_DISCOVERY_QUEUE_SPEC.max_attempts_error
            task.error_detail = str(error)[:2000]
        task.lease_owner = None
        task.lease_expires_at = None
        await session.commit()


async def run_once(worker_id: str, *, reap: bool = False) -> bool:
    if reap:
        await _reap_expired()
    tasks = await _queue.claim(owner=worker_id, limit=1)
    if not tasks:
        return False
    task = tasks[0]
    if not await _queue.mark_running(task_id=task.id, owner=worker_id):
        return True
    await _process_claimed_task(task, worker_id)
    return True


async def _reap_expired() -> None:
    # The reconcile body is shared with the cross-queue sweeper, which reclaims
    # this queue when THIS worker is the process that died. Two copies of the
    # same terminal transition would be two things to keep in step.
    sweep = await _queue.release_expired_detailed(
        batch_size=brand_discovery_settings.reaper_batch_size
    )
    await reconcile_brand_discoveries(SessionLocal, list(sweep.failed_parent_ids))


async def _process_claimed_task(task, worker_id: str) -> None:
    heartbeat = asyncio.create_task(_heartbeat(task.id, worker_id))
    error: Exception | None = None
    try:
        async with SessionLocal() as session:
            discovery = await session.get(BrandDiscovery, task.discovery_id)
            if discovery is None:
                raise RuntimeError("Brand discovery task has no discovery")
            if discovery.status not in {
                DISCOVERY_STATUS_READY,
                DISCOVERY_STATUS_PROJECT_CREATED,
            }:
                discovery.status = DISCOVERY_STATUS_RUNNING
                await session.commit()
                await process_discovery(session, discovery)
            else:
                logger.info(
                    "brand discovery task skipped because processing is complete",
                    extra={
                        "discovery_id": str(discovery.id),
                        "task_id": str(task.id),
                    },
                )
    except Exception as exc:
        error = exc
    finally:
        try:
            await _stop_heartbeat(heartbeat)
        finally:
            await _finalize(task.id, worker_id=worker_id, error=error)


def _set_fallback_signal(
    loop: asyncio.AbstractEventLoop,
    shutdown: asyncio.Event,
    shutdown_signal: signal.Signals,
) -> None:
    signal.signal(
        shutdown_signal,
        lambda *_: loop.call_soon_threadsafe(shutdown.set),
    )


def _install_fallback_shutdown_handler(
    loop: asyncio.AbstractEventLoop, shutdown: asyncio.Event
) -> None:
    try:
        _set_fallback_signal(loop, shutdown, signal.SIGTERM)
        _set_fallback_signal(loop, shutdown, signal.SIGINT)
    except ValueError:
        logger.warning("SIGTERM handler unavailable outside the main thread")


def _install_loop_shutdown_handlers(
    loop: asyncio.AbstractEventLoop, shutdown: asyncio.Event
) -> None:
    for shutdown_signal in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(shutdown_signal, shutdown.set)


def _install_shutdown_handler(shutdown: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    try:
        _install_loop_shutdown_handlers(loop, shutdown)
    except RuntimeError:
        _install_fallback_shutdown_handler(loop, shutdown)


def _log_iteration_failure(consecutive_failures: int) -> None:
    if consecutive_failures == 1:
        logger.exception("Brand discovery worker iteration failed")
        return
    logger.error(
        "Brand discovery worker iteration still failing",
        extra={"consecutive_failures": consecutive_failures},
    )


async def _attempt_iteration(
    worker_id: str,
    shutdown: asyncio.Event,
    *,
    reap: bool,
    consecutive_failures: int,
) -> tuple[bool, int]:
    try:
        return await run_once(worker_id, reap=reap), 0
    except asyncio.CancelledError:
        shutdown.set()
        raise
    except Exception:
        failures = consecutive_failures + 1
        _log_iteration_failure(failures)
        return False, failures


def _idle_delay(consecutive_failures: int) -> float:
    if not consecutive_failures:
        return brand_discovery_settings.poll_seconds
    return min(
        brand_discovery_settings.poll_seconds * 2 ** (consecutive_failures - 1),
        brand_discovery_settings.failure_backoff_max_seconds,
    )


async def _run_loop(worker_id: str, shutdown: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    next_reap_at = 0.0
    consecutive_failures = 0
    while not shutdown.is_set():
        reap = loop.time() >= next_reap_at
        if reap:
            next_reap_at = (
                loop.time() + brand_discovery_settings.reaper_interval_seconds
            )
        processed, consecutive_failures = await _attempt_iteration(
            worker_id,
            shutdown,
            reap=reap,
            consecutive_failures=consecutive_failures,
        )
        if not processed and not shutdown.is_set():
            await asyncio.sleep(_idle_delay(consecutive_failures))


async def main() -> None:
    configure_logging()
    instrument_worker("brand-discovery-worker")
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
    shutdown = asyncio.Event()
    _install_shutdown_handler(shutdown)
    try:
        await _run_loop(worker_id, shutdown)
    finally:
        await asyncio.shield(dispose_engine())


if __name__ == "__main__":
    asyncio.run(main())
