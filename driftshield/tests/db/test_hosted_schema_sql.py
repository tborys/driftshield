from driftshield.db.hosted_schema_sql import (
    build_hosted_base_drop_sql,
    build_hosted_base_sql,
    build_phase3h_team_pattern_sql,
    build_phase3h_team_recurrence_sql,
    build_phase3h_team_views_drop_sql,
    build_phase3h_teams_drop_sql,
    build_phase3h_teams_sql,
)


def test_hosted_base_sql_covers_phase3f_and_phase3g_tables() -> None:
    sql = "\n".join(build_hosted_base_sql())

    for table_name in (
        "installations",
        "consent_records",
        "submissions",
        "trust_evaluations",
        "signature_matches",
        "recurrence_observations",
        "pattern_objects",
        "pattern_signature_links",
        "distribution_events",
    ):
        assert f"create table if not exists {table_name}" in sql

    assert "create type submission_state as enum" in sql
    assert "confidence_band text not null default 'high'" in sql
    assert "learning_eligible boolean not null default false" in sql
    assert "evaluation_metadata jsonb not null default '{}'::jsonb" in sql
    assert "write_order bigint not null generated always as identity" in sql
    assert "mechanism_id text" in sql
    assert "confidence_breakdown jsonb" in sql
    assert "review_needed boolean not null default false" in sql
    assert "visibility_class text not null default 'internal_only'" in sql
    assert "recurrence_group_key text" in sql


def test_phase3h_teams_sql_covers_identity_tables_and_submission_scope_columns() -> None:
    sql = "\n".join(build_phase3h_teams_sql())

    for table_name in (
        "tenants",
        "workspaces",
        "service_identities",
        "entitlements",
        "team_api_access_audit",
    ):
        assert f"create table if not exists {table_name}" in sql

    assert "tenant_id uuid references tenants(id) on delete set null" in sql
    assert "workspace_id uuid references workspaces(id) on delete set null" in sql
    assert "service_identity_id uuid references service_identities(id) on delete set null" in sql
    assert "workflow_reference text" in sql
    assert "project_reference text" in sql
    assert "evidence_artifact_prefix text" in sql
    assert "attempt_count integer not null default 0" in sql
    assert "claimed_by text" in sql
    assert "ix_submissions_tenant_workspace_received_at" in sql
    assert "tenant_public_id text" in sql
    assert "service_identity_public_id text" in sql


def test_phase3h_team_recurrence_sql_creates_expected_view_shape() -> None:
    sql = "\n".join(build_phase3h_team_recurrence_sql())

    assert "create or replace view team_recurrence_summary as" in sql
    assert "latest_trust_evaluations as (" in sql
    assert "selected_trust_evaluations as (" in sql
    assert "submissions.tenant_id as tenant_row_id" in sql
    assert "tenants.tenant_id" in sql
    assert "signature_matches.recurrence_group_key" in sql
    assert "workflow_diversity_count" in sql
    assert "Treat null final_learning_weight as zero so non-weighted rows stay out of recurrence summaries." in sql
    assert "jsonb_object_agg" in sql
    assert "ix_signature_matches_recurrence_group_signature" in sql
    assert "ix_trust_evaluations_submission_created_at_write_order" in sql
    assert "ix_submissions_tenant_workspace_workflow_project" in sql


def test_phase3h_team_pattern_sql_creates_expected_view_shape() -> None:
    sql = "\n".join(build_phase3h_team_pattern_sql())

    assert "create or replace view team_pattern_summary as" in sql
    assert "signature_family_rollup" in sql
    assert "workflow_distribution" in sql
    assert "trend_direction" in sql
    assert "jsonb_build_object" in sql
    assert "Treat null final_learning_weight as zero so non-weighted rows stay out of pattern summaries." in sql
    assert "recent_count" in sql
    assert "previous_count" in sql
    assert "split_part(signature_matches.signature_id, '.', 1)" in sql


def test_drop_sql_removes_views_before_supporting_schema() -> None:
    team_drop_sql = build_phase3h_teams_drop_sql()
    views_drop_sql = build_phase3h_team_views_drop_sql()
    base_drop_sql = build_hosted_base_drop_sql()

    assert views_drop_sql[0] == "drop view if exists team_pattern_summary"
    assert views_drop_sql[1] == "drop view if exists team_recurrence_summary"
    assert team_drop_sql[-1] == "drop table if exists tenants"
    assert base_drop_sql[-1] == "drop type if exists submission_state"
