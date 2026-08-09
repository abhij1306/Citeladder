"""Reconcile Growth Agent runs waiting on existing durable domain queues."""

from __future__ import annotations

import asyncio
import logging
import signal

from app.core.config.agent import default_agent_settings
from app.core.database import SessionLocal, dispose_engine
from app.core.telemetry import configure_logging
from app.domain.agent.service import reconcile_awaiting_tasks

logger = logging.getLogger(__name__)


class AgentWorker:
    def __init__(self) -> None:
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def run_once(self) -> int:
        async with SessionLocal() as session:
            return await reconcile_awaiting_tasks(
                session, limit=default_agent_settings.reconcile_batch_size
            )

    async def run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                changed = await self.run_once()
                if changed:
                    logger.info(
                        "agent child tasks reconciled", extra={"count": changed}
                    )
            except Exception:
                logger.exception("agent reconciliation failed")
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=default_agent_settings.reconcile_poll_seconds,
                )
            except TimeoutError:
                continue


async def _main() -> None:
    worker = AgentWorker()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, worker.stop)
        except NotImplementedError:  # Windows process runner
            pass
    try:
        await worker.run_forever()
    finally:
        await dispose_engine()


def main() -> None:  # pragma: no cover
    configure_logging()
    asyncio.run(_main())


if __name__ == "__main__":  # pragma: no cover
    main()
