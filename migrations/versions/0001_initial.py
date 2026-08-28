"""Complete greenfield bootstrap schema.

Revision ID: 0001_initial
Revises: None
Create Date: 2026-07-17

This revision is the complete greenfield baseline. It contains explicit
Alembic operations and deliberately does not import live ORM metadata. Rebuild
it directly while CiteLadder has no data-retention requirement.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql


_COMMERCE_SCHEMA_PATH = Path(__file__).parents[1] / "commerce_atomic_schema.py"
_COMMERCE_SCHEMA_SPEC = importlib.util.spec_from_file_location(
    "commerce_atomic_schema", _COMMERCE_SCHEMA_PATH
)
if _COMMERCE_SCHEMA_SPEC is None or _COMMERCE_SCHEMA_SPEC.loader is None:
    raise RuntimeError("Unable to load the Commerce initial-schema operations")
_COMMERCE_SCHEMA = importlib.util.module_from_spec(_COMMERCE_SCHEMA_SPEC)
_COMMERCE_SCHEMA_SPEC.loader.exec_module(_COMMERCE_SCHEMA)

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

_CONTENT_GENERATION_FK = "content_generations.id"
_SITE_SNAPSHOT_FK = "site_health_snapshots.id"
_SITE_CHANGE_SNAPSHOT_FK = "site_change_snapshots.id"
_DEMAND_SNAPSHOT_FK = "demand_snapshots.id"
_AGENT_TASK_RUN_FK = "agent_task_runs.id"


def _create_indexes(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(op.f(f"ix_{table}_{column}"), table, [column])


def upgrade() -> None:
    op.create_table(
        "billing_webhook_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("external_event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("safe_summary", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_code", sa.String(length=64), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider", "external_event_id", name="uq_billing_webhook_external"
        ),
    )
    op.create_table(
        "usage_windows",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("subject_kind", sa.String(length=32), nullable=False),
        sa.Column("subject_hash", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "subject_kind",
            "subject_hash",
            "operation",
            "window_started_at",
            name="uq_usage_window_subject_operation_start",
        ),
    )
    op.create_index(
        "ix_usage_windows_expires_at", "usage_windows", ["expires_at"], unique=False
    )
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("session_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_table(
        "workspaces",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_workspaces_single_system",
        "workspaces",
        ["is_system"],
        unique=True,
        postgresql_where=sa.text("is_system"),
    )
    op.create_table(
        "billing_accounts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("billing_country", sa.String(length=2), nullable=False),
        sa.Column("country_verification", sa.String(length=16), nullable=False),
        sa.Column(
            "entitlement_lifecycle_version",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "entitlement_lifecycle_version >= 0",
            name="ck_billing_account_entitlement_version_nonneg",
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_billing_accounts_owner_user_id"),
        "billing_accounts",
        ["owner_user_id"],
        unique=True,
    )
    op.create_table(
        "integration_oauth_grants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("transport", sa.String(length=24), nullable=False),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=False),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "granted_scopes", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_integration_grants_ws_id"),
        sa.UniqueConstraint(
            "workspace_id", "transport", name="uq_integration_grant_ws_transport"
        ),
    )
    op.create_index(
        op.f("ix_integration_oauth_grants_status"),
        "integration_oauth_grants",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_integration_oauth_grants_workspace_id"),
        "integration_oauth_grants",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "integration_oauth_states",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("jti"),
    )
    op.create_index(
        op.f("ix_integration_oauth_states_user_id"),
        "integration_oauth_states",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_integration_oauth_states_workspace_id"),
        "integration_oauth_states",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("brand_name", sa.String(length=255), nullable=False),
        sa.Column("website_url", sa.String(length=1024), nullable=False),
        sa.Column("country_code", sa.String(length=8), nullable=False),
        sa.Column("language_code", sa.String(length=16), nullable=False),
        sa.Column("industry", sa.String(length=255), nullable=False),
        sa.Column("subindustry", sa.String(length=255), nullable=False),
        sa.Column("primary_market", sa.String(length=8), nullable=False),
        sa.Column("benchmark_mode", sa.String(length=32), nullable=False),
        sa.Column("default_repetitions", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_projects_workspace_id"), "projects", ["workspace_id"], unique=False
    )
    op.create_table(
        "prompt_sets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_prompt_sets_project_id"), "prompt_sets", ["project_id"], unique=False
    )
    op.create_table(
        "audit_schedules",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("prompt_set_id", sa.UUID(), nullable=False),
        sa.Column("audit_scope", sa.String(16), nullable=False),
        sa.Column("cadence", sa.String(32), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=True),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("engines", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("repetitions", sa.Integer(), nullable=True),
        sa.Column("benchmark_mode", sa.String(32), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(255), nullable=False),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["prompt_set_id"], ["prompt_sets.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_indexes(
        "audit_schedules",
        ("enabled", "next_run_at", "project_id", "prompt_set_id", "workspace_id"),
    )
    op.create_index(
        "ix_audit_schedules_due", "audit_schedules", ["enabled", "next_run_at"]
    )
    op.create_index("ix_audit_schedules_lease", "audit_schedules", ["lease_expires_at"])
    op.create_table(
        "provider_connections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("transport_provider", sa.String(length=32), nullable=False),
        sa.Column("base_url", sa.String(length=1024), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "deactivation_reason",
            sa.String(length=64),
            server_default="",
            nullable=False,
        ),
        sa.Column(
            "credential_source",
            sa.String(length=16),
            server_default="byok",
            nullable=False,
        ),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "pause_reason", sa.String(length=64), server_default="", nullable=False
        ),
        sa.Column("pause_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_provider_connections_workspace_id"),
        "provider_connections",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_provider_connections_workspace_source",
        "provider_connections",
        ["workspace_id", "credential_source", "transport_provider"],
        unique=False,
    )
    op.create_table(
        "queue_workspace_turns",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("queue_name", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("last_claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "queue_name", "workspace_id", name="uq_queue_workspace_turn"
        ),
    )
    op.create_index(
        "ix_queue_workspace_turn_order",
        "queue_workspace_turns",
        ["queue_name", "last_claimed_at"],
        unique=False,
    )
    op.create_table(
        "workspace_members",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("product_tour_version", sa.String(length=32), nullable=True),
        sa.Column("product_tour_status", sa.String(length=20), nullable=False),
        sa.Column("product_tour_step_id", sa.String(length=64), nullable=True),
        sa.Column("product_tour_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "product_tour_completed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),
    )
    op.create_index(
        op.f("ix_workspace_members_user_id"),
        "workspace_members",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workspace_members_workspace_id"),
        "workspace_members",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "workspace_site_health_runtime",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("resolved_registry_revision", sa.String(length=64), nullable=False),
        sa.Column(
            "resolved_entitlement_lifecycle_version", sa.Integer(), nullable=False
        ),
        sa.Column("resolved_valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discovery_mode", sa.String(length=16), nullable=False),
        sa.Column("discovery_url_cap", sa.Integer(), nullable=True),
        sa.Column("sample_url_limit", sa.Integer(), nullable=False),
        sa.Column("monitored_url_limit", sa.Integer(), nullable=False),
        sa.Column("count_disclosure", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", name="uq_ws_site_health_runtime_workspace"),
    )
    op.create_table(
        "ai_referrals_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("granularity", sa.String(length=8), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column(
            "source_classification_ids",
            postgresql.JSONB(astext_type=Text()),
            nullable=True,
        ),
        sa.Column("analyzer_version", sa.String(length=64), nullable=False),
        sa.Column("formula_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "window_start",
            "window_end",
            "granularity",
            name="uq_ai_referrals_snapshot_window",
        ),
    )
    op.create_index(
        op.f("ix_ai_referrals_snapshots_project_id"),
        "ai_referrals_snapshots",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_referrals_snapshots_workspace_id"),
        "ai_referrals_snapshots",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "analytics_tasks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("task_kind", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("randomized_position", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=32), nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_analytics_task_idempotency_key"
        ),
    )
    op.create_index(
        op.f("ix_analytics_tasks_available_at"),
        "analytics_tasks",
        ["available_at"],
        unique=False,
    )
    op.create_index(
        "ix_analytics_tasks_claim",
        "analytics_tasks",
        ["status", "available_at"],
        unique=False,
    )
    op.create_index(
        "ix_analytics_tasks_lease",
        "analytics_tasks",
        ["status", "lease_expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_analytics_tasks_project_id"),
        "analytics_tasks",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_analytics_tasks_status"), "analytics_tasks", ["status"], unique=False
    )
    op.create_index(
        op.f("ix_analytics_tasks_workspace_id"),
        "analytics_tasks",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "attribution_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("granularity", sa.String(length=8), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column(
            "source_link_ids", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column(
            "source_order_fact_ids", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column(
            "source_metric_row_ids", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column(
            "source_snapshot_ids", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column("analyzer_version", sa.String(length=64), nullable=False),
        sa.Column("formula_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "window_start",
            "window_end",
            "granularity",
            name="uq_attribution_snapshot_window",
        ),
    )
    op.create_index(
        op.f("ix_attribution_snapshots_project_id"),
        "attribution_snapshots",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_attribution_snapshots_workspace_id"),
        "attribution_snapshots",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "audits",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("benchmark_mode", sa.String(length=32), nullable=False),
        sa.Column(
            "audit_scope",
            sa.String(length=16),
            server_default="brand",
            nullable=False,
        ),
        sa.Column("parent_audit_id", sa.UUID(), nullable=True),
        sa.Column("repair_key", sa.String(length=64), nullable=True),
        sa.Column("schedule_id", sa.UUID(), nullable=True),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("funding_account_id", sa.UUID(), nullable=True),
        sa.Column(
            "funded_budget_period_start", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("funded_reserved_cost_microusd", sa.BigInteger(), nullable=True),
        sa.Column("system_instruction", sa.Text(), nullable=False),
        sa.Column("repetitions", sa.Integer(), nullable=False),
        sa.Column("random_seed", sa.String(length=32), nullable=False),
        sa.Column("configuration", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("summary", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("analyzer_version", sa.String(length=32), nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("completed_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["funding_account_id"], ["billing_accounts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["parent_audit_id"],
            ["audits.id"],
            name="fk_audits_parent_audit_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["schedule_id"],
            ["audit_schedules.id"],
            name="fk_audits_schedule_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "parent_audit_id", "repair_key", name="uq_audit_parent_repair_key"
        ),
        sa.UniqueConstraint(
            "schedule_id", "scheduled_for", name="uq_audit_schedule_slot"
        ),
    )
    op.create_index(
        op.f("ix_audits_funding_account_id"),
        "audits",
        ["funding_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audits_project_id"), "audits", ["project_id"], unique=False
    )
    op.create_index(op.f("ix_audits_status"), "audits", ["status"], unique=False)
    op.create_index(op.f("ix_audits_trigger"), "audits", ["trigger"], unique=False)
    op.create_index(
        op.f("ix_audits_workspace_id"), "audits", ["workspace_id"], unique=False
    )
    op.create_index(op.f("ix_audits_parent_audit_id"), "audits", ["parent_audit_id"])
    op.create_index(op.f("ix_audits_schedule_id"), "audits", ["schedule_id"])
    op.create_table(
        "billing_customers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("billing_account_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("external_customer_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["billing_account_id"], ["billing_accounts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "billing_account_id",
            "provider",
            name="uq_billing_customer_account_provider",
        ),
        sa.UniqueConstraint(
            "provider", "external_customer_id", name="uq_billing_customer_external"
        ),
    )
    op.create_index(
        op.f("ix_billing_customers_billing_account_id"),
        "billing_customers",
        ["billing_account_id"],
        unique=False,
    )
    op.create_table(
        "brand_logo_assets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("image_data", sa.LargeBinary(), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("domain", name="uq_brand_logo_asset_domain"),
    )
    op.create_table(
        "brands",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("logo_asset_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["logo_asset_id"],
            ["brand_logo_assets.id"],
            name="fk_brands_logo_asset_id_brand_logo_assets",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_brand_project"),
    )
    op.create_index(
        op.f("ix_brands_logo_asset_id"), "brands", ["logo_asset_id"], unique=False
    )
    op.create_table(
        "competitors",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("logo_asset_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("aliases", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("domains", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["logo_asset_id"],
            ["brand_logo_assets.id"],
            name="fk_competitors_logo_asset_id_brand_logo_assets",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_competitors_logo_asset_id"),
        "competitors",
        ["logo_asset_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_competitors_project_id"), "competitors", ["project_id"], unique=False
    )
    op.create_table(
        "content_generations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("opportunity_id", sa.UUID(), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("output_type", sa.String(length=32), nullable=False),
        sa.Column("skill_id", sa.String(64), nullable=False),
        sa.Column("skill_version", sa.String(32), nullable=False),
        sa.Column("feedback", sa.String(16), nullable=True),
        sa.Column(
            "feedback_reason", sa.String(32), nullable=False, server_default=""
        ),
        sa.Column("feedback_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("grounding_status", sa.String(length=16), nullable=False),
        sa.Column(
            "grounding_envelope",
            postgresql.JSONB(astext_type=Text()),
            nullable=False,
        ),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("message_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "message_snapshot", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("randomized_position", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=32), nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("output_text", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("requested_model", sa.String(length=255), nullable=False),
        sa.Column("returned_model", sa.String(length=255), nullable=True),
        sa.Column("finish_reason", sa.String(length=32), nullable=True),
        sa.Column("output_truncated", sa.Boolean(), nullable=False),
        sa.Column("usage", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "request_snapshot", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column("generator_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_content_generation_ws_idem"
        ),
    )
    op.create_index(
        op.f("ix_content_generations_available_at"),
        "content_generations",
        ["available_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_generations_project_id"),
        "content_generations",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_generations_request_fingerprint"),
        "content_generations",
        ["request_fingerprint"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_generations_status"),
        "content_generations",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_generations_workspace_id"),
        "content_generations",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_generations_opportunity_id"),
        "content_generations",
        ["opportunity_id"],
    )
    op.create_table(
        "discovery_model_configs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=True),
        sa.Column("logical_engine", sa.String(length=32), nullable=False),
        sa.Column("transport_provider", sa.String(length=32), nullable=False),
        sa.Column("transport_model", sa.String(length=255), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["provider_connections.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_discovery_model_configs_connection_id"),
        "discovery_model_configs",
        ["connection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_discovery_model_configs_workspace_id"),
        "discovery_model_configs",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "integration_connections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("grant_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("account_ref", sa.String(length=1024), nullable=False),
        sa.Column(
            "dataset_capabilities", postgresql.JSONB(astext_type=Text()), nullable=False
        ),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "grant_id"],
            ["integration_oauth_grants.workspace_id", "integration_oauth_grants.id"],
            name="fk_integration_connection_grant_scoped",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "grant_id", "provider", name="uq_integration_connection_grant_provider"
        ),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_integration_connections_ws_id"
        ),
    )
    op.create_index(
        op.f("ix_integration_connections_grant_id"),
        "integration_connections",
        ["grant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_integration_connections_workspace_id"),
        "integration_connections",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "owned_domains",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_owned_domains_project_id"),
        "owned_domains",
        ["project_id"],
        unique=False,
    )
    op.create_table(
        "provider_connection_tests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.String(length=1024), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("logical_engine", sa.String(length=32), nullable=False),
        sa.Column("transport_provider", sa.String(length=32), nullable=False),
        sa.Column("transport_model", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["provider_connections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_provider_connection_tests_connection_id"),
        "provider_connection_tests",
        ["connection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_provider_connection_tests_workspace_id"),
        "provider_connection_tests",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "provider_routes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("logical_engine", sa.String(length=32), nullable=False),
        sa.Column("transport_provider", sa.String(length=32), nullable=False),
        sa.Column("transport_model", sa.String(length=255), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "deactivation_reason",
            sa.String(length=64),
            server_default="",
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["provider_connections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_provider_routes_connection_id"),
        "provider_routes",
        ["connection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_provider_routes_workspace_id"),
        "provider_routes",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "site_health_profiles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("root_url", sa.String(length=2048), nullable=False),
        sa.Column("root_host", sa.String(length=255), nullable=False),
        sa.Column("registrable_domain", sa.String(length=255), nullable=False),
        sa.Column("include_globs", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("exclude_globs", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("selection_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_site_health_profile_project"),
    )
    op.create_index(
        op.f("ix_site_health_profiles_workspace_id"),
        "site_health_profiles",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "topics",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_topics_project_id"), "topics", ["project_id"], unique=False
    )
    op.create_index(
        "uq_topic_project_name",
        "topics",
        ["project_id", sa.literal_column("lower(name)")],
        unique=True,
    )
    op.create_table(
        "traffic_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("granularity", sa.String(length=8), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column(
            "source_metric_row_ids", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column(
            "source_artifact_ids", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column("formula_version", sa.String(length=64), nullable=False),
        sa.Column("normalization_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "window_start",
            "window_end",
            "granularity",
            name="uq_traffic_snapshot_window",
        ),
        sa.UniqueConstraint("workspace_id", "id", name="uq_traffic_snapshots_ws_id"),
    )
    op.create_index(
        op.f("ix_traffic_snapshots_project_id"),
        "traffic_snapshots",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_traffic_snapshots_workspace_id"),
        "traffic_snapshots",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "unintended_domains",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_unintended_domains_project_id"),
        "unintended_domains",
        ["project_id"],
        unique=False,
    )
    op.create_table(
        "workspace_billing_links",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("billing_account_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["billing_account_id"], ["billing_accounts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_workspace_billing_links_billing_account_id"),
        "workspace_billing_links",
        ["billing_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workspace_billing_links_workspace_id"),
        "workspace_billing_links",
        ["workspace_id"],
        unique=True,
    )
    op.create_table(
        "audit_engine_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("audit_id", sa.UUID(), nullable=False),
        sa.Column("logical_engine", sa.String(length=32), nullable=False),
        sa.Column("transport_provider", sa.String(length=32), nullable=False),
        sa.Column("transport_model", sa.String(length=255), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=True),
        sa.Column("base_url", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["provider_connections.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "audit_id", "logical_engine", name="uq_audit_engine_snapshot_engine"
        ),
    )
    op.create_index(
        op.f("ix_audit_engine_snapshots_audit_id"),
        "audit_engine_snapshots",
        ["audit_id"],
        unique=False,
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("audit_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_audit_events_audit_id"), "audit_events", ["audit_id"], unique=False
    )
    op.create_index(
        op.f("ix_audit_events_created_at"), "audit_events", ["created_at"], unique=False
    )
    # Covers the exact (audit_id, created_at, id) ordering the SSE/list keyset
    # resumes on; the single-column indexes above cannot serve it.
    op.create_index(
        "ix_audit_events_audit_id_created_at_id",
        "audit_events",
        ["audit_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "billing_subscriptions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("billing_account_id", sa.UUID(), nullable=False),
        sa.Column("billing_customer_id", sa.UUID(), nullable=True),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("external_subscription_id", sa.String(length=255), nullable=False),
        sa.Column("external_price_id", sa.String(length=255), nullable=False),
        sa.Column("catalog_key", sa.String(length=64), nullable=False),
        sa.Column("subscription_kind", sa.String(length=16), nullable=False),
        sa.Column("cadence", sa.String(length=24), nullable=False),
        sa.Column("quantity", sa.Integer(), server_default="1", nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_state_version", sa.Integer(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["billing_account_id"], ["billing_accounts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["billing_customer_id"], ["billing_customers.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "external_subscription_id",
            name="uq_billing_subscription_external",
        ),
    )
    op.create_index(
        op.f("ix_billing_subscriptions_billing_account_id"),
        "billing_subscriptions",
        ["billing_account_id"],
        unique=False,
    )
    op.create_index(
        "uq_billing_subscription_one_current",
        "billing_subscriptions",
        ["billing_account_id"],
        unique=True,
        postgresql_where=sa.text("is_current AND subscription_kind = 'base'"),
    )
    op.create_index(
        "uq_billing_subscription_one_current_addon",
        "billing_subscriptions",
        ["billing_account_id", "catalog_key"],
        unique=True,
        postgresql_where=sa.text("is_current AND subscription_kind = 'addon'"),
    )
    op.create_table(
        "brand_aliases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("brand_id", sa.UUID(), nullable=False),
        sa.Column("alias", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_brand_aliases_brand_id"), "brand_aliases", ["brand_id"], unique=False
    )
    op.create_table(
        "brand_profiles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("brand_id", sa.UUID(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("positioning", sa.Text(), nullable=False),
        sa.Column(
            "products_services", postgresql.JSONB(astext_type=Text()), nullable=False
        ),
        sa.Column("target_audience", sa.Text(), nullable=False),
        sa.Column(
            "business_context", postgresql.JSONB(astext_type=Text()), nullable=False
        ),
        sa.Column("sources", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column(
            "source_artifact_ids", postgresql.JSONB(astext_type=Text()), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("brand_id", name="uq_brand_profile_brand"),
    )
    op.create_index(
        op.f("ix_brand_profiles_project_id"),
        "brand_profiles",
        ["project_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_brand_profiles_workspace_id"),
        "brand_profiles",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "content_generation_attempts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("content_generation_id", sa.UUID(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requested_model", sa.String(length=255), nullable=False),
        sa.Column("returned_model", sa.String(length=255), nullable=True),
        sa.Column("finish_reason", sa.String(length=32), nullable=True),
        sa.Column("error_code", sa.String(length=32), nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=False),
        sa.Column("usage", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["content_generation_id"], [_CONTENT_GENERATION_FK], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "content_generation_id",
            "attempt_number",
            name="uq_content_generation_attempt_number",
        ),
    )
    op.create_index(
        op.f("ix_content_generation_attempts_content_generation_id"),
        "content_generation_attempts",
        ["content_generation_id"],
        unique=False,
    )
    op.create_table(
        "integration_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=True),
        sa.Column("grant_id", sa.UUID(), nullable=True),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["integration_connections.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["grant_id"], ["integration_oauth_grants.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_integration_events_connection_id"),
        "integration_events",
        ["connection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_integration_events_created_at"),
        "integration_events",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_integration_events_workspace_id"),
        "integration_events",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "integration_property_mappings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("property_ref", sa.String(length=512), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["integration_connections.workspace_id", "integration_connections.id"],
            name="fk_integration_mapping_connection_scoped",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_integration_property_mappings_active_owner",
        "integration_property_mappings",
        ["workspace_id", "provider", "property_ref"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        op.f("ix_integration_property_mappings_connection_id"),
        "integration_property_mappings",
        ["connection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_integration_property_mappings_project_id"),
        "integration_property_mappings",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_integration_property_mappings_workspace_id"),
        "integration_property_mappings",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "integration_sync_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("sync_kind", sa.String(length=16), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("resync_seq", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("randomized_position", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=32), nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["integration_connections.workspace_id", "integration_connections.id"],
            name="fk_integration_sync_run_connection_scoped",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id",
            "sync_kind",
            "window_start",
            "window_end",
            "resync_seq",
            name="uq_integration_sync_run_window_seq",
        ),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_integration_sync_run_idempotency_key"
        ),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_integration_sync_runs_ws_id"
        ),
    )
    op.create_index(
        "ix_integration_sync_runs_active_window",
        "integration_sync_runs",
        ["connection_id", "sync_kind", "window_start", "window_end"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('leased', 'queued', 'retry_wait', 'running')"
        ),
    )
    op.create_index(
        op.f("ix_integration_sync_runs_available_at"),
        "integration_sync_runs",
        ["available_at"],
        unique=False,
    )
    op.create_index(
        "ix_integration_sync_runs_claim",
        "integration_sync_runs",
        ["status", "available_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_integration_sync_runs_connection_id"),
        "integration_sync_runs",
        ["connection_id"],
        unique=False,
    )
    op.create_index(
        "ix_integration_sync_runs_lease",
        "integration_sync_runs",
        ["status", "lease_expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_integration_sync_runs_status"),
        "integration_sync_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_integration_sync_runs_workspace_id"),
        "integration_sync_runs",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "metric_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("audit_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("analyzer_version", sa.String(length=32), nullable=False),
        sa.Column("scoring_rule_version", sa.String(length=32), nullable=False),
        sa.Column("total_completed", sa.Integer(), nullable=False),
        sa.Column("total_failed", sa.Integer(), nullable=False),
        sa.Column("visibility_score", sa.Float(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column(
            "source_analysis_ids", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column(
            "source_artifact_ids", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("audit_id", name="uq_metric_snapshot_audit"),
    )
    op.create_index(
        op.f("ix_metric_snapshots_project_id"),
        "metric_snapshots",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_metric_snapshots_workspace_id"),
        "metric_snapshots",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "prompts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("prompt_set_id", sa.UUID(), nullable=False),
        sa.Column("topic_id", sa.UUID(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("normalized_text_hash", sa.String(length=64), nullable=False),
        sa.Column("theme", sa.String(length=255), nullable=False),
        sa.Column("intent", sa.String(length=32), nullable=False),
        sa.Column(
            "buyer_stage", sa.String(length=16), server_default="", nullable=False
        ),
        sa.Column(
            "prompt_intent", sa.String(length=16), server_default="", nullable=False
        ),
        sa.Column("branded", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "cohort", sa.String(length=32), server_default="core", nullable=False
        ),
        sa.Column(
            "status", sa.String(length=16), server_default="active", nullable=False
        ),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column(
            "generation_evidence", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["prompt_set_id"], ["prompt_sets.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "prompt_set_id",
            "normalized_text_hash",
            name="uq_prompt_set_normalized_text",
        ),
    )
    op.create_index(
        op.f("ix_prompts_prompt_set_id"), "prompts", ["prompt_set_id"], unique=False
    )
    op.create_index(op.f("ix_prompts_topic_id"), "prompts", ["topic_id"], unique=False)
    op.create_index(op.f("ix_prompts_cohort"), "prompts", ["cohort"])
    op.create_table(
        "site_crawls",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("profile_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("discovery_status", sa.String(length=24), nullable=False),
        sa.Column("analysis_status", sa.String(length=24), nullable=False),
        sa.Column("root_url", sa.String(length=2048), nullable=False),
        sa.Column("random_seed", sa.String(length=32), nullable=False),
        sa.Column("configuration", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("sample_mode", sa.Boolean(), nullable=False),
        sa.Column("admitted_url_count", sa.Integer(), nullable=False),
        sa.Column("discovered_url_count", sa.Integer(), nullable=False),
        sa.Column("analyzed_url_count", sa.Integer(), nullable=False),
        sa.Column("failed_url_count", sa.Integer(), nullable=False),
        sa.Column("discovery_requested_count", sa.Integer(), nullable=False),
        sa.Column("analysis_requested_count", sa.Integer(), nullable=False),
        sa.Column("inventory_complete", sa.Boolean(), nullable=False),
        sa.Column("partial_reason", sa.String(length=48), nullable=False),
        sa.Column("score_summary", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("site_facts", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("extractor_version", sa.String(length=32), nullable=False),
        sa.Column("analyzer_version", sa.String(length=32), nullable=False),
        sa.Column("rule_catalog_version", sa.String(length=32), nullable=False),
        sa.Column("scoring_version", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["site_health_profiles.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "project_id", "workspace_id", name="uq_site_crawls_id_project"
        ),
    )
    op.create_index(
        op.f("ix_site_crawls_profile_id"), "site_crawls", ["profile_id"], unique=False
    )
    op.create_index(
        op.f("ix_site_crawls_project_id"), "site_crawls", ["project_id"], unique=False
    )
    op.create_index(
        op.f("ix_site_crawls_status"), "site_crawls", ["status"], unique=False
    )
    op.create_index(
        op.f("ix_site_crawls_workspace_id"),
        "site_crawls",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "site_crawl_phase_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("crawl_id", sa.UUID(), nullable=False),
        sa.Column("phase", sa.String(length=16), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("processed_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["crawl_id"], ["site_crawls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "crawl_id", "phase", "ordinal", name="uq_site_phase_run_ordinal"
        ),
    )
    op.create_index(
        "ix_site_phase_runs_crawl_phase",
        "site_crawl_phase_runs",
        ["crawl_id", "phase", "status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_site_crawl_phase_runs_crawl_id"),
        "site_crawl_phase_runs",
        ["crawl_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_site_crawl_phase_runs_status"),
        "site_crawl_phase_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_site_crawl_phase_runs_workspace_id"),
        "site_crawl_phase_runs",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "site_discovery_frontier",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("crawl_id", sa.UUID(), nullable=False),
        sa.Column("normalized_url", sa.String(length=2048), nullable=False),
        sa.Column("url_hash", sa.String(length=64), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(length=16), nullable=False),
        sa.Column("value_kind", sa.String(length=32), nullable=False),
        sa.Column("value_priority", sa.Integer(), nullable=False),
        sa.Column("parent_position", sa.Integer(), nullable=False),
        sa.Column("link_ordinal", sa.Integer(), nullable=False),
        sa.Column("rewrite_reason", sa.String(length=64), nullable=False),
        sa.Column("rewrite_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("admitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["crawl_id"], ["site_crawls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "crawl_id", "url_hash", name="uq_site_discovery_frontier_url"
        ),
    )
    op.create_index(
        "ix_site_discovery_frontier_pending",
        "site_discovery_frontier",
        [
            "crawl_id",
            "status",
            sa.text("value_priority DESC"),
            "parent_position",
            "link_ordinal",
            "url_hash",
        ],
        unique=False,
    )
    op.create_index(
        op.f("ix_site_discovery_frontier_crawl_id"),
        "site_discovery_frontier",
        ["crawl_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_site_discovery_frontier_workspace_id"),
        "site_discovery_frontier",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "traffic_query_stats",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("snapshot_id", sa.UUID(), nullable=False),
        sa.Column("normalized_query", sa.String(length=1024), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column(
            "source_metric_row_ids", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column(
            "source_artifact_ids", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "snapshot_id"],
            ["traffic_snapshots.workspace_id", "traffic_snapshots.id"],
            name="fk_traffic_query_stat_snapshot_scoped",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_id", "normalized_query", name="uq_traffic_query_stat_query"
        ),
    )
    op.create_index(
        op.f("ix_traffic_query_stats_project_id"),
        "traffic_query_stats",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_traffic_query_stats_snapshot_id"),
        "traffic_query_stats",
        ["snapshot_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_traffic_query_stats_workspace_id"),
        "traffic_query_stats",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "audit_prompt_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("audit_id", sa.UUID(), nullable=False),
        sa.Column("prompt_id", sa.UUID(), nullable=True),
        sa.Column("prompt_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("theme", sa.String(length=255), nullable=False),
        sa.Column("intent", sa.String(length=32), nullable=False),
        sa.Column(
            "cohort", sa.String(length=32), server_default="core", nullable=False
        ),
        sa.Column(
            "generation_evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["prompt_id"], ["prompts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "audit_id", "prompt_index", name="uq_audit_prompt_snapshot_index"
        ),
    )
    op.create_index(
        op.f("ix_audit_prompt_snapshots_audit_id"),
        "audit_prompt_snapshots",
        ["audit_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_prompt_snapshots_cohort"), "audit_prompt_snapshots", ["cohort"]
    )
    op.create_table(
        "integration_import_artifacts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("sync_run_id", sa.UUID(), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("dataset", sa.String(length=48), nullable=False),
        sa.Column(
            "query_snapshot", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["integration_connections.workspace_id", "integration_connections.id"],
            name="fk_integration_artifact_connection_scoped",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "sync_run_id"],
            ["integration_sync_runs.workspace_id", "integration_sync_runs.id"],
            name="fk_integration_artifact_sync_run_scoped",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_integration_import_artifacts_ws_id"
        ),
    )
    op.create_index(
        op.f("ix_integration_import_artifacts_connection_id"),
        "integration_import_artifacts",
        ["connection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_integration_import_artifacts_payload_hash"),
        "integration_import_artifacts",
        ["payload_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_integration_import_artifacts_sync_run_id"),
        "integration_import_artifacts",
        ["sync_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_integration_import_artifacts_workspace_id"),
        "integration_import_artifacts",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "opportunities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("rule_id", sa.String(length=64), nullable=False),
        sa.Column("opportunity_type", sa.String(length=16), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("priority_score", sa.Float(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("remediation", sa.Text(), nullable=False),
        sa.Column("target_key", sa.String(length=512), nullable=False),
        sa.Column("target_prompt_id", sa.UUID(), nullable=True),
        sa.Column("target_url", sa.Text(), nullable=True),
        sa.Column("target_theme", sa.String(length=255), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column(
            "source_analysis_ids", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column(
            "source_issue_ids", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column(
            "source_metric_ids", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column(
            "source_traffic_ids", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column("analyzer_version", sa.String(length=32), nullable=False),
        sa.Column("rule_version", sa.String(length=32), nullable=False),
        sa.Column("formula_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("superseded_by_id", sa.UUID(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["superseded_by_id"], ["opportunities.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["target_prompt_id"], ["prompts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_opportunities_filter",
        "opportunities",
        ["project_id", "status", "severity", "opportunity_type"],
        unique=False,
    )
    op.create_index(
        "ix_opportunities_list",
        "opportunities",
        ["project_id", "priority_score", "id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_opportunities_project_id"),
        "opportunities",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_opportunities_workspace_id"),
        "opportunities",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "uq_opportunities_live_target",
        "opportunities",
        ["project_id", "rule_id", "target_key"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )
    op.create_foreign_key(
        "fk_content_generations_opportunity_id",
        "content_generations",
        "opportunities",
        ["opportunity_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "opportunity_orders",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("ordered_keys", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by_user_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_opportunity_orders_project"),
    )
    op.create_index(
        op.f("ix_opportunity_orders_workspace_id"),
        "opportunity_orders",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "opportunity_status_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("opportunity_id", sa.UUID(), nullable=False),
        sa.Column("stable_key", sa.String(length=640), nullable=False),
        sa.Column("previous_status", sa.String(length=16), nullable=False),
        sa.Column("next_status", sa.String(length=16), nullable=False),
        sa.Column("changed_by_user_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["changed_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"], ["opportunities.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_opportunity_status_events_opportunity_id"),
        "opportunity_status_events",
        ["opportunity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_opportunity_status_events_project_id"),
        "opportunity_status_events",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_opportunity_status_events_project_created",
        "opportunity_status_events",
        ["project_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_opportunity_status_events_workspace_id"),
        "opportunity_status_events",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "opportunity_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("audit_id", sa.UUID(), nullable=True),
        sa.Column("site_crawl_id", sa.UUID(), nullable=True),
        sa.Column("demand_snapshot_id", sa.UUID(), nullable=True),
        sa.Column("demand_source_revision", sa.String(length=64), nullable=True),
        sa.Column("coverage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "limitations",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "counts_by_type", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column(
            "counts_by_severity", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column(
            "counts_by_status", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("median_priority", sa.Float(), nullable=True),
        sa.Column("analyzer_version", sa.String(length=32), nullable=False),
        sa.Column("rule_version", sa.String(length=32), nullable=False),
        sa.Column("formula_version", sa.String(length=32), nullable=False),
        sa.Column(
            "source_analysis_ids", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column(
            "source_issue_ids", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["site_crawl_id"], ["site_crawls.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_opportunity_snapshot_run"),
    )
    op.create_index(
        "ix_opportunity_snapshots_project_created",
        "opportunity_snapshots",
        ["project_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_opportunity_snapshots_project_id"),
        "opportunity_snapshots",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_opportunity_snapshots_workspace_id"),
        "opportunity_snapshots",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "opportunity_implementation_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("opportunity_id", sa.UUID(), nullable=False),
        sa.Column("opportunity_snapshot_id", sa.UUID(), nullable=False),
        sa.Column(
            "target_site_url_ids",
            postgresql.JSONB(astext_type=Text()),
            nullable=False,
        ),
        sa.Column("generation_id", sa.UUID(), nullable=True),
        sa.Column(
            "declared_implemented_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "expected_checks", postgresql.JSONB(astext_type=Text()), nullable=False
        ),
        sa.Column("actor_user_id", sa.UUID(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["opportunity_id"], ["opportunities.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_snapshot_id"],
            ["opportunity_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["generation_id"], ["content_generations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_opportunity_implementation_ws_idem",
        ),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_opportunity_implementation_ws_id"
        ),
    )
    _create_indexes(
        "opportunity_implementation_events",
        (
            "workspace_id",
            "project_id",
            "opportunity_id",
            "opportunity_snapshot_id",
        ),
    )
    op.create_index(
        "ix_opportunity_implementation_project_created",
        "opportunity_implementation_events",
        ["project_id", "created_at", "id"],
    )
    op.create_table(
        "opportunity_verification_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("implementation_event_id", sa.UUID(), nullable=False),
        sa.Column("observation_kind", sa.String(length=16), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("crawl_id", sa.UUID(), nullable=True),
        sa.Column("audit_id", sa.UUID(), nullable=True),
        sa.Column(
            "source_analysis_ids", postgresql.JSONB(astext_type=Text()), nullable=False
        ),
        sa.Column(
            "source_rule_evaluation_ids",
            postgresql.JSONB(astext_type=Text()),
            nullable=False,
        ),
        sa.Column(
            "source_metric_ids", postgresql.JSONB(astext_type=Text()), nullable=False
        ),
        sa.Column("verifier_version", sa.String(length=32), nullable=False),
        sa.Column("limitations", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "implementation_event_id"],
            [
                "opportunity_implementation_events.workspace_id",
                "opportunity_implementation_events.id",
            ],
            ondelete="CASCADE",
            name="fk_opportunity_verification_implementation_workspace",
        ),
        sa.ForeignKeyConstraint(["crawl_id"], ["site_crawls.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_opportunity_verification_ws_idem",
        ),
    )
    _create_indexes(
        "opportunity_verification_events",
        ("workspace_id", "project_id", "implementation_event_id"),
    )
    op.create_index(
        "ix_opportunity_verification_implementation_created",
        "opportunity_verification_events",
        ["implementation_event_id", "created_at", "id"],
    )
    op.create_table(
        "opportunity_guidance",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("opportunity_id", sa.UUID(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column(
            "input_snapshot", postgresql.JSONB(astext_type=Text()), nullable=False
        ),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("findings", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column(
            "recommendations", postgresql.JSONB(astext_type=Text()), nullable=False
        ),
        sa.Column(
            "source_analysis_ids", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column(
            "source_issue_ids", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column(
            "source_metric_ids", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column("analyzer_version", sa.String(length=32), nullable=False),
        sa.Column("rule_version", sa.String(length=32), nullable=False),
        sa.Column("formula_version", sa.String(length=32), nullable=False),
        sa.Column("generator_version", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["opportunity_id"], ["opportunities.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "opportunity_id",
            "idempotency_key",
            name="uq_opportunity_guidance_idempotency",
        ),
    )
    op.create_index(
        op.f("ix_opportunity_guidance_input_hash"),
        "opportunity_guidance",
        ["input_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_opportunity_guidance_opportunity_id"),
        "opportunity_guidance",
        ["opportunity_id"],
        unique=False,
    )
    op.create_index(
        "ix_opportunity_guidance_opportunity_created",
        "opportunity_guidance",
        ["opportunity_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_opportunity_guidance_project_id"),
        "opportunity_guidance",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_opportunity_guidance_workspace_id"),
        "opportunity_guidance",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "products",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("sku", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("aliases", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("variants", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("attributes", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=True),
        sa.Column("external_item_ref", sa.String(length=255), nullable=False),
        sa.Column("last_seen_sync_run_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["integration_connections.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["last_seen_sync_run_id"], ["integration_sync_runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "sku", name="uq_product_project_sku"),
    )
    op.create_index(
        op.f("ix_products_connection_id"), "products", ["connection_id"], unique=False
    )
    op.create_index(
        op.f("ix_products_last_seen_sync_run_id"),
        "products",
        ["last_seen_sync_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_products_project_id"), "products", ["project_id"], unique=False
    )
    op.create_table(
        "site_crawl_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("crawl_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["crawl_id"], ["site_crawls.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_site_crawl_events_crawl_id"),
        "site_crawl_events",
        ["crawl_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_site_crawl_events_created_at"),
        "site_crawl_events",
        ["created_at"],
        unique=False,
    )
    # Covers the exact (crawl_id, created_at, id) ordering ``load_events``
    # resumes on; the single-column indexes above cannot serve it.
    op.create_index(
        "ix_site_crawl_events_crawl_id_created_at_id",
        "site_crawl_events",
        ["crawl_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "site_health_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("crawl_id", sa.UUID(), nullable=False),
        sa.Column("selected_url_count", sa.Integer(), nullable=False),
        sa.Column("analyzed_url_count", sa.Integer(), nullable=False),
        sa.Column("technical_score", sa.Float(), nullable=True),
        sa.Column("aeo_score", sa.Float(), nullable=True),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("issue_count", sa.Integer(), nullable=False),
        sa.Column(
            "severity_counts", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column(
            "category_counts", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column("coverage_state", sa.String(length=16), nullable=False),
        sa.Column(
            "coverage_evidence", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column(
            "coverage_formula_version", sa.String(length=32), nullable=False
        ),
        sa.Column("source_analysis_ids", postgresql.ARRAY(sa.UUID()), nullable=True),
        sa.Column("source_artifact_ids", postgresql.ARRAY(sa.UUID()), nullable=True),
        sa.Column("source_evaluation_ids", postgresql.ARRAY(sa.UUID()), nullable=True),
        sa.Column("analyzer_version", sa.String(length=32), nullable=False),
        sa.Column("scoring_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["crawl_id"], ["site_crawls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("crawl_id", name="uq_site_health_snapshot_crawl"),
    )
    op.create_index(
        op.f("ix_site_health_snapshots_project_id"),
        "site_health_snapshots",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_site_health_snapshots_workspace_id"),
        "site_health_snapshots",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "site_urls",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("normalized_url", sa.String(length=2048), nullable=False),
        sa.Column("url_hash", sa.String(length=64), nullable=False),
        sa.Column("display_url", sa.String(length=2048), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("corpus_disposition", sa.String(length=16), nullable=False),
        sa.Column("disposition_reason", sa.String(length=32), nullable=False),
        sa.Column("disposition_version", sa.String(length=32), nullable=False),
        sa.Column("item_kind", sa.String(length=16), nullable=False),
        sa.Column("discovery_status", sa.String(length=24), nullable=False),
        sa.Column("latest_source_kind", sa.String(length=16), nullable=False),
        sa.Column("latest_title", sa.String(length=1024), nullable=False),
        sa.Column("latest_content_type", sa.String(length=128), nullable=False),
        sa.Column("first_seen_crawl_id", sa.UUID(), nullable=True),
        sa.Column("last_seen_crawl_id", sa.UUID(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["first_seen_crawl_id"], ["site_crawls.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["last_seen_crawl_id"], ["site_crawls.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "project_id", "workspace_id", name="uq_site_urls_id_project"
        ),
        sa.UniqueConstraint("project_id", "url_hash", name="uq_site_url_project_hash"),
    )
    op.create_index(
        op.f("ix_site_urls_project_id"), "site_urls", ["project_id"], unique=False
    )
    op.create_index(
        "ix_site_urls_project_keyset",
        "site_urls",
        ["project_id", "normalized_url", "id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_site_urls_workspace_id"), "site_urls", ["workspace_id"], unique=False
    )
    op.create_table(
        "audit_tasks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("audit_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("prompt_snapshot_id", sa.UUID(), nullable=False),
        sa.Column("engine_snapshot_id", sa.UUID(), nullable=False),
        sa.Column("prompt_index", sa.Integer(), nullable=False),
        sa.Column("repetition", sa.Integer(), nullable=False),
        sa.Column("randomized_position", sa.Integer(), nullable=False),
        sa.Column("logical_engine", sa.String(length=32), nullable=False),
        sa.Column("transport_provider", sa.String(length=32), nullable=False),
        sa.Column("transport_model", sa.String(length=255), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column(
            "provider_route_snapshot",
            postgresql.JSONB(astext_type=Text()),
            nullable=True,
        ),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("result_artifact_id", sa.UUID(), nullable=True),
        sa.Column("source_task_id", sa.UUID(), nullable=True),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("search_used", sa.Boolean(), nullable=False),
        sa.Column("search_events", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("citations", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("score", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column(
            "request_snapshot", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column(
            "provider_metadata", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("finish_reason", sa.String(length=24), nullable=False),
        sa.Column("raw_finish_reason", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=32), nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["engine_snapshot_id"], ["audit_engine_snapshots.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["prompt_snapshot_id"], ["audit_prompt_snapshots.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_task_id"],
            ["audit_tasks.id"],
            name="fk_audit_tasks_source_task_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "audit_id",
            "prompt_index",
            "repetition",
            "logical_engine",
            name="uq_audit_task_slot",
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_audit_task_idempotency_key"),
    )
    op.create_index(
        op.f("ix_audit_tasks_audit_id"), "audit_tasks", ["audit_id"], unique=False
    )
    op.create_index(
        op.f("ix_audit_tasks_available_at"),
        "audit_tasks",
        ["available_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_tasks_status"), "audit_tasks", ["status"], unique=False
    )
    op.create_index(
        op.f("ix_audit_tasks_workspace_id"),
        "audit_tasks",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_tasks_source_task_id"), "audit_tasks", ["source_task_id"]
    )
    op.create_table(
        "provider_capacity_buckets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("pool_kind", sa.String(length=16), nullable=False),
        sa.Column("transport_provider", sa.String(length=32), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=True),
        sa.Column("billing_account_id", sa.UUID(), nullable=True),
        sa.Column("capacity", sa.Numeric(14, 4), nullable=False),
        sa.Column("tokens", sa.Numeric(14, 4), nullable=False),
        sa.Column("refill_tokens_per_second", sa.Numeric(14, 4), nullable=False),
        sa.Column("refilled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("policy_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["billing_account_id"], ["billing_accounts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["provider_connections.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pool_kind",
            "transport_provider",
            "connection_id",
            "billing_account_id",
            name="uq_provider_capacity_bucket_pool",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        op.f("ix_provider_capacity_buckets_blocked_until"),
        "provider_capacity_buckets",
        ["blocked_until"],
        unique=False,
    )
    op.create_table(
        "provider_capacity_leases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("bucket_id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("lease_kind", sa.String(length=16), nullable=False),
        sa.Column("units", sa.Numeric(14, 4), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["bucket_id"], ["provider_capacity_buckets.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["task_id"], ["audit_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "bucket_id",
            "task_id",
            "attempt_number",
            "lease_kind",
            name="uq_provider_capacity_lease_slot",
        ),
    )
    op.create_index(
        op.f("ix_provider_capacity_leases_bucket_id"),
        "provider_capacity_leases",
        ["bucket_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_provider_capacity_leases_expires_at"),
        "provider_capacity_leases",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_provider_capacity_leases_task_id"),
        "provider_capacity_leases",
        ["task_id"],
        unique=False,
    )
    op.create_table(
        "feed_issues",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("sync_run_id", sa.UUID(), nullable=False),
        sa.Column("external_item_ref", sa.String(length=255), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=True),
        sa.Column("source_artifact_id", sa.UUID(), nullable=False),
        sa.Column("rule_id", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("importer_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["integration_connections.workspace_id", "integration_connections.id"],
            name="fk_feed_issue_connection_scoped",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_artifact_id"],
            [
                "integration_import_artifacts.workspace_id",
                "integration_import_artifacts.id",
            ],
            name="fk_feed_issue_artifact_scoped",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "sync_run_id"],
            ["integration_sync_runs.workspace_id", "integration_sync_runs.id"],
            name="fk_feed_issue_sync_run_scoped",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "sync_run_id",
            "external_item_ref",
            "rule_id",
            name="uq_feed_issue_run_item_rule",
        ),
    )
    op.create_index(
        op.f("ix_feed_issues_connection_id"),
        "feed_issues",
        ["connection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_feed_issues_project_id"), "feed_issues", ["project_id"], unique=False
    )
    op.create_index(
        op.f("ix_feed_issues_source_artifact_id"),
        "feed_issues",
        ["source_artifact_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_feed_issues_sync_run_id"), "feed_issues", ["sync_run_id"], unique=False
    )
    op.create_index(
        op.f("ix_feed_issues_workspace_id"),
        "feed_issues",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "integration_metric_rows",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("property_ref", sa.String(length=512), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("dataset", sa.String(length=48), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("dimension_key", sa.String(length=1024), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("source_artifact_id", sa.UUID(), nullable=False),
        sa.Column("resync_seq", sa.Integer(), nullable=False),
        sa.Column("importer_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_artifact_id"],
            [
                "integration_import_artifacts.workspace_id",
                "integration_import_artifacts.id",
            ],
            name="fk_integration_metric_row_artifact_scoped",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "property_ref",
            "provider",
            "dataset",
            "date",
            "dimension_key",
            "resync_seq",
            name="uq_integration_metric_row_identity",
        ),
    )
    op.create_index(
        "ix_integration_metric_rows_project_date",
        "integration_metric_rows",
        ["project_id", "date"],
        unique=False,
    )
    op.create_index(
        op.f("ix_integration_metric_rows_project_id"),
        "integration_metric_rows",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_integration_metric_rows_source_artifact_id"),
        "integration_metric_rows",
        ["source_artifact_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_integration_metric_rows_workspace_id"),
        "integration_metric_rows",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "monitored_site_urls",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("profile_id", sa.UUID(), nullable=False),
        sa.Column("site_url_id", sa.UUID(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("selection_source", sa.String(length=16), nullable=False),
        sa.Column("selecting_membership_id", sa.Integer(), nullable=True),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deselected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["site_health_profiles.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_url_id"], ["site_urls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "site_url_id", name="uq_monitored_site_url"),
    )
    op.create_index(
        op.f("ix_monitored_site_urls_profile_id"),
        "monitored_site_urls",
        ["profile_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_monitored_site_urls_project_id"),
        "monitored_site_urls",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_monitored_site_urls_site_url_id"),
        "monitored_site_urls",
        ["site_url_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_monitored_site_urls_workspace_id"),
        "monitored_site_urls",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_monitored_site_urls_ws_active",
        "monitored_site_urls",
        ["workspace_id", "active"],
        unique=False,
    )
    op.create_table(
        "order_facts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("order_ref_hash", sa.String(length=64), nullable=False),
        sa.Column("resync_seq", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("line_items", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column(
            "attribution_keys", postgresql.JSONB(astext_type=Text()), nullable=False
        ),
        sa.Column("source_artifact_id", sa.UUID(), nullable=False),
        sa.Column("importer_version", sa.String(length=64), nullable=False),
        sa.Column("order_sanitize_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["integration_connections.workspace_id", "integration_connections.id"],
            name="fk_order_fact_connection_scoped",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_artifact_id"],
            [
                "integration_import_artifacts.workspace_id",
                "integration_import_artifacts.id",
            ],
            name="fk_order_fact_artifact_scoped",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id",
            "order_ref_hash",
            "resync_seq",
            name="uq_order_fact_identity",
        ),
        sa.UniqueConstraint("workspace_id", "id", name="uq_order_facts_ws_id"),
    )
    op.create_index(
        op.f("ix_order_facts_connection_id"),
        "order_facts",
        ["connection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_order_facts_order_ref_hash"),
        "order_facts",
        ["order_ref_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_order_facts_project_id"), "order_facts", ["project_id"], unique=False
    )
    op.create_index(
        op.f("ix_order_facts_source_artifact_id"),
        "order_facts",
        ["source_artifact_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_order_facts_workspace_id"),
        "order_facts",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "product_metric_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("audit_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=True),
        sa.Column("product_analyzer_version", sa.String(length=32), nullable=False),
        sa.Column("product_scoring_rule_version", sa.String(length=32), nullable=False),
        sa.Column("mention_count", sa.Integer(), nullable=False),
        sa.Column("sov_share", sa.Float(), nullable=False),
        sa.Column("avg_rank", sa.Float(), nullable=True),
        sa.Column(
            "rank_distribution", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column("price_mention_count", sa.Integer(), nullable=False),
        sa.Column("price_accuracy_rate", sa.Float(), nullable=True),
        sa.Column("win_rate", sa.Float(), nullable=True),
        sa.Column("price_mismatch_rate", sa.Float(), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column(
            "source_analysis_ids", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column(
            "source_artifact_ids", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_product_metric_snapshots_audit_id"),
        "product_metric_snapshots",
        ["audit_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_metric_snapshots_project_id"),
        "product_metric_snapshots",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_metric_snapshots_workspace_id"),
        "product_metric_snapshots",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "uq_product_metric_snapshot_product",
        "product_metric_snapshots",
        [
            "audit_id",
            "product_id",
            "product_analyzer_version",
            "product_scoring_rule_version",
        ],
        unique=True,
        postgresql_where=sa.text("product_id IS NOT NULL"),
    )
    op.create_table(
        "site_crawl_tasks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("crawl_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("phase_run_id", sa.UUID(), nullable=True),
        sa.Column("site_url_id", sa.UUID(), nullable=True),
        sa.Column("task_kind", sa.String(length=16), nullable=False),
        sa.Column("requested_url", sa.String(length=2048), nullable=False),
        sa.Column("url_hash", sa.String(length=64), nullable=False),
        sa.Column("parent_site_url_id", sa.UUID(), nullable=True),
        sa.Column("source_task_id", sa.UUID(), nullable=True),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("randomized_position", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("result_artifact_id", sa.UUID(), nullable=True),
        sa.Column("error_code", sa.String(length=32), nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["crawl_id"], ["site_crawls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["phase_run_id"], ["site_crawl_phase_runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["parent_site_url_id"], ["site_urls.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["site_url_id"], ["site_urls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_task_id"], ["site_crawl_tasks.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "crawl_id",
            "task_kind",
            "url_hash",
            "generation",
            name="uq_site_crawl_task_slot",
        ),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_site_crawl_task_idempotency_key"
        ),
    )
    op.create_index(
        op.f("ix_site_crawl_tasks_available_at"),
        "site_crawl_tasks",
        ["available_at"],
        unique=False,
    )
    op.create_index(
        "ix_site_crawl_tasks_claim",
        "site_crawl_tasks",
        ["status", "available_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_site_crawl_tasks_crawl_id"),
        "site_crawl_tasks",
        ["crawl_id"],
        unique=False,
    )
    op.create_index(
        "ix_site_crawl_tasks_lease",
        "site_crawl_tasks",
        ["status", "lease_expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_site_crawl_tasks_site_url_id"),
        "site_crawl_tasks",
        ["site_url_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_site_crawl_tasks_phase_run_id"),
        "site_crawl_tasks",
        ["phase_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_site_crawl_tasks_status"), "site_crawl_tasks", ["status"], unique=False
    )
    op.create_index(
        op.f("ix_site_crawl_tasks_workspace_id"),
        "site_crawl_tasks",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "traffic_page_stats",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("snapshot_id", sa.UUID(), nullable=False),
        sa.Column("site_url_id", sa.UUID(), nullable=True),
        sa.Column("canonical_url", sa.String(length=2048), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column(
            "source_metric_row_ids", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column(
            "source_artifact_ids", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_url_id"], ["site_urls.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "snapshot_id"],
            ["traffic_snapshots.workspace_id", "traffic_snapshots.id"],
            name="fk_traffic_page_stat_snapshot_scoped",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_id", "canonical_url", name="uq_traffic_page_stat_url"
        ),
    )
    op.create_index(
        op.f("ix_traffic_page_stats_project_id"),
        "traffic_page_stats",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_traffic_page_stats_snapshot_id"),
        "traffic_page_stats",
        ["snapshot_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_traffic_page_stats_workspace_id"),
        "traffic_page_stats",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "attribution_links",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("order_fact_id", sa.UUID(), nullable=False),
        sa.Column("method", sa.String(length=24), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("matched_rule_id", sa.String(length=64), nullable=False),
        sa.Column("rule_version", sa.String(length=64), nullable=False),
        sa.Column("analyzer_version", sa.String(length=64), nullable=False),
        sa.Column(
            "evidence_refs", postgresql.JSONB(astext_type=Text()), nullable=False
        ),
        sa.Column("revenue_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "order_fact_id"],
            ["order_facts.workspace_id", "order_facts.id"],
            name="fk_attribution_link_order_fact_scoped",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "order_fact_id",
            "matched_rule_id",
            "rule_version",
            name="uq_attribution_link_order_rule_version",
        ),
    )
    op.create_index(
        op.f("ix_attribution_links_order_fact_id"),
        "attribution_links",
        ["order_fact_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_attribution_links_project_id"),
        "attribution_links",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_attribution_links_workspace_id"),
        "attribution_links",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "raw_response_artifacts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("audit_id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("logical_engine", sa.String(length=32), nullable=False),
        sa.Column("transport_provider", sa.String(length=32), nullable=False),
        sa.Column("transport_model", sa.String(length=255), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("search_used", sa.Boolean(), nullable=False),
        sa.Column("search_events", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("citations", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column(
            "provider_metadata", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column("usage", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("finish_reason", sa.String(length=24), nullable=False),
        sa.Column("raw_finish_reason", sa.String(length=64), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["audit_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_raw_response_artifacts_audit_id"),
        "raw_response_artifacts",
        ["audit_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_raw_response_artifacts_task_id"),
        "raw_response_artifacts",
        ["task_id"],
        unique=False,
    )
    op.create_table(
        "execution_cost_projections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("audit_id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("raw_response_artifact_id", sa.UUID(), nullable=False),
        sa.Column("formula_version", sa.String(length=32), nullable=False),
        sa.Column("pricing_version", sa.String(length=64), nullable=False),
        sa.Column("projection_status", sa.String(length=16), nullable=False),
        sa.Column("uncached_input_tokens", sa.Integer(), nullable=True),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("reasoning_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("search_requests", sa.Integer(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=True),
        sa.Column("uncached_input_cost_microusd", sa.BigInteger(), nullable=True),
        sa.Column("cached_input_cost_microusd", sa.BigInteger(), nullable=True),
        sa.Column("output_cost_microusd", sa.BigInteger(), nullable=True),
        sa.Column("reasoning_cost_microusd", sa.BigInteger(), nullable=True),
        sa.Column("search_cost_microusd", sa.BigInteger(), nullable=True),
        sa.Column("provider_reported_cost_microusd", sa.BigInteger(), nullable=True),
        sa.Column("projected_total_cost_microusd", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["raw_response_artifact_id"],
            ["raw_response_artifacts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["task_id"], ["audit_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "raw_response_artifact_id",
            "formula_version",
            "pricing_version",
            name="uq_execution_cost_projection_version",
        ),
    )
    op.create_index(
        op.f("ix_execution_cost_projections_audit_id"),
        "execution_cost_projections",
        ["audit_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_execution_cost_projections_raw_response_artifact_id"),
        "execution_cost_projections",
        ["raw_response_artifact_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_execution_cost_projections_task_id"),
        "execution_cost_projections",
        ["task_id"],
        unique=False,
    )
    op.create_table(
        "referral_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("import_id", sa.UUID(), nullable=False),
        sa.Column("source_metric_row_id", sa.UUID(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("landing_url", sa.String(length=2048), nullable=False),
        sa.Column("referrer_host", sa.String(length=512), nullable=False),
        sa.Column("referrer_url", sa.String(length=2048), nullable=False),
        sa.Column("utm_source", sa.String(length=512), nullable=False),
        sa.Column("utm_medium", sa.String(length=512), nullable=False),
        sa.Column("utm_campaign", sa.String(length=512), nullable=False),
        sa.Column("user_agent", sa.String(length=128), nullable=False),
        sa.Column("session_id_hash", sa.String(length=64), nullable=False),
        sa.Column("raw", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("sanitize_version", sa.String(length=64), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_metric_row_id"],
            ["integration_metric_rows.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "import_id"],
            [
                "integration_import_artifacts.workspace_id",
                "integration_import_artifacts.id",
            ],
            name="fk_referral_event_import_scoped",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "import_id", "content_hash", name="uq_referral_event_import_content"
        ),
        sa.UniqueConstraint("workspace_id", "id", name="uq_referral_events_ws_id"),
    )
    op.create_index(
        op.f("ix_referral_events_import_id"),
        "referral_events",
        ["import_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_referral_events_project_id"),
        "referral_events",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_referral_events_project_occurred",
        "referral_events",
        ["project_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_referral_events_workspace_id"),
        "referral_events",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "site_fetch_artifacts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("crawl_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("fetch_purpose", sa.String(length=16), nullable=False),
        sa.Column("requested_url", sa.String(length=2048), nullable=False),
        sa.Column("final_url", sa.String(length=2048), nullable=False),
        sa.Column(
            "redirect_chain", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column(
            "redacted_headers", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("http_version", sa.String(length=16), nullable=False),
        sa.Column("ttfb_ms", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("wire_bytes", sa.Integer(), nullable=True),
        sa.Column("decoded_bytes", sa.Integer(), nullable=True),
        sa.Column("acquisition_transport", sa.String(length=32), nullable=False),
        sa.Column("acquisition_rung", sa.Integer(), nullable=True),
        sa.Column("acquisition_trigger", sa.String(length=32), nullable=False),
        sa.Column("impersonation_profile", sa.String(length=64), nullable=False),
        sa.Column(
            "acquisition_options", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column("acquisition_policy_version", sa.String(length=32), nullable=False),
        sa.Column("extractor_version", sa.String(length=32), nullable=False),
        sa.Column(
            "normalized_facts", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["crawl_id"], ["site_crawls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["task_id"], ["site_crawl_tasks.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", name="uq_site_fetch_artifact_task"),
    )
    op.create_index(
        op.f("ix_site_fetch_artifacts_crawl_id"),
        "site_fetch_artifacts",
        ["crawl_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_site_fetch_artifacts_workspace_id"),
        "site_fetch_artifacts",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "product_response_analyses",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("audit_id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("artifact_id", sa.UUID(), nullable=True),
        sa.Column("product_analyzer_version", sa.String(length=32), nullable=False),
        sa.Column("product_scoring_rule_version", sa.String(length=32), nullable=False),
        sa.Column("logical_engine", sa.String(length=32), nullable=False),
        sa.Column("transport_provider", sa.String(length=32), nullable=False),
        sa.Column("transport_model", sa.String(length=255), nullable=False),
        sa.Column("prompt_index", sa.Integer(), nullable=False),
        sa.Column("repetition", sa.Integer(), nullable=False),
        sa.Column("own_product_mention_count", sa.Integer(), nullable=False),
        sa.Column("products_with_price_match", sa.Integer(), nullable=False),
        sa.Column("score", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["artifact_id"], ["raw_response_artifacts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["audit_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id",
            "product_analyzer_version",
            "product_scoring_rule_version",
            name="uq_product_response_analysis_task_version",
        ),
    )
    op.create_index(
        op.f("ix_product_response_analyses_audit_id"),
        "product_response_analyses",
        ["audit_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_response_analyses_task_id"),
        "product_response_analyses",
        ["task_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_response_analyses_workspace_id"),
        "product_response_analyses",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "provider_attempts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("audit_id", sa.UUID(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("logical_engine", sa.String(length=32), nullable=False),
        sa.Column("transport_provider", sa.String(length=32), nullable=False),
        sa.Column("transport_model", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=32), nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("artifact_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["artifact_id"], ["raw_response_artifacts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["audit_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_provider_attempts_audit_id"),
        "provider_attempts",
        ["audit_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_provider_attempts_task_id"),
        "provider_attempts",
        ["task_id"],
        unique=False,
    )
    op.create_table(
        "referral_classifications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("referral_event_id", sa.UUID(), nullable=False),
        sa.Column("is_ai_referral", sa.Boolean(), nullable=False),
        sa.Column("ai_source", sa.String(length=32), nullable=False),
        sa.Column("logical_engine", sa.String(length=32), nullable=True),
        sa.Column("matched_rule_id", sa.String(length=64), nullable=False),
        sa.Column("match_signal", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("rule_version", sa.String(length=64), nullable=False),
        sa.Column("analyzer_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "referral_event_id"],
            ["referral_events.workspace_id", "referral_events.id"],
            name="fk_referral_classification_event_scoped",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "referral_event_id", name="uq_referral_classification_event"
        ),
    )
    op.create_index(
        op.f("ix_referral_classifications_project_id"),
        "referral_classifications",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_referral_classifications_workspace_id"),
        "referral_classifications",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "response_analyses",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("audit_id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("artifact_id", sa.UUID(), nullable=False),
        sa.Column("analyzer_version", sa.String(length=32), nullable=False),
        sa.Column("scoring_rule_version", sa.String(length=32), nullable=False),
        sa.Column("logical_engine", sa.String(length=32), nullable=False),
        sa.Column("transport_provider", sa.String(length=32), nullable=False),
        sa.Column("transport_model", sa.String(length=255), nullable=False),
        sa.Column("prompt_index", sa.Integer(), nullable=False),
        sa.Column("repetition", sa.Integer(), nullable=False),
        sa.Column("prompt_class", sa.String(length=32), nullable=False),
        sa.Column(
            "cohort", sa.String(length=32), server_default="core", nullable=False
        ),
        sa.Column("brand_mentioned", sa.Boolean(), nullable=False),
        sa.Column("brand_first_offset", sa.Integer(), nullable=True),
        sa.Column("owned_domain_cited", sa.Boolean(), nullable=False),
        sa.Column("owned_citation_count", sa.Integer(), nullable=False),
        sa.Column("unintended_domain_cited", sa.Boolean(), nullable=False),
        sa.Column("citation_count", sa.Integer(), nullable=False),
        sa.Column("search_used", sa.Boolean(), nullable=False),
        sa.Column("search_query_count", sa.Integer(), nullable=False),
        sa.Column("sentiment", sa.String(length=16), nullable=True),
        sa.Column("avg_position", sa.Float(), nullable=True),
        sa.Column("score", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["artifact_id"], ["raw_response_artifacts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["audit_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", name="uq_response_analysis_task"),
    )
    op.create_index(
        op.f("ix_response_analyses_audit_id"),
        "response_analyses",
        ["audit_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_response_analyses_workspace_id"),
        "response_analyses",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_response_analyses_cohort"), "response_analyses", ["cohort"]
    )
    op.create_table(
        "site_fetch_attempts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("crawl_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("request_ordinal", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(length=8), nullable=False),
        sa.Column("target_host", sa.String(length=255), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=32), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("wire_bytes", sa.Integer(), nullable=True),
        sa.Column("decoded_bytes", sa.Integer(), nullable=True),
        sa.Column("acquisition_transport", sa.String(length=32), nullable=False),
        sa.Column("acquisition_rung", sa.Integer(), nullable=True),
        sa.Column("acquisition_trigger", sa.String(length=32), nullable=False),
        sa.Column("impersonation_profile", sa.String(length=64), nullable=False),
        sa.Column(
            "acquisition_options", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column("acquisition_policy_version", sa.String(length=32), nullable=False),
        sa.Column("artifact_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["artifact_id"], ["site_fetch_artifacts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["crawl_id"], ["site_crawls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["task_id"], ["site_crawl_tasks.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id",
            "attempt_number",
            "request_ordinal",
            name="uq_site_fetch_attempt_call",
        ),
    )
    op.create_index(
        op.f("ix_site_fetch_attempts_crawl_id"),
        "site_fetch_attempts",
        ["crawl_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_site_fetch_attempts_task_id"),
        "site_fetch_attempts",
        ["task_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_site_fetch_attempts_workspace_id"),
        "site_fetch_attempts",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "site_page_analyses",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("crawl_id", sa.UUID(), nullable=False),
        sa.Column("site_url_id", sa.UUID(), nullable=False),
        sa.Column("artifact_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("technical_score", sa.Float(), nullable=True),
        sa.Column("aeo_score", sa.Float(), nullable=True),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("analyzer_version", sa.String(length=32), nullable=False),
        sa.Column("scoring_version", sa.String(length=32), nullable=False),
        sa.Column("page_kind", sa.String(length=24), nullable=False),
        sa.Column("classifier_version", sa.String(length=32), nullable=False),
        sa.Column(
            "page_kind_evidence", postgresql.JSONB(astext_type=Text()), nullable=True
        ),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("source_evaluation_ids", postgresql.ARRAY(sa.UUID()), nullable=True),
        sa.Column("source_artifact_ids", postgresql.ARRAY(sa.UUID()), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["artifact_id"], ["site_fetch_artifacts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["crawl_id"], ["site_crawls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_url_id"], ["site_urls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # Artifact IDs are reusable provenance. The row UUID is the analysis
    # identity, with one current understanding per page in a crawl.
    op.create_index(
        "uq_site_page_analysis_current",
        "site_page_analyses",
        ["crawl_id", "site_url_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.create_index(
        op.f("ix_site_page_analyses_artifact_id"),
        "site_page_analyses",
        ["artifact_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_site_page_analyses_crawl_id"),
        "site_page_analyses",
        ["crawl_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_site_page_analyses_project_id"),
        "site_page_analyses",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_site_page_analyses_site_url_id"),
        "site_page_analyses",
        ["site_url_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_site_page_analyses_workspace_id"),
        "site_page_analyses",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "site_url_observations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("crawl_id", sa.UUID(), nullable=False),
        sa.Column("site_url_id", sa.UUID(), nullable=False),
        sa.Column("source_kind", sa.String(length=16), nullable=False),
        sa.Column("parent_site_url_id", sa.UUID(), nullable=True),
        sa.Column("source_artifact_id", sa.UUID(), nullable=True),
        sa.Column("phase_run_id", sa.UUID(), nullable=True),
        sa.Column("value_kind", sa.String(length=32), nullable=False),
        sa.Column("value_priority", sa.Integer(), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("observed_url", sa.String(length=2048), nullable=False),
        sa.Column("final_url", sa.String(length=2048), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=1024), nullable=False),
        sa.Column("rewrite_reason", sa.String(length=64), nullable=False),
        sa.Column("rewrite_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["parent_site_url_id"], ["site_urls.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_artifact_id"], ["site_fetch_artifacts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["phase_run_id"], ["site_crawl_phase_runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id", "crawl_id"],
            ["site_crawls.workspace_id", "site_crawls.project_id", "site_crawls.id"],
            name="fk_site_url_observation_crawl_scoped",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id", "site_url_id"],
            ["site_urls.workspace_id", "site_urls.project_id", "site_urls.id"],
            name="fk_site_url_observation_site_url_scoped",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("crawl_id", "site_url_id", name="uq_site_url_observation"),
    )
    op.create_index(
        op.f("ix_site_url_observations_crawl_id"),
        "site_url_observations",
        ["crawl_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_site_url_observations_project_id"),
        "site_url_observations",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_site_url_observations_phase_run_id"),
        "site_url_observations",
        ["phase_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_site_url_observations_site_url_id"),
        "site_url_observations",
        ["site_url_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_site_url_observations_workspace_id"),
        "site_url_observations",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "site_page_link_metrics",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("crawl_id", sa.UUID(), nullable=False),
        sa.Column("site_url_id", sa.UUID(), nullable=False),
        sa.Column("inbound_count", sa.Integer(), nullable=False),
        sa.Column("outbound_count", sa.Integer(), nullable=False),
        sa.Column("main_content_inbound_count", sa.Integer(), nullable=False),
        sa.Column("main_content_outbound_count", sa.Integer(), nullable=False),
        sa.Column("nofollow_inbound_count", sa.Integer(), nullable=False),
        sa.Column("depth_from_home", sa.Integer(), nullable=True),
        sa.Column("source_page_count", sa.Integer(), nullable=False),
        sa.Column("top_inbound", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("top_outbound", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("source_artifact_ids", postgresql.ARRAY(sa.UUID()), nullable=True),
        sa.Column("extractor_version", sa.String(length=32), nullable=False),
        sa.Column("formula_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id", "crawl_id"],
            ["site_crawls.workspace_id", "site_crawls.project_id", "site_crawls.id"],
            name="fk_site_page_link_metric_crawl_scoped",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id", "site_url_id"],
            ["site_urls.workspace_id", "site_urls.project_id", "site_urls.id"],
            name="fk_site_page_link_metric_site_url_scoped",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "crawl_id",
            "site_url_id",
            "extractor_version",
            "formula_version",
            name="uq_site_page_link_metric",
        ),
    )
    _create_indexes(
        "site_page_link_metrics",
        ("workspace_id", "project_id", "crawl_id", "site_url_id"),
    )
    op.create_table(
        "site_observed_architectures",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("crawl_id", sa.UUID(), nullable=False),
        sa.Column("source_snapshot_id", sa.UUID(), nullable=False),
        sa.Column("source_brand_profile_id", sa.UUID(), nullable=True),
        sa.Column("coverage_state", sa.String(length=16), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("page_kind_counts", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("families", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("hierarchy", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("archetype", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("source_analysis_ids", postgresql.ARRAY(sa.UUID()), nullable=True),
        sa.Column("source_artifact_ids", postgresql.ARRAY(sa.UUID()), nullable=True),
        sa.Column("source_evaluation_ids", postgresql.ARRAY(sa.UUID()), nullable=True),
        sa.Column("source_link_metric_ids", postgresql.ARRAY(sa.UUID()), nullable=True),
        sa.Column("extractor_version", sa.String(length=32), nullable=False),
        sa.Column("analyzer_version", sa.String(length=32), nullable=False),
        sa.Column("rule_version", sa.String(length=32), nullable=False),
        sa.Column("architecture_formula_version", sa.String(length=32), nullable=False),
        sa.Column("archetype_policy_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id", "crawl_id"],
            ["site_crawls.workspace_id", "site_crawls.project_id", "site_crawls.id"],
            name="fk_site_observed_architecture_crawl_scoped",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_snapshot_id"],
            ["site_health_snapshots.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "crawl_id",
            "extractor_version",
            "analyzer_version",
            "rule_version",
            "architecture_formula_version",
            "archetype_policy_version",
            name="uq_site_observed_architecture",
        ),
    )
    _create_indexes(
        "site_observed_architectures", ("workspace_id", "project_id", "crawl_id")
    )
    op.create_table(
        "brand_mentions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("audit_id", sa.UUID(), nullable=False),
        sa.Column("analysis_id", sa.UUID(), nullable=False),
        sa.Column("artifact_id", sa.UUID(), nullable=False),
        sa.Column("analyzer_version", sa.String(length=32), nullable=False),
        sa.Column("brand_name", sa.String(length=255), nullable=False),
        sa.Column("first_offset", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"], ["response_analyses.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"], ["raw_response_artifacts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_brand_mentions_analysis_id"),
        "brand_mentions",
        ["analysis_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_brand_mentions_audit_id"), "brand_mentions", ["audit_id"], unique=False
    )
    op.create_index(
        op.f("ix_brand_mentions_workspace_id"),
        "brand_mentions",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "citations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("audit_id", sa.UUID(), nullable=False),
        sa.Column("analysis_id", sa.UUID(), nullable=False),
        sa.Column("artifact_id", sa.UUID(), nullable=False),
        sa.Column("analyzer_version", sa.String(length=32), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("classification", sa.String(length=24), nullable=False),
        sa.Column("is_owned", sa.Boolean(), nullable=False),
        sa.Column("is_unintended", sa.Boolean(), nullable=False),
        sa.Column("matched_competitor", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"], ["response_analyses.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"], ["raw_response_artifacts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_citations_analysis_id"), "citations", ["analysis_id"], unique=False
    )
    op.create_index(
        op.f("ix_citations_audit_id"), "citations", ["audit_id"], unique=False
    )
    op.create_index(
        op.f("ix_citations_workspace_id"), "citations", ["workspace_id"], unique=False
    )
    op.create_table(
        "competitor_mentions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("audit_id", sa.UUID(), nullable=False),
        sa.Column("analysis_id", sa.UUID(), nullable=False),
        sa.Column("artifact_id", sa.UUID(), nullable=False),
        sa.Column("analyzer_version", sa.String(length=32), nullable=False),
        sa.Column("competitor_name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"], ["response_analyses.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"], ["raw_response_artifacts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_competitor_mentions_analysis_id"),
        "competitor_mentions",
        ["analysis_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_competitor_mentions_audit_id"),
        "competitor_mentions",
        ["audit_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_competitor_mentions_workspace_id"),
        "competitor_mentions",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "merchant_mentions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("audit_id", sa.UUID(), nullable=False),
        sa.Column("analysis_id", sa.UUID(), nullable=False),
        sa.Column("artifact_id", sa.UUID(), nullable=True),
        sa.Column("product_id", sa.UUID(), nullable=True),
        sa.Column("merchant_name", sa.String(length=255), nullable=False),
        sa.Column("merchant_domain", sa.String(length=255), nullable=False),
        sa.Column("merchant_kind", sa.String(length=16), nullable=False),
        sa.Column("destination_url", sa.Text(), nullable=False),
        sa.Column("price_text", sa.String(length=64), nullable=False),
        sa.Column("price_value", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("price_currency", sa.String(length=3), nullable=False),
        sa.Column("product_analyzer_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"], ["product_response_analyses.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"], ["raw_response_artifacts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_merchant_mentions_analysis_id"),
        "merchant_mentions",
        ["analysis_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_merchant_mentions_audit_id"),
        "merchant_mentions",
        ["audit_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_merchant_mentions_workspace_id"),
        "merchant_mentions",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "product_mentions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("audit_id", sa.UUID(), nullable=False),
        sa.Column("analysis_id", sa.UUID(), nullable=False),
        sa.Column("artifact_id", sa.UUID(), nullable=True),
        sa.Column("product_analyzer_version", sa.String(length=32), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=True),
        sa.Column("matched_name", sa.String(length=255), nullable=False),
        sa.Column("matched_sku", sa.String(length=128), nullable=False),
        sa.Column("first_offset", sa.Integer(), nullable=True),
        sa.Column("rank_position", sa.Integer(), nullable=True),
        sa.Column("price_text", sa.String(length=64), nullable=False),
        sa.Column("price_value", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("price_currency", sa.String(length=3), nullable=False),
        sa.Column("price_matches_catalog", sa.Boolean(), nullable=True),
        sa.Column("price_relation", sa.String(length=16), nullable=True),
        sa.Column(
            "attribute_mentions", postgresql.JSONB(astext_type=Text()), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"], ["product_response_analyses.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"], ["raw_response_artifacts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_product_mentions_analysis_id"),
        "product_mentions",
        ["analysis_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_mentions_audit_id"),
        "product_mentions",
        ["audit_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_mentions_workspace_id"),
        "product_mentions",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "site_rule_evaluations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("analysis_id", sa.UUID(), nullable=False),
        sa.Column("source_artifact_id", sa.UUID(), nullable=False),
        sa.Column("source_architecture_id", sa.UUID(), nullable=True),
        sa.Column("rule_id", sa.String(length=64), nullable=False),
        sa.Column("dimension", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("finding_class", sa.String(length=16), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column(
            "supporting_artifact_ids", postgresql.ARRAY(sa.UUID()), nullable=True
        ),
        sa.Column("extractor_version", sa.String(length=32), nullable=False),
        sa.Column("analyzer_version", sa.String(length=32), nullable=False),
        sa.Column("rule_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"], ["site_page_analyses.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_artifact_id"], ["site_fetch_artifacts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_architecture_id"],
            ["site_observed_architectures.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "outcome IN ('pass', 'fail', 'not_applicable', 'error')",
            name="ck_site_rule_evaluations_outcome",
        ),
        sa.UniqueConstraint(
            "analysis_id",
            "rule_id",
            "source_architecture_id",
            name="uq_site_rule_evaluation",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        op.f("ix_site_rule_evaluations_analysis_id"),
        "site_rule_evaluations",
        ["analysis_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_site_rule_evaluations_source_artifact_id"),
        "site_rule_evaluations",
        ["source_artifact_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_site_rule_evaluations_source_architecture_id"),
        "site_rule_evaluations",
        ["source_architecture_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_site_rule_evaluations_workspace_id"),
        "site_rule_evaluations",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "site_issues",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("crawl_id", sa.UUID(), nullable=False),
        sa.Column("site_url_id", sa.UUID(), nullable=False),
        sa.Column("analysis_id", sa.UUID(), nullable=False),
        sa.Column("evaluation_id", sa.UUID(), nullable=False),
        sa.Column("source_artifact_id", sa.UUID(), nullable=False),
        sa.Column("rule_id", sa.String(length=64), nullable=False),
        sa.Column("dimension", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("finding_class", sa.String(length=16), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("remediation", sa.Text(), nullable=False),
        sa.Column("analyzer_version", sa.String(length=32), nullable=False),
        sa.Column("rule_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"], ["site_page_analyses.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["crawl_id"], ["site_crawls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["evaluation_id"], ["site_rule_evaluations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_url_id"], ["site_urls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_artifact_id"], ["site_fetch_artifacts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("evaluation_id", name="uq_site_issue_evaluation"),
    )
    op.create_index(
        op.f("ix_site_issues_analysis_id"), "site_issues", ["analysis_id"], unique=False
    )
    op.create_index(
        op.f("ix_site_issues_crawl_id"), "site_issues", ["crawl_id"], unique=False
    )
    op.create_index(
        "ix_site_issues_filter",
        "site_issues",
        ["crawl_id", "finding_class", "severity", "category", "rule_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_site_issues_project_id"), "site_issues", ["project_id"], unique=False
    )
    op.create_index(
        op.f("ix_site_issues_site_url_id"), "site_issues", ["site_url_id"], unique=False
    )
    op.create_index(
        "ix_site_issues_url_created",
        "site_issues",
        ["site_url_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_site_issues_workspace_id"),
        "site_issues",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "site_change_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("crawl_a_id", sa.UUID(), nullable=True),
        sa.Column("crawl_b_id", sa.UUID(), nullable=False),
        sa.Column("supersedes_id", sa.UUID(), nullable=True),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("root_origin", sa.String(length=512), nullable=False),
        sa.Column("crawl_scope_hash", sa.String(length=64), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("source_analysis_ids", postgresql.ARRAY(sa.UUID()), nullable=False),
        sa.Column("source_artifact_ids", postgresql.ARRAY(sa.UUID()), nullable=False),
        sa.Column("analyzer_version", sa.String(length=32), nullable=False),
        sa.Column("page_analyzer_version", sa.String(length=32), nullable=False),
        sa.Column("extractor_version", sa.String(length=32), nullable=False),
        sa.Column("complete_pair", sa.Boolean(), nullable=False),
        sa.Column("coverage", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("limitations", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["crawl_a_id", "project_id", "workspace_id"],
            ["site_crawls.id", "site_crawls.project_id", "site_crawls.workspace_id"],
            ondelete="CASCADE",
            name="fk_site_change_snapshot_crawl_a_scoped",
        ),
        sa.ForeignKeyConstraint(
            ["crawl_b_id", "project_id", "workspace_id"],
            ["site_crawls.id", "site_crawls.project_id", "site_crawls.workspace_id"],
            ondelete="CASCADE",
            name="fk_site_change_snapshot_crawl_b_scoped",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["supersedes_id"], [_SITE_CHANGE_SNAPSHOT_FK], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "crawl_a_id",
            "crawl_b_id",
            "source_hash",
            "analyzer_version",
            name="uq_site_change_snapshot_identity",
        ),
        sa.UniqueConstraint("workspace_id", "id", name="uq_site_change_snapshot_ws_id"),
    )
    _create_indexes(
        "site_change_snapshots",
        ("workspace_id", "project_id", "crawl_a_id", "crawl_b_id"),
    )
    op.create_table(
        "site_change_observations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("snapshot_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("site_url_id", sa.UUID(), nullable=False),
        sa.Column("normalized_url", sa.String(length=2048), nullable=False),
        sa.Column("field", sa.String(length=32), nullable=False),
        sa.Column("change_class", sa.String(length=32), nullable=False),
        sa.Column("before_value", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("after_value", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("source_analysis_a_id", sa.UUID(), nullable=True),
        sa.Column("source_analysis_b_id", sa.UUID(), nullable=True),
        sa.Column("source_artifact_a_id", sa.UUID(), nullable=True),
        sa.Column("source_artifact_b_id", sa.UUID(), nullable=True),
        sa.Column("source_evaluation_a_id", sa.UUID(), nullable=True),
        sa.Column("source_evaluation_b_id", sa.UUID(), nullable=True),
        sa.Column("expected", sa.Boolean(), nullable=False),
        sa.Column("implementation_event_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "change_class IN ('improvement', 'neutral-change', "
            "'potential-regression', 'critical-regression')",
            name="ck_site_change_observation_class",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "implementation_event_id"],
            [
                "opportunity_implementation_events.workspace_id",
                "opportunity_implementation_events.id",
            ],
            ondelete="RESTRICT",
            name="fk_site_change_observation_implementation_workspace",
        ),
        sa.ForeignKeyConstraint(["site_url_id"], ["site_urls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "snapshot_id"],
            ["site_change_snapshots.workspace_id", _SITE_CHANGE_SNAPSHOT_FK],
            ondelete="CASCADE",
            name="fk_site_change_observation_snapshot_workspace",
        ),
        sa.ForeignKeyConstraint(
            ["source_analysis_a_id"], ["site_page_analyses.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_analysis_b_id"], ["site_page_analyses.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_artifact_a_id"], ["site_fetch_artifacts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_artifact_b_id"], ["site_fetch_artifacts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_evaluation_a_id"],
            ["site_rule_evaluations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_evaluation_b_id"],
            ["site_rule_evaluations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_id", "site_url_id", "field", name="uq_site_change_observation"
        ),
    )
    _create_indexes(
        "site_change_observations",
        ("snapshot_id", "workspace_id", "site_url_id", "change_class"),
    )
    op.create_table(
        "account_grants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("billing_account_id", sa.UUID(), nullable=False),
        sa.Column("source_kind", sa.String(length=16), nullable=False),
        sa.Column("source_ref", sa.String(length=255), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("catalog_revision", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "period_start IS NULL OR period_end IS NULL OR period_start < period_end",
            name="ck_account_grant_period_ordered",
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from",
            name="ck_account_grant_valid_ordered",
        ),
        sa.CheckConstraint("value >= 0", name="ck_account_grant_value_nonneg"),
        sa.ForeignKeyConstraint(
            ["billing_account_id"], ["billing_accounts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "billing_account_id",
            "idempotency_key",
            "key",
            name="uq_account_grant_bundle_key",
        ),
    )
    op.create_index(
        "ix_account_grant_account_key_valid",
        "account_grants",
        ["billing_account_id", "key", "valid_from"],
        unique=False,
    )
    op.create_index(
        "ix_account_grant_source",
        "account_grants",
        ["source_kind", "source_ref"],
        unique=False,
    )
    op.create_index(
        op.f("ix_account_grants_billing_account_id"),
        "account_grants",
        ["billing_account_id"],
        unique=False,
    )
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("billing_account_id", sa.UUID(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["billing_account_id"], ["billing_accounts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "billing_account_id",
            "idempotency_key",
            name="uq_idempotency_record_account_key",
        ),
    )
    op.create_index(
        "ix_idempotency_record_expiry",
        "idempotency_records",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_idempotency_records_billing_account_id"),
        "idempotency_records",
        ["billing_account_id"],
        unique=False,
    )
    op.create_table(
        "pending_activations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("billing_account_id", sa.UUID(), nullable=False),
        sa.Column("activation_kind", sa.String(length=16), nullable=False),
        sa.Column("catalog_key", sa.String(length=64), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("catalog_revision", sa.String(length=64), nullable=False),
        sa.Column("credential_mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("external_reference", sa.String(length=255), nullable=True),
        sa.Column("external_price_id", sa.String(length=255), nullable=True),
        sa.Column("checkout_url", sa.Text(), nullable=True),
        sa.Column("quote", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("region", sa.String(length=16), nullable=False),
        sa.Column("settled_by", sa.String(length=24), nullable=True),
        sa.Column("settled_authority_id", sa.String(length=255), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "quantity > 0", name="ck_pending_activation_quantity_positive"
        ),
        sa.ForeignKeyConstraint(
            ["billing_account_id"], ["billing_accounts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "billing_account_id",
            "idempotency_key",
            name="uq_pending_activation_account_idempotency",
        ),
    )
    op.create_index(
        "ix_pending_activation_status_created",
        "pending_activations",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_pending_activations_billing_account_id"),
        "pending_activations",
        ["billing_account_id"],
        unique=False,
    )
    op.create_index(
        "uq_pending_activation_provider_reference",
        "pending_activations",
        ["provider", "external_reference"],
        unique=True,
        postgresql_where=sa.text("external_reference IS NOT NULL"),
    )
    # One UNSETTLED base per account and one UNSETTLED add-on per
    # (account, catalog_key): the final guard against two concurrent
    # different-key intents both reaching the provider. Top-ups stay
    # repeatable; transitions out of 'pending' free the slot.
    op.create_index(
        "uq_pending_activation_one_pending_base",
        "pending_activations",
        ["billing_account_id"],
        unique=True,
        postgresql_where=sa.text("activation_kind = 'base' AND status = 'pending'"),
    )
    op.create_index(
        "uq_pending_activation_one_pending_addon",
        "pending_activations",
        ["billing_account_id", "catalog_key"],
        unique=True,
        postgresql_where=sa.text("activation_kind = 'addon' AND status = 'pending'"),
    )
    op.create_table(
        "consumable_ledger",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("billing_account_id", sa.UUID(), nullable=False),
        sa.Column("grant_id", sa.UUID(), nullable=False),
        sa.Column("capability_key", sa.String(length=64), nullable=False),
        sa.Column("entry_kind", sa.String(length=16), nullable=False),
        sa.Column("reservation_id", sa.UUID(), nullable=False),
        sa.Column("audit_id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=True),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(entry_kind = 'debit' AND attempt IS NOT NULL AND attempt > 0) "
            "OR (entry_kind <> 'debit' AND attempt IS NULL)",
            name="ck_consumable_ledger_attempt_shape",
        ),
        sa.CheckConstraint("units > 0", name="ck_consumable_ledger_units_positive"),
        sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["billing_account_id"], ["billing_accounts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["grant_id"], ["account_grants.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["task_id"], ["audit_tasks.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "billing_account_id",
            "idempotency_key",
            name="uq_consumable_ledger_idempotency",
        ),
    )
    op.create_index(
        op.f("ix_consumable_ledger_billing_account_id"),
        "consumable_ledger",
        ["billing_account_id"],
        unique=False,
    )
    op.create_index(
        "ix_consumable_ledger_grant_key_created",
        "consumable_ledger",
        ["grant_id", "capability_key", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_consumable_ledger_reservation_kind",
        "consumable_ledger",
        ["reservation_id", "entry_kind"],
        unique=False,
    )
    op.create_index(
        "uq_consumable_ledger_task_attempt",
        "consumable_ledger",
        ["task_id", "attempt"],
        unique=True,
        postgresql_where=sa.text("entry_kind = 'debit'"),
    )
    op.create_table(
        "grant_revocations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("grant_id", sa.UUID(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("actor_kind", sa.String(length=24), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["grant_id"], ["account_grants.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "grant_id", "idempotency_key", name="uq_grant_revocation_idempotency"
        ),
    )
    op.create_index(
        "ix_grant_revocation_grant_effective",
        "grant_revocations",
        ["grant_id", "effective_from"],
        unique=False,
    )
    op.create_index(
        op.f("ix_grant_revocations_grant_id"),
        "grant_revocations",
        ["grant_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_audit_tasks_result_artifact_id",
        "audit_tasks",
        "raw_response_artifacts",
        ["result_artifact_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.create_foreign_key(
        "fk_site_crawl_tasks_result_artifact_id",
        "site_crawl_tasks",
        "site_fetch_artifacts",
        ["result_artifact_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.create_table(
        "brand_discoveries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("progress", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("input_data", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("profile", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("domains", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("competitors", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("topics", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column(
            "prompt_suggestions", postgresql.JSONB(astext_type=Text()), nullable=False
        ),
        sa.Column("evidence", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("gaps", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("warnings", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("error_code", sa.String(32), nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=False),
        sa.Column("initial_crawl_id", sa.UUID(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["initial_crawl_id"], ["site_crawls.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_brand_discovery_idempotency"
        ),
    )
    op.create_index(
        op.f("ix_brand_discoveries_status"), "brand_discoveries", ["status"]
    )
    op.create_table(
        "brand_discovery_tasks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("discovery_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("task_kind", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("randomized_position", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=32), nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["discovery_id"], ["brand_discoveries.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("discovery_id", name="uq_brand_discovery_task_discovery"),
        sa.UniqueConstraint("idempotency_key", name="uq_brand_discovery_task_key"),
    )
    op.create_index(
        "ix_brand_discovery_tasks_claim",
        "brand_discovery_tasks",
        ["status", "available_at"],
    )
    op.create_index(
        "ix_brand_discovery_tasks_lease",
        "brand_discovery_tasks",
        ["status", "lease_expires_at"],
    )
    op.create_index(
        op.f("ix_brand_discovery_tasks_status"),
        "brand_discovery_tasks",
        ["status"],
    )
    op.create_index(
        op.f("ix_brand_discovery_tasks_available_at"),
        "brand_discovery_tasks",
        ["available_at"],
    )
    # ### end Alembic commands ###

    op.create_table(
        "brand_research_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("discovery_id", sa.UUID(), nullable=False),
        sa.Column("research_version", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(255), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("method", sa.String(64), nullable=False),
        sa.Column(
            "extracted_fields", postgresql.JSONB(astext_type=Text()), nullable=False
        ),
        sa.Column(
            "field_confidence", postgresql.JSONB(astext_type=Text()), nullable=False
        ),
        sa.Column("evidence", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("warnings", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["discovery_id"], ["brand_discoveries.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "discovery_id", "research_version", name="uq_brand_research_version"
        ),
    )
    op.create_index(
        op.f("ix_brand_research_snapshots_workspace_id"),
        "brand_research_snapshots",
        ["workspace_id"],
    )
    op.create_index(
        op.f("ix_brand_research_snapshots_discovery_id"),
        "brand_research_snapshots",
        ["discovery_id"],
    )

    op.create_table(
        "prompt_metric_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("audit_id", sa.UUID(), nullable=False),
        sa.Column("prompt_id", sa.UUID(), nullable=True),
        sa.Column("prompt_identity", sa.String(64), nullable=False),
        sa.Column("prompt_index", sa.Integer(), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("cohort", sa.String(32), nullable=False),
        sa.Column("analyzer_version", sa.String(32), nullable=False),
        sa.Column("scoring_rule_version", sa.String(32), nullable=False),
        sa.Column("composite_score", sa.Float(), nullable=False),
        sa.Column("previous_score", sa.Float(), nullable=True),
        sa.Column("immediate_delta", sa.Float(), nullable=True),
        sa.Column("rolling_four", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column(
            "per_engine_scores", postgresql.JSONB(astext_type=Text()), nullable=False
        ),
        sa.Column("components", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("engine_agreement", sa.Float(), nullable=False),
        sa.Column("repetition_agreement", sa.Float(), nullable=False),
        sa.Column("evidence_coverage", sa.Float(), nullable=False),
        sa.Column("trend_confidence", sa.Float(), nullable=False),
        sa.Column("decline_confirmed", sa.Boolean(), nullable=False),
        sa.Column(
            "source_analysis_ids", postgresql.JSONB(astext_type=Text()), nullable=False
        ),
        sa.Column(
            "source_artifact_ids", postgresql.JSONB(astext_type=Text()), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["prompt_id"], ["prompts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "audit_id", "prompt_identity", name="uq_prompt_metric_audit_identity"
        ),
    )
    _create_indexes(
        "prompt_metric_snapshots",
        (
            "workspace_id",
            "project_id",
            "audit_id",
            "prompt_id",
            "cohort",
            "decline_confirmed",
            "created_at",
        ),
    )
    op.create_index(
        "ix_prompt_metric_history",
        "prompt_metric_snapshots",
        ["project_id", "prompt_identity", sa.text("created_at DESC")],
    )

    op.create_table(
        "observed_entity_candidates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("audit_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("qualification_reason", sa.Text(), nullable=False),
        sa.Column("prompt_count", sa.Integer(), nullable=False),
        sa.Column("engine_count", sa.Integer(), nullable=False),
        sa.Column("market_relevant", sa.Boolean(), nullable=False),
        sa.Column("analyzer_version", sa.String(32), nullable=False),
        sa.Column(
            "source_analysis_ids", postgresql.JSONB(astext_type=Text()), nullable=False
        ),
        sa.Column(
            "source_artifact_ids", postgresql.JSONB(astext_type=Text()), nullable=False
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("audit_id", "domain", name="uq_observed_candidate_domain"),
    )
    _create_indexes(
        "observed_entity_candidates",
        ("workspace_id", "project_id", "audit_id", "status"),
    )

    # --- Demand Intelligence ---------------------------------------------
    op.create_table(
        "demand_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("prior_snapshot_id", sa.UUID(), nullable=True),
        sa.Column(
            "source_artifact_ids", postgresql.JSONB(astext_type=Text()), nullable=False
        ),
        sa.Column(
            "source_metric_row_ids",
            postgresql.JSONB(astext_type=Text()),
            nullable=False,
        ),
        sa.Column("coverage", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("comparison", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("formula_version", sa.String(length=32), nullable=False),
        sa.Column("analyzer_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["prior_snapshot_id"], [_DEMAND_SNAPSHOT_FK], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "source_hash", name="uq_demand_snapshot_source_hash"
        ),
    )
    _create_indexes("demand_snapshots", ("workspace_id", "project_id", "created_at"))
    op.create_foreign_key(
        "fk_opportunity_snapshots_demand_snapshot_id",
        "opportunity_snapshots",
        "demand_snapshots",
        ["demand_snapshot_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "demand_signals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("snapshot_id", sa.UUID(), nullable=False),
        sa.Column("identity_hash", sa.String(length=64), nullable=False),
        sa.Column("signal_type", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("topic_cluster", sa.String(length=512), nullable=False),
        sa.Column("page_url", sa.String(length=2048), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("coverage", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("limitations", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("priority_score", sa.Float(), nullable=True),
        sa.Column(
            "priority_inputs", postgresql.JSONB(astext_type=Text()), nullable=False
        ),
        sa.Column("analyzer_version", sa.String(length=32), nullable=False),
        sa.Column("rule_version", sa.String(length=32), nullable=False),
        sa.Column("formula_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], [_DEMAND_SNAPSHOT_FK], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_id", "identity_hash", name="uq_demand_signal_identity"
        ),
    )
    _create_indexes(
        "demand_signals",
        ("workspace_id", "project_id", "snapshot_id", "signal_type", "state"),
    )

    op.create_table(
        "query_evidence_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("supersedes_snapshot_id", sa.UUID(), nullable=True),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column(
            "source_metric_row_ids",
            postgresql.JSONB(astext_type=Text()),
            nullable=False,
        ),
        sa.Column(
            "source_artifact_ids", postgresql.JSONB(astext_type=Text()), nullable=False
        ),
        sa.Column("coverage", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("limitations", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("analyzer_version", sa.String(length=32), nullable=False),
        sa.Column("resolver_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["supersedes_snapshot_id"],
            ["query_evidence_snapshots.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "project_id",
            "window_start",
            "window_end",
            "source_hash",
            "analyzer_version",
            name="uq_query_evidence_snapshot_identity",
        ),
    )
    _create_indexes(
        "query_evidence_snapshots", ("workspace_id", "project_id", "created_at")
    )
    op.create_table(
        "query_evidence_rows",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("snapshot_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("normalized_query", sa.String(length=512), nullable=False),
        sa.Column("observed_page_url", sa.String(length=2048), nullable=False),
        sa.Column("site_url_id", sa.UUID(), nullable=True),
        sa.Column("resolved_page_url", sa.String(length=2048), nullable=False),
        sa.Column("resolution_outcome", sa.String(length=16), nullable=False),
        sa.Column(
            "resolution_candidates",
            postgresql.JSONB(astext_type=Text()),
            nullable=False,
        ),
        sa.Column("property_ref", sa.String(length=512), nullable=False),
        sa.Column("impressions", sa.Integer(), nullable=False),
        sa.Column("clicks", sa.Integer(), nullable=False),
        sa.Column("ctr", sa.Float(), nullable=True),
        sa.Column("position", sa.Float(), nullable=True),
        sa.Column("source_metric_row_id", sa.UUID(), nullable=False),
        sa.Column("source_artifact_id", sa.UUID(), nullable=False),
        sa.Column("importer_version", sa.String(length=64), nullable=False),
        sa.Column("resolver_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_url_id"], ["site_urls.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["query_evidence_snapshots.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_id",
            "source_metric_row_id",
            name="uq_query_evidence_source_row",
        ),
    )
    _create_indexes(
        "query_evidence_rows",
        (
            "snapshot_id",
            "workspace_id",
            "project_id",
            "date",
            "normalized_query",
            "resolution_outcome",
        ),
    )
    op.create_index(
        "ix_query_evidence_page_time",
        "query_evidence_rows",
        ["workspace_id", "project_id", "site_url_id", "date"],
    )

    op.create_table(
        "branded_query_overrides",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "ordinal",
            sa.BigInteger(),
            sa.Identity(always=False),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("normalized_query", sa.String(length=512), nullable=False),
        sa.Column("classification", sa.String(length=16), nullable=False),
        sa.Column("classifier_version", sa.String(length=32), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ordinal"),
    )
    _create_indexes("branded_query_overrides", ("workspace_id", "project_id"))
    op.create_index(
        "ix_branded_query_override_lookup",
        "branded_query_overrides",
        ["workspace_id", "project_id", "normalized_query", "ordinal"],
    )

    # --- Bounded Growth Agent --------------------------------------------
    op.create_table(
        "agent_task_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("task_policy_version", sa.String(length=32), nullable=False),
        sa.Column(
            "allowed_tools", postgresql.JSONB(astext_type=Text()), nullable=False
        ),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("provider_adapter", sa.String(length=64), nullable=False),
        sa.Column("endpoint_host", sa.String(length=255), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("instruction_version", sa.String(length=64), nullable=False),
        sa.Column("usage", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_agent_run_ws_idempotency"
        ),
    )
    _create_indexes(
        "agent_task_runs",
        ("workspace_id", "project_id", "status", "available_at"),
    )
    op.create_index(
        "ix_agent_task_runs_project_created",
        "agent_task_runs",
        ["project_id", "created_at", "id"],
    )
    op.create_index(
        "ix_agent_task_runs_claim",
        "agent_task_runs",
        ["status", "available_at", "created_at"],
    )

    op.create_table(
        "agent_tool_attempts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("task_run_id", sa.UUID(), nullable=False),
        sa.Column("run_attempt", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("tool_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("input", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column(
            "artifact_refs", postgresql.JSONB(astext_type=Text()), nullable=False
        ),
        sa.Column("output_hash", sa.String(length=64), nullable=False),
        sa.Column("omissions", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=False),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["task_run_id"], [_AGENT_TASK_RUN_FK], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_run_id",
            "run_attempt",
            "ordinal",
            name="uq_agent_tool_attempt_slot",
        ),
    )
    _create_indexes(
        "agent_tool_attempts", ("workspace_id", "project_id", "task_run_id")
    )
    _COMMERCE_SCHEMA.upgrade()


def downgrade() -> None:
    # This is the repository's sole greenfield revision. The Commerce rebuild
    # retires tables that the earlier body creates before the final schema is
    # installed, so replaying the generated reverse delta would recreate those
    # retired authorities. Drop the explicit final table set instead.
    final_tables = (
        "site_issues",
        "site_observed_architectures",
        "site_page_link_metrics",
        "site_change_observations",
        "referral_classifications",
        "opportunity_verification_events",
        "commerce_product_categories",
        "commerce_observation_citations",
        "site_rule_evaluations",
        "referral_events",
        "opportunity_implementation_events",
        "content_generation_attempts",
        "competitor_mentions",
        "commerce_product_observations",
        "commerce_category_observations",
        "commerce_categories",
        "citations",
        "brand_mentions",
        "traffic_page_stats",
        "site_url_observations",
        "site_page_analyses",
        "response_analyses",
        "query_evidence_rows",
        "provider_attempts",
        "prompt_metric_snapshots",
        "opportunity_status_events",
        "opportunity_snapshots",
        "opportunity_guidance",
        "observed_entity_candidates",
        "monitored_site_urls",
        "metric_snapshots",
        "integration_metric_rows",
        "execution_cost_projections",
        "content_generations",
        "consumable_ledger",
        "commerce_shelf_snapshots",
        "commerce_recommendation_observations",
        "brand_research_snapshots",
        "brand_discovery_tasks",
        "audit_prompt_snapshots",
        "audit_events",
        "audit_engine_snapshots",
        "site_urls",
        "site_health_snapshots",
        "site_fetch_attempts",
        "site_discovery_frontier",
        "site_crawl_phase_runs",
        "site_crawl_events",
        "site_change_snapshots",
        "opportunities",
        "integration_import_artifacts",
        "commerce_prompt_targets",
        "commerce_competitor_candidates",
        "brand_discoveries",
        "audits",
        "traffic_query_stats",
        "site_crawls",
        "provider_capacity_leases",
        "prompts",
        "integration_sync_runs",
        "integration_property_mappings",
        "integration_events",
        "grant_revocations",
        "demand_signals",
        "commerce_competitor_attempts",
        "brand_profiles",
        "brand_aliases",
        "billing_subscriptions",
        "audit_schedules",
        "agent_tool_attempts",
        "workspace_billing_links",
        "unintended_domains",
        "traffic_snapshots",
        "topics",
        "site_health_profiles",
        "query_evidence_snapshots",
        "provider_routes",
        "provider_connection_tests",
        "provider_capacity_buckets",
        "prompt_sets",
        "pending_activations",
        "owned_domains",
        "opportunity_orders",
        "integration_connections",
        "idempotency_records",
        "discovery_model_configs",
        "demand_snapshots",
        "competitors",
        "commerce_products",
        "commerce_csv_imports",
        "brands",
        "branded_query_overrides",
        "billing_customers",
        "analytics_tasks",
        "ai_referrals_snapshots",
        "agent_task_runs",
        "account_grants",
        "workspace_site_health_runtime",
        "workspace_members",
        "queue_workspace_turns",
        "provider_connections",
        "projects",
        "integration_oauth_states",
        "integration_oauth_grants",
        "billing_accounts",
        "workspaces",
        "users",
        "usage_windows",
        "site_fetch_artifacts",
        "site_crawl_tasks",
        "raw_response_artifacts",
        "brand_logo_assets",
        "billing_webhook_events",
        "audit_tasks",
    )
    for table_name in final_tables:
        op.execute(sa.text(f'DROP TABLE IF EXISTS "{table_name}" CASCADE'))
