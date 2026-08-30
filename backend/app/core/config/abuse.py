"""Durable abuse-control limits (invariant 1).

All counters are enforced in PostgreSQL, so limits are shared by every API
task and survive process restarts. Edge/WAF limits remain an additional layer.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config.dotenv import dotenv_sources


class AbuseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ABUSE_",
        env_file=dotenv_sources(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    login_email_limit: int = Field(default=10, ge=1)
    login_client_limit: int = Field(default=30, ge=1)
    login_window_seconds: int = Field(default=300, ge=1)
    register_client_limit: int = Field(default=20, ge=1)
    register_window_seconds: int = Field(default=86400, ge=1)

    agent_call_limit: int = Field(default=30, ge=1)
    agent_call_window_seconds: int = Field(default=86400, ge=1)
    bulk_import_limit: int = Field(default=10, ge=1)
    bulk_import_window_seconds: int = Field(default=3600, ge=1)
    provider_test_limit: int = Field(default=20, ge=1)
    provider_test_window_seconds: int = Field(default=3600, ge=1)
    # Property discovery calls the provider live on every request, so a
    # reopened picker spends the workspace's Google API quota. Generous
    # enough for real reselection, low enough that a stuck client cannot
    # drain the quota.
    property_discovery_limit: int = Field(default=60, ge=1)
    property_discovery_window_seconds: int = Field(default=3600, ge=1)
    crawl_create_limit: int = Field(default=10, ge=1)
    crawl_create_window_seconds: int = Field(default=86400, ge=1)
    brand_logo_refresh_limit: int = Field(default=10, ge=1)
    brand_logo_refresh_window_seconds: int = Field(default=3600, ge=1)

    active_audits_per_workspace: int = Field(default=3, ge=1)
    audit_tasks_per_workspace_daily: int = Field(default=1500, ge=1)
    active_content_jobs_per_workspace: int = Field(default=5, ge=1)
    content_jobs_per_workspace_daily: int = Field(default=100, ge=1)
    active_job_retry_after_seconds: int = Field(default=60, ge=1)


abuse_settings = AbuseSettings()
