from driftshield.db.hosted_schema_sql import (
    build_hosted_base_drop_sql,
    build_hosted_base_sql,
)


def test_hosted_base_sql_covers_oss_tier_tables() -> None:
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


def test_hosted_base_drop_sql_drops_submission_state_last() -> None:
    base_drop_sql = build_hosted_base_drop_sql()

    assert base_drop_sql[-1] == "drop type if exists submission_state"
