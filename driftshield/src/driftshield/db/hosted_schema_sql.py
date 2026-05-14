"""Hosted Aurora schema SQL for the Phase 3h intake and Teams runtime path."""

from __future__ import annotations


def build_hosted_base_sql() -> tuple[str, ...]:
    return (
        """
        do $$
        begin
            if not exists (select 1 from pg_type where typname = 'submission_state') then
                create type submission_state as enum (
                    'received',
                    'processing',
                    'processed',
                    'quarantined',
                    'failed',
                    'duplicate'
                );
            end if;
        end
        $$
        """,
        "create extension if not exists pgcrypto",
        """
        create table if not exists installations (
            id uuid primary key default gen_random_uuid(),
            installation_id text not null unique,
            client_name text,
            platform text not null,
            app_version text,
            metadata jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default timezone('utc', now()),
            updated_at timestamptz not null default timezone('utc', now())
        )
        """,
        """
        create table if not exists consent_records (
            id uuid primary key default gen_random_uuid(),
            installation_id uuid not null references installations(id) on delete cascade,
            consent_version text not null,
            consent_granted boolean not null,
            consent_scope jsonb not null default '{}'::jsonb,
            captured_at timestamptz not null,
            revoked_at timestamptz,
            created_at timestamptz not null default timezone('utc', now())
        )
        """,
        """
        create table if not exists submissions (
            id uuid primary key default gen_random_uuid(),
            installation_id uuid not null references installations(id) on delete restrict,
            consent_record_id uuid not null references consent_records(id) on delete restrict,
            submission_id text not null unique,
            source_system text not null,
            source_session_id text not null,
            source_report_id text,
            envelope_contract_version text not null,
            envelope jsonb not null,
            envelope_checksum text not null,
            state submission_state not null default 'received',
            duplicate_of_submission_id uuid references submissions(id) on delete set null,
            received_at timestamptz not null default timezone('utc', now()),
            processing_started_at timestamptz,
            processed_at timestamptz,
            quarantined_at timestamptz,
            failed_at timestamptz,
            last_error_code text,
            last_error_detail text,
            created_at timestamptz not null default timezone('utc', now()),
            updated_at timestamptz not null default timezone('utc', now())
        )
        """,
        "create index if not exists ix_submissions_state_received_at on submissions (state, received_at)",
        """
        create table if not exists trust_evaluations (
            id uuid primary key default gen_random_uuid(),
            submission_id uuid not null references submissions(id) on delete cascade,
            trust_band text not null,
            confidence_band text not null default 'high',
            structural_score double precision,
            semantic_score double precision,
            source_factor double precision,
            final_learning_weight double precision,
            learning_eligible boolean not null default false,
            requires_review boolean not null default false,
            downgrade_reasons jsonb not null default '[]'::jsonb,
            quarantine_reason_codes jsonb not null default '[]'::jsonb,
            provenance jsonb not null default '{}'::jsonb,
            evaluation_metadata jsonb not null default '{}'::jsonb,
            write_order bigint not null generated always as identity,
            created_at timestamptz not null default timezone('utc', now())
        )
        """,
        """
        create table if not exists signature_matches (
            id uuid primary key default gen_random_uuid(),
            submission_id uuid not null references submissions(id) on delete cascade,
            signature_id text not null,
            signature_version text,
            match_status text not null,
            confidence double precision,
            mechanism_id text,
            evidence jsonb not null default '{}'::jsonb,
            confidence_breakdown jsonb,
            review_needed boolean not null default false,
            visibility_class text not null default 'internal_only',
            recurrence_group_key text,
            created_at timestamptz not null default timezone('utc', now())
        )
        """,
        """
        create table if not exists recurrence_observations (
            id uuid primary key default gen_random_uuid(),
            submission_id uuid not null references submissions(id) on delete cascade,
            observation_key text not null,
            recurrence_group_key text,
            observed_at timestamptz not null,
            observation_payload jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default timezone('utc', now())
        )
        """,
        """
        create table if not exists pattern_objects (
            id uuid primary key default gen_random_uuid(),
            pattern_key text not null unique,
            maturity_level text not null,
            status text not null,
            summary jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default timezone('utc', now()),
            updated_at timestamptz not null default timezone('utc', now())
        )
        """,
        """
        create table if not exists pattern_signature_links (
            id uuid primary key default gen_random_uuid(),
            pattern_object_id uuid not null references pattern_objects(id) on delete cascade,
            signature_id text not null,
            linked_at timestamptz not null default timezone('utc', now()),
            metadata jsonb not null default '{}'::jsonb,
            unique (pattern_object_id, signature_id)
        )
        """,
        """
        create table if not exists distribution_events (
            id uuid primary key default gen_random_uuid(),
            manifest_version text not null,
            artifact_checksum text not null,
            artifact_url text,
            distributed_at timestamptz not null,
            metadata jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default timezone('utc', now())
        )
        """,
    )


def build_hosted_base_drop_sql() -> tuple[str, ...]:
    return (
        "drop table if exists distribution_events",
        "drop table if exists pattern_signature_links",
        "drop table if exists pattern_objects",
        "drop table if exists recurrence_observations",
        "drop table if exists signature_matches",
        "drop table if exists trust_evaluations",
        "drop table if exists submissions",
        "drop table if exists consent_records",
        "drop table if exists installations",
        "drop type if exists submission_state",
    )


def build_phase3h_oss_fallback_installation_seed_sql() -> tuple[str, str, str]:
    return (
        """
        insert into installations (
            id,
            installation_id,
            client_name,
            platform,
            metadata
        )
        values (
            '00000000-0000-0000-0000-000000000551',
            'oss-fallback-installation',
            'OSS fallback installation',
            'aws-lambda',
            jsonb_build_object(
                'seed_source', 'alembic',
                'persona', 'oss-fallback'
            )
        )
        on conflict (installation_id) do nothing
        """,
        """
        insert into consent_records (
            id,
            installation_id,
            consent_version,
            consent_granted,
            captured_at,
            revoked_at
        )
        values (
            '00000000-0000-0000-0000-000000000c51',
            (select id from installations where installation_id = 'oss-fallback-installation'),
            'phase3f-consent.v1',
            true,
            '2026-05-12T00:00:00+00:00'::timestamptz,
            null
        )
        on conflict (id) do nothing
        """,
        """
        select
            installations.id as installation_row_id,
            consent_records.id as consent_record_id
        from installations
        inner join consent_records on consent_records.installation_id = installations.id
        where installations.installation_id = 'oss-fallback-installation'
          and consent_records.id = '00000000-0000-0000-0000-000000000c51'
        """,
    )
