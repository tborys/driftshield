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
            attempt_count integer not null default 0,
            received_at timestamptz not null default timezone('utc', now()),
            processing_started_at timestamptz,
            processed_at timestamptz,
            quarantined_at timestamptz,
            failed_at timestamptz,
            claimed_by text,
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
            workflow_id text,
            mechanism_id text,
            trust_band text,
            confidence_band text,
            learning_weight double precision,
            contributes_to_recurrence boolean,
            supports_maturation boolean,
            quarantine_reason_codes text[],
            signature_ids text[],
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


def build_phase3h_teams_sql() -> tuple[str, ...]:
    return (
        """
        create table if not exists tenants (
            id uuid primary key default gen_random_uuid(),
            tenant_id text not null unique,
            display_name text,
            tenancy_state text not null default 'active',
            home_region text not null default 'eu-west-2',
            deployment_target text not null default 'aurora-postgresql-serverless-v2',
            metadata jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default timezone('utc', now()),
            updated_at timestamptz not null default timezone('utc', now())
        )
        """,
        """
        create table if not exists workspaces (
            id uuid primary key default gen_random_uuid(),
            tenant_id uuid not null references tenants(id) on delete cascade,
            workspace_id text not null,
            display_name text,
            project_reference text,
            metadata jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default timezone('utc', now()),
            updated_at timestamptz not null default timezone('utc', now()),
            unique (tenant_id, workspace_id)
        )
        """,
        """
        create table if not exists service_identities (
            id uuid primary key default gen_random_uuid(),
            tenant_id uuid not null references tenants(id) on delete cascade,
            workspace_id uuid references workspaces(id) on delete set null,
            service_identity_id text not null,
            display_name text,
            auth_method text not null default 'api_key',
            secret_reference text,
            status text not null default 'active',
            metadata jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default timezone('utc', now()),
            updated_at timestamptz not null default timezone('utc', now()),
            unique (tenant_id, service_identity_id)
        )
        """,
        """
        create table if not exists entitlements (
            id uuid primary key default gen_random_uuid(),
            tenant_id uuid not null references tenants(id) on delete cascade,
            workspace_id uuid references workspaces(id) on delete cascade,
            service_identity_id uuid references service_identities(id) on delete cascade,
            access_tier text not null,
            subject_scope text not null default 'tenant',
            capabilities jsonb not null default '[]'::jsonb,
            metadata jsonb not null default '{}'::jsonb,
            effective_from timestamptz not null default timezone('utc', now()),
            effective_to timestamptz,
            created_at timestamptz not null default timezone('utc', now())
        )
        """,
        "alter table submissions add column if not exists tenant_id uuid references tenants(id) on delete set null",
        "alter table submissions add column if not exists workspace_id uuid references workspaces(id) on delete set null",
        "alter table submissions add column if not exists service_identity_id uuid references service_identities(id) on delete set null",
        "alter table submissions add column if not exists workflow_reference text",
        "alter table submissions add column if not exists project_reference text",
        "alter table submissions add column if not exists evidence_artifact_prefix text",
        "alter table submissions add column if not exists attempt_count integer not null default 0",
        "alter table submissions add column if not exists claimed_by text",
        "alter table recurrence_observations add column if not exists workflow_id text",
        "alter table recurrence_observations add column if not exists mechanism_id text",
        "alter table recurrence_observations add column if not exists trust_band text",
        "alter table recurrence_observations add column if not exists confidence_band text",
        "alter table recurrence_observations add column if not exists learning_weight double precision",
        "alter table recurrence_observations add column if not exists contributes_to_recurrence boolean",
        "alter table recurrence_observations add column if not exists supports_maturation boolean",
        "alter table recurrence_observations add column if not exists quarantine_reason_codes text[]",
        "alter table recurrence_observations add column if not exists signature_ids text[]",
        "create index if not exists ix_submissions_tenant_workspace_received_at on submissions (tenant_id, workspace_id, received_at)",
        """
        create table if not exists team_api_access_audit (
            id uuid primary key default gen_random_uuid(),
            tenant_id uuid references tenants(id) on delete set null,
            tenant_public_id text,
            workspace_id uuid references workspaces(id) on delete set null,
            workspace_public_id text,
            service_identity_id uuid references service_identities(id) on delete set null,
            service_identity_public_id text,
            endpoint text not null,
            http_method text not null,
            auth_source text not null,
            decision text not null,
            access_tier text,
            denial_reason text,
            requested_tenant_id text,
            requested_workspace_id text,
            metadata jsonb not null default '{}'::jsonb,
            logged_at timestamptz not null default timezone('utc', now()),
            created_at timestamptz not null default timezone('utc', now())
        )
        """,
        "create index if not exists ix_team_api_access_audit_tenant_logged_at on team_api_access_audit (tenant_id, logged_at)",
        "create index if not exists ix_team_api_access_audit_service_identity_logged_at on team_api_access_audit (service_identity_id, logged_at)",
    )


def build_phase3h_teams_drop_sql() -> tuple[str, ...]:
    return (
        "drop index if exists ix_team_api_access_audit_service_identity_logged_at",
        "drop index if exists ix_team_api_access_audit_tenant_logged_at",
        "drop table if exists team_api_access_audit",
        "drop index if exists ix_submissions_tenant_workspace_received_at",
        "alter table submissions drop column if exists evidence_artifact_prefix",
        "alter table submissions drop column if exists project_reference",
        "alter table submissions drop column if exists workflow_reference",
        "alter table submissions drop column if exists service_identity_id",
        "alter table submissions drop column if exists workspace_id",
        "alter table submissions drop column if exists tenant_id",
        "drop table if exists entitlements",
        "drop table if exists service_identities",
        "drop table if exists workspaces",
        "drop table if exists tenants",
    )


def build_phase3h_team_recurrence_sql() -> tuple[str, ...]:
    return (
        "create index if not exists ix_signature_matches_recurrence_group_signature on signature_matches (recurrence_group_key, signature_id, submission_id)",
        "create index if not exists ix_trust_evaluations_submission_created_at_write_order on trust_evaluations (submission_id, created_at desc, write_order desc)",
        "create index if not exists ix_submissions_tenant_workspace_workflow_project on submissions (tenant_id, workspace_id, workflow_reference, project_reference)",
        """
        create or replace view team_recurrence_summary as
        with latest_trust_evaluations as (
            select distinct on (trust_evaluations.submission_id)
                trust_evaluations.submission_id,
                trust_evaluations.trust_band,
                trust_evaluations.learning_eligible,
                coalesce(trust_evaluations.final_learning_weight, 0.0) as learning_weight
            from trust_evaluations
            order by
                trust_evaluations.submission_id,
                trust_evaluations.created_at desc,
                trust_evaluations.write_order desc
        ),
        selected_trust_evaluations as (
            select
                latest_trust_evaluations.submission_id,
                latest_trust_evaluations.trust_band,
                latest_trust_evaluations.learning_weight
            from latest_trust_evaluations
            where latest_trust_evaluations.learning_eligible is true
              and latest_trust_evaluations.trust_band in ('trusted', 'provisional')
              -- Treat null final_learning_weight as zero so non-weighted rows stay out of recurrence summaries.
              and latest_trust_evaluations.learning_weight > 0
        ),
        recurrence_base as (
            select distinct
                submissions.tenant_id as tenant_row_id,
                tenants.tenant_id,
                submissions.workspace_id as workspace_row_id,
                workspaces.workspace_id,
                submissions.workflow_reference,
                submissions.project_reference,
                signature_matches.recurrence_group_key,
                signature_matches.signature_id,
                coalesce(submissions.processed_at, submissions.received_at) as observed_at,
                selected_trust_evaluations.trust_band,
                selected_trust_evaluations.learning_weight,
                coalesce(
                    nullif(submissions.envelope ->> 'environment', ''),
                    nullif(submissions.envelope #>> '{context,environment}', ''),
                    nullif(submissions.envelope #>> '{metadata,environment}', ''),
                    'unknown'
                ) as environment_name,
                submissions.id as submission_row_id
            from submissions
            inner join tenants on tenants.id = submissions.tenant_id
            left join workspaces on workspaces.id = submissions.workspace_id
            inner join selected_trust_evaluations on selected_trust_evaluations.submission_id = submissions.id
            inner join signature_matches on signature_matches.submission_id = submissions.id
            where submissions.tenant_id is not null
              and signature_matches.recurrence_group_key is not null
              and signature_matches.recurrence_group_key <> ''
        ),
        summary_base as (
            select
                tenant_row_id,
                tenant_id,
                workspace_row_id,
                workspace_id,
                workflow_reference,
                project_reference,
                recurrence_group_key,
                signature_id,
                min(observed_at) as first_seen_at,
                max(observed_at) as last_seen_at,
                count(distinct submission_row_id) as occurrence_count,
                count(distinct case when trust_band = 'trusted' then submission_row_id end) as trusted_occurrence_count,
                round(sum(learning_weight)::numeric, 3)::double precision as weighted_occurrence_count,
                count(distinct workflow_reference) filter (where workflow_reference is not null) as workflow_diversity_count
            from recurrence_base
            group by tenant_row_id, tenant_id, workspace_row_id, workspace_id, workflow_reference, project_reference, recurrence_group_key, signature_id
        ),
        environment_counts as (
            select
                tenant_row_id,
                tenant_id,
                workspace_row_id,
                workspace_id,
                workflow_reference,
                project_reference,
                recurrence_group_key,
                signature_id,
                environment_name,
                count(distinct submission_row_id) as occurrence_count
            from recurrence_base
            group by tenant_row_id, tenant_id, workspace_row_id, workspace_id, workflow_reference, project_reference, recurrence_group_key, signature_id, environment_name
        ),
        environment_distribution as (
            select
                tenant_row_id,
                tenant_id,
                workspace_row_id,
                workspace_id,
                workflow_reference,
                project_reference,
                recurrence_group_key,
                signature_id,
                coalesce(
                    jsonb_object_agg(environment_name, occurrence_count order by environment_name)
                        filter (where environment_name is not null),
                    '{}'::jsonb
                ) as environment_distribution
            from environment_counts
            group by tenant_row_id, tenant_id, workspace_row_id, workspace_id, workflow_reference, project_reference, recurrence_group_key, signature_id
        )
        select
            summary_base.tenant_row_id,
            summary_base.tenant_id,
            summary_base.workspace_row_id,
            summary_base.workspace_id,
            summary_base.workflow_reference,
            summary_base.project_reference,
            summary_base.recurrence_group_key,
            summary_base.signature_id,
            summary_base.first_seen_at,
            summary_base.last_seen_at,
            summary_base.occurrence_count,
            summary_base.trusted_occurrence_count,
            summary_base.weighted_occurrence_count,
            summary_base.workflow_diversity_count,
            coalesce(environment_distribution.environment_distribution, '{}'::jsonb) as environment_distribution
        from summary_base
        left join environment_distribution
          on environment_distribution.tenant_row_id = summary_base.tenant_row_id
         and environment_distribution.tenant_id = summary_base.tenant_id
         and environment_distribution.workspace_row_id is not distinct from summary_base.workspace_row_id
         and environment_distribution.workspace_id is not distinct from summary_base.workspace_id
         and environment_distribution.workflow_reference is not distinct from summary_base.workflow_reference
         and environment_distribution.project_reference is not distinct from summary_base.project_reference
         and environment_distribution.recurrence_group_key = summary_base.recurrence_group_key
         and environment_distribution.signature_id = summary_base.signature_id
        """,
    )


def build_phase3h_team_pattern_sql() -> tuple[str, ...]:
    return (
        """
        create or replace view team_pattern_summary as
        with latest_trust_evaluations as (
            select distinct on (trust_evaluations.submission_id)
                trust_evaluations.submission_id,
                trust_evaluations.trust_band,
                trust_evaluations.learning_eligible,
                trust_evaluations.write_order,
                coalesce(trust_evaluations.final_learning_weight, 0.0) as learning_weight
            from trust_evaluations
            order by
                trust_evaluations.submission_id,
                trust_evaluations.created_at desc,
                trust_evaluations.write_order desc
        ),
        selected_trust_evaluations as (
            select
                latest_trust_evaluations.submission_id,
                latest_trust_evaluations.trust_band,
                latest_trust_evaluations.write_order,
                latest_trust_evaluations.learning_weight
            from latest_trust_evaluations
            where latest_trust_evaluations.learning_eligible is true
              and latest_trust_evaluations.trust_band in ('trusted', 'provisional')
              -- Treat null final_learning_weight as zero so non-weighted rows stay out of pattern summaries.
              and latest_trust_evaluations.learning_weight > 0
        ),
        pattern_base as (
            select distinct
                submissions.tenant_id as tenant_row_id,
                tenants.tenant_id,
                submissions.workspace_id as workspace_row_id,
                workspaces.workspace_id,
                signature_matches.recurrence_group_key,
                signature_matches.signature_id,
                coalesce(
                    nullif(split_part(signature_matches.signature_id, '.', 1), ''),
                    signature_matches.signature_id
                ) as signature_family,
                coalesce(submissions.processed_at, submissions.received_at) as observed_at,
                selected_trust_evaluations.trust_band,
                selected_trust_evaluations.write_order,
                submissions.workflow_reference,
                submissions.id as submission_row_id
            from submissions
            inner join tenants on tenants.id = submissions.tenant_id
            left join workspaces on workspaces.id = submissions.workspace_id
            inner join selected_trust_evaluations on selected_trust_evaluations.submission_id = submissions.id
            inner join signature_matches on signature_matches.submission_id = submissions.id
            where submissions.tenant_id is not null
              and signature_matches.recurrence_group_key is not null
              and signature_matches.recurrence_group_key <> ''
        ),
        latest_pattern_rows as (
            select distinct on (
                tenant_row_id,
                tenant_id,
                workspace_row_id,
                workspace_id,
                recurrence_group_key,
                submission_row_id,
                signature_id
            )
                tenant_row_id,
                tenant_id,
                workspace_row_id,
                workspace_id,
                recurrence_group_key,
                submission_row_id,
                signature_id,
                signature_family,
                observed_at,
                trust_band,
                write_order,
                workflow_reference
            from pattern_base
            order by
                tenant_row_id,
                tenant_id,
                workspace_row_id,
                workspace_id,
                recurrence_group_key,
                submission_row_id,
                signature_id,
                observed_at desc,
                write_order desc
        ),
        representative_submission_rows as (
            select distinct on (
                tenant_row_id,
                tenant_id,
                workspace_row_id,
                workspace_id,
                recurrence_group_key,
                submission_row_id
            )
                tenant_row_id,
                tenant_id,
                workspace_row_id,
                workspace_id,
                recurrence_group_key,
                submission_row_id,
                observed_at,
                workflow_reference
            from latest_pattern_rows
            order by
                tenant_row_id,
                tenant_id,
                workspace_row_id,
                workspace_id,
                recurrence_group_key,
                submission_row_id,
                observed_at desc,
                workflow_reference desc nulls last
        ),
        summary_base as (
            select
                tenant_row_id,
                tenant_id,
                workspace_row_id,
                workspace_id,
                recurrence_group_key,
                min(observed_at) as first_seen_at,
                max(observed_at) as last_seen_at,
                count(distinct submission_row_id) as occurrence_count,
                count(distinct case when trust_band = 'trusted' then submission_row_id end) as trusted_occurrence_count
            from latest_pattern_rows
            group by tenant_row_id, tenant_id, workspace_row_id, workspace_id, recurrence_group_key
        ),
        family_counts as (
            select
                tenant_row_id,
                tenant_id,
                workspace_row_id,
                workspace_id,
                recurrence_group_key,
                signature_family,
                count(distinct submission_row_id) as occurrence_count,
                count(distinct signature_id) as signature_count
            from latest_pattern_rows
            group by tenant_row_id, tenant_id, workspace_row_id, workspace_id, recurrence_group_key, signature_family
        ),
        family_rollup as (
            select
                tenant_row_id,
                tenant_id,
                workspace_row_id,
                workspace_id,
                recurrence_group_key,
                jsonb_agg(
                    jsonb_build_object(
                        'signature_family', signature_family,
                        'occurrence_count', occurrence_count,
                        'signature_count', signature_count
                    )
                    order by occurrence_count desc, signature_family
                ) as signature_family_rollup
            from family_counts
            group by tenant_row_id, tenant_id, workspace_row_id, workspace_id, recurrence_group_key
        ),
        workflow_counts as (
            select
                tenant_row_id,
                tenant_id,
                workspace_row_id,
                workspace_id,
                recurrence_group_key,
                coalesce(nullif(trim(workflow_reference), ''), 'unknown') as workflow_reference,
                count(distinct submission_row_id) as occurrence_count
            from representative_submission_rows
            group by tenant_row_id, tenant_id, workspace_row_id, workspace_id, recurrence_group_key, coalesce(nullif(trim(workflow_reference), ''), 'unknown')
        ),
        workflow_rollup as (
            select
                tenant_row_id,
                tenant_id,
                workspace_row_id,
                workspace_id,
                recurrence_group_key,
                jsonb_agg(
                    jsonb_build_object(
                        'workflow_reference', workflow_reference,
                        'occurrence_count', occurrence_count
                    )
                    order by occurrence_count desc, workflow_reference
                ) as workflow_distribution
            from workflow_counts
            group by tenant_row_id, tenant_id, workspace_row_id, workspace_id, recurrence_group_key
        ),
        trend_windows as (
            select
                summary_base.tenant_row_id,
                summary_base.tenant_id,
                summary_base.workspace_row_id,
                summary_base.workspace_id,
                summary_base.recurrence_group_key,
                count(distinct case
                    when representative_submission_rows.observed_at >= summary_base.last_seen_at - interval '7 day'
                     and representative_submission_rows.observed_at <= summary_base.last_seen_at
                    then representative_submission_rows.submission_row_id
                end) as recent_count,
                count(distinct case
                    when representative_submission_rows.observed_at >= summary_base.last_seen_at - interval '14 day'
                     and representative_submission_rows.observed_at < summary_base.last_seen_at - interval '7 day'
                    then representative_submission_rows.submission_row_id
                end) as previous_count
            from summary_base
            inner join representative_submission_rows
              on representative_submission_rows.tenant_row_id = summary_base.tenant_row_id
             and representative_submission_rows.tenant_id = summary_base.tenant_id
             and representative_submission_rows.workspace_row_id is not distinct from summary_base.workspace_row_id
             and representative_submission_rows.workspace_id is not distinct from summary_base.workspace_id
             and representative_submission_rows.recurrence_group_key = summary_base.recurrence_group_key
            group by summary_base.tenant_row_id, summary_base.tenant_id, summary_base.workspace_row_id, summary_base.workspace_id, summary_base.recurrence_group_key
        )
        select
            summary_base.tenant_row_id,
            summary_base.tenant_id,
            summary_base.workspace_row_id,
            summary_base.workspace_id,
            summary_base.recurrence_group_key,
            summary_base.first_seen_at,
            summary_base.last_seen_at,
            summary_base.occurrence_count,
            summary_base.trusted_occurrence_count,
            case
                when trend_windows.previous_count = 0 and trend_windows.recent_count > 0 then 'new'
                when trend_windows.recent_count > trend_windows.previous_count then 'increasing'
                when trend_windows.recent_count < trend_windows.previous_count then 'decreasing'
                else 'stable'
            end as trend_direction,
            coalesce(family_rollup.signature_family_rollup, '[]'::jsonb) as signature_family_rollup,
            coalesce(workflow_rollup.workflow_distribution, '[]'::jsonb) as workflow_distribution
        from summary_base
        inner join trend_windows
          on trend_windows.tenant_row_id = summary_base.tenant_row_id
         and trend_windows.tenant_id = summary_base.tenant_id
         and trend_windows.workspace_row_id is not distinct from summary_base.workspace_row_id
         and trend_windows.workspace_id is not distinct from summary_base.workspace_id
         and trend_windows.recurrence_group_key = summary_base.recurrence_group_key
        left join family_rollup
          on family_rollup.tenant_row_id = summary_base.tenant_row_id
         and family_rollup.tenant_id = summary_base.tenant_id
         and family_rollup.workspace_row_id is not distinct from summary_base.workspace_row_id
         and family_rollup.workspace_id is not distinct from summary_base.workspace_id
         and family_rollup.recurrence_group_key = summary_base.recurrence_group_key
        left join workflow_rollup
          on workflow_rollup.tenant_row_id = summary_base.tenant_row_id
         and workflow_rollup.tenant_id = summary_base.tenant_id
         and workflow_rollup.workspace_row_id is not distinct from summary_base.workspace_row_id
         and workflow_rollup.workspace_id is not distinct from summary_base.workspace_id
         and workflow_rollup.recurrence_group_key = summary_base.recurrence_group_key
        """,
    )


def build_phase3h_team_views_drop_sql() -> tuple[str, ...]:
    return (
        "drop view if exists team_pattern_summary",
        "drop view if exists team_recurrence_summary",
        "drop index if exists ix_submissions_tenant_workspace_workflow_project",
        "drop index if exists ix_trust_evaluations_submission_created_at_write_order",
        "drop index if exists ix_signature_matches_recurrence_group_signature",
    )


def build_phase3h_tenant_oss_seed_sql() -> tuple[str, str]:
    return (
        """
        insert into tenants (
            tenant_id,
            display_name,
            tenancy_state,
            home_region,
            deployment_target,
            metadata
        )
        values (
            'tenant-oss',
            'OSS fallback tenant',
            'active',
            'eu-west-2',
            'aurora-postgresql-serverless-v2',
            jsonb_build_object(
                'seed_source', 'alembic',
                'persona', 'oss'
            )
        )
        on conflict (tenant_id) do nothing
        """,
        "select id from tenants where tenant_id = 'tenant-oss'",
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


def build_phase3h_teams_ab_fixture_seed_sql() -> tuple[str, ...]:
    return (
        # Keep these row UUIDs aligned with the public Teams API fixture contract.
        """
        insert into tenants (
            id,
            tenant_id,
            display_name,
            tenancy_state,
            home_region,
            deployment_target,
            metadata
        )
        values
            (
                '00000000-0000-0000-0000-000000000101',
                'tenant-alpha',
                'Teams Alpha tenant',
                'active',
                'eu-west-2',
                'aurora-postgresql-serverless-v2',
                jsonb_build_object('seed_source', 'alembic', 'persona', 'teams', 'fixture_key', 'tenant-alpha')
            ),
            (
                '00000000-0000-0000-0000-000000000201',
                'tenant-beta',
                'Teams Beta tenant',
                'active',
                'eu-west-2',
                'aurora-postgresql-serverless-v2',
                jsonb_build_object('seed_source', 'alembic', 'persona', 'teams', 'fixture_key', 'tenant-beta')
            )
        on conflict (tenant_id) do nothing
        """,
        """
        insert into workspaces (
            id,
            tenant_id,
            workspace_id,
            display_name,
            project_reference,
            metadata
        )
        values
            (
                '00000000-0000-0000-0000-000000000102',
                '00000000-0000-0000-0000-000000000101',
                'workspace-alpha',
                'Teams Alpha workspace',
                'project-gateway',
                jsonb_build_object('seed_source', 'alembic', 'fixture_key', 'workspace-alpha')
            ),
            (
                '00000000-0000-0000-0000-000000000202',
                '00000000-0000-0000-0000-000000000201',
                'workspace-beta',
                'Teams Beta workspace',
                'project-fulfilment',
                jsonb_build_object('seed_source', 'alembic', 'fixture_key', 'workspace-beta')
            )
        on conflict (tenant_id, workspace_id) do nothing
        """,
        """
        insert into service_identities (
            id,
            tenant_id,
            workspace_id,
            service_identity_id,
            display_name,
            auth_method,
            secret_reference,
            status,
            metadata
        )
        values
            (
                '00000000-0000-0000-0000-000000000103',
                '00000000-0000-0000-0000-000000000101',
                '00000000-0000-0000-0000-000000000102',
                'svc-alpha',
                'Teams Alpha service identity',
                'api_key',
                'phase3h/teams/api-keys/tenant-alpha',
                'active',
                jsonb_build_object('seed_source', 'alembic', 'fixture_key', 'svc-alpha')
            ),
            (
                '00000000-0000-0000-0000-000000000203',
                '00000000-0000-0000-0000-000000000201',
                '00000000-0000-0000-0000-000000000202',
                'svc-beta',
                'Teams Beta service identity',
                'api_key',
                'phase3h/teams/api-keys/tenant-beta',
                'active',
                jsonb_build_object('seed_source', 'alembic', 'fixture_key', 'svc-beta')
            )
        on conflict (tenant_id, service_identity_id) do nothing
        """,
        """
        insert into entitlements (
            id,
            tenant_id,
            workspace_id,
            service_identity_id,
            access_tier,
            subject_scope,
            capabilities,
            metadata,
            effective_from
        )
        values
            (
                '00000000-0000-0000-0000-000000000104',
                '00000000-0000-0000-0000-000000000101',
                '00000000-0000-0000-0000-000000000102',
                '00000000-0000-0000-0000-000000000103',
                'teams',
                'workspace',
                '["teams:read"]'::jsonb,
                jsonb_build_object('seed_source', 'alembic'),
                '2026-05-07T00:00:00+00:00'::timestamptz
            ),
            (
                '00000000-0000-0000-0000-000000000204',
                '00000000-0000-0000-0000-000000000201',
                '00000000-0000-0000-0000-000000000202',
                '00000000-0000-0000-0000-000000000203',
                'teams',
                'workspace',
                '["teams:read"]'::jsonb,
                jsonb_build_object('seed_source', 'alembic'),
                '2026-05-07T00:00:00+00:00'::timestamptz
            )
        on conflict (id) do nothing
        """,
        """
        insert into installations (
            id,
            installation_id,
            client_name,
            platform,
            metadata
        )
        values
            (
                '00000000-0000-0000-0000-000000000151',
                'teams-fixture-installation-alpha',
                'Teams Alpha installation',
                'aws-lambda',
                jsonb_build_object('seed_source', 'alembic', 'tenant_id', 'tenant-alpha')
            ),
            (
                '00000000-0000-0000-0000-000000000251',
                'teams-fixture-installation-beta',
                'Teams Beta installation',
                'aws-lambda',
                jsonb_build_object('seed_source', 'alembic', 'tenant_id', 'tenant-beta')
            )
        on conflict (installation_id) do nothing
        """,
        """
        insert into consent_records (
            id,
            installation_id,
            consent_version,
            consent_granted,
            consent_scope,
            captured_at,
            revoked_at
        )
        values
            (
                '00000000-0000-0000-0000-000000000161',
                '00000000-0000-0000-0000-000000000151',
                'phase3f-consent.v1',
                true,
                jsonb_build_object('persona', 'teams', 'tenant_id', 'tenant-alpha'),
                '2026-05-07T19:55:00+00:00'::timestamptz,
                null
            ),
            (
                '00000000-0000-0000-0000-000000000261',
                '00000000-0000-0000-0000-000000000251',
                'phase3f-consent.v1',
                true,
                jsonb_build_object('persona', 'teams', 'tenant_id', 'tenant-beta'),
                '2026-05-07T19:55:00+00:00'::timestamptz,
                null
            )
        on conflict (id) do nothing
        """,
        """
        insert into submissions (
            id,
            installation_id,
            consent_record_id,
            submission_id,
            source_system,
            source_session_id,
            source_report_id,
            envelope_contract_version,
            envelope,
            envelope_checksum,
            state,
            received_at,
            processed_at,
            tenant_id,
            workspace_id,
            service_identity_id,
            workflow_reference,
            project_reference,
            evidence_artifact_prefix
        )
        values
            ('00000000-0000-0000-0000-000000000111', '00000000-0000-0000-0000-000000000151', '00000000-0000-0000-0000-000000000161', 'sub-alpha-1', 'teams-e2e', 'teams-alpha-session', 'teams-alpha-report-1', 'phase3h-envelope.v1', jsonb_build_object('environment', 'prod'), 'sha256:sub-alpha-1', 'processed', '2026-05-07T20:00:00+00:00'::timestamptz, '2026-05-07T20:00:00+00:00'::timestamptz, '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000102', '00000000-0000-0000-0000-000000000103', 'workflow-build', 'project-gateway', 's3://driftshield-phase3h/teams/sub-alpha-1/'),
            ('00000000-0000-0000-0000-000000000112', '00000000-0000-0000-0000-000000000151', '00000000-0000-0000-0000-000000000161', 'sub-alpha-2', 'teams-e2e', 'teams-alpha-session', 'teams-alpha-report-2', 'phase3h-envelope.v1', jsonb_build_object('environment', 'prod'), 'sha256:sub-alpha-2', 'processed', '2026-05-07T20:05:00+00:00'::timestamptz, '2026-05-07T20:05:00+00:00'::timestamptz, '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000102', '00000000-0000-0000-0000-000000000103', 'workflow-build', 'project-gateway', 's3://driftshield-phase3h/teams/sub-alpha-2/'),
            ('00000000-0000-0000-0000-000000000113', '00000000-0000-0000-0000-000000000151', '00000000-0000-0000-0000-000000000161', 'sub-alpha-3', 'teams-e2e', 'teams-alpha-session', 'teams-alpha-report-3', 'phase3h-envelope.v1', jsonb_build_object('environment', 'staging'), 'sha256:sub-alpha-3', 'processed', '2026-05-07T20:10:00+00:00'::timestamptz, '2026-05-07T20:10:00+00:00'::timestamptz, '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000102', '00000000-0000-0000-0000-000000000103', 'workflow-review', 'project-gateway', 's3://driftshield-phase3h/teams/sub-alpha-3/'),
            ('00000000-0000-0000-0000-000000000114', '00000000-0000-0000-0000-000000000151', '00000000-0000-0000-0000-000000000161', 'sub-alpha-4', 'teams-e2e', 'teams-alpha-session', 'teams-alpha-report-4', 'phase3h-envelope.v1', jsonb_build_object('environment', 'prod'), 'sha256:sub-alpha-4', 'processed', '2026-05-07T20:15:00+00:00'::timestamptz, '2026-05-07T20:15:00+00:00'::timestamptz, '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000102', '00000000-0000-0000-0000-000000000103', 'workflow-corrected', 'project-gateway', 's3://driftshield-phase3h/teams/sub-alpha-4/'),
            ('00000000-0000-0000-0000-000000000211', '00000000-0000-0000-0000-000000000251', '00000000-0000-0000-0000-000000000261', 'sub-beta-1', 'teams-e2e', 'teams-beta-session', 'teams-beta-report-1', 'phase3h-envelope.v1', jsonb_build_object('environment', 'prod'), 'sha256:sub-beta-1', 'processed', '2026-05-07T20:03:00+00:00'::timestamptz, '2026-05-07T20:03:00+00:00'::timestamptz, '00000000-0000-0000-0000-000000000201', '00000000-0000-0000-0000-000000000202', '00000000-0000-0000-0000-000000000203', 'workflow-build', 'project-fulfilment', 's3://driftshield-phase3h/teams/sub-beta-1/')
        on conflict (submission_id) do nothing
        """,
        """
        insert into trust_evaluations (
            id,
            submission_id,
            trust_band,
            confidence_band,
            final_learning_weight,
            learning_eligible,
            requires_review,
            provenance,
            evaluation_metadata,
            created_at
        )
        values
            ('00000000-0000-0000-0000-000000000121', '00000000-0000-0000-0000-000000000111', 'trusted', 'high', 1.0, true, false, jsonb_build_object('seed_source', 'alembic'), jsonb_build_object('fixture_key', 'sub-alpha-1'), '2026-05-07T20:00:00+00:00'::timestamptz),
            ('00000000-0000-0000-0000-000000000122', '00000000-0000-0000-0000-000000000112', 'provisional', 'high', 0.5, true, false, jsonb_build_object('seed_source', 'alembic'), jsonb_build_object('fixture_key', 'sub-alpha-2'), '2026-05-07T20:05:00+00:00'::timestamptz),
            ('00000000-0000-0000-0000-000000000123', '00000000-0000-0000-0000-000000000113', 'trusted', 'high', 1.0, true, false, jsonb_build_object('seed_source', 'alembic'), jsonb_build_object('fixture_key', 'sub-alpha-3'), '2026-05-07T20:10:00+00:00'::timestamptz),
            ('00000000-0000-0000-0000-000000000124', '00000000-0000-0000-0000-000000000114', 'trusted', 'high', 1.0, true, false, jsonb_build_object('seed_source', 'alembic'), jsonb_build_object('fixture_key', 'sub-alpha-4'), '2026-05-07T20:15:00+00:00'::timestamptz),
            ('00000000-0000-0000-0000-000000000125', '00000000-0000-0000-0000-000000000114', 'quarantined', 'high', 0.0, false, true, jsonb_build_object('seed_source', 'alembic'), jsonb_build_object('fixture_key', 'sub-alpha-4-corrected'), '2026-05-07T20:20:00+00:00'::timestamptz),
            ('00000000-0000-0000-0000-000000000221', '00000000-0000-0000-0000-000000000211', 'trusted', 'high', 1.0, true, false, jsonb_build_object('seed_source', 'alembic'), jsonb_build_object('fixture_key', 'sub-beta-1'), '2026-05-07T20:03:00+00:00'::timestamptz)
        on conflict (id) do nothing
        """,
        """
        insert into signature_matches (
            id,
            submission_id,
            signature_id,
            signature_version,
            match_status,
            confidence,
            mechanism_id,
            evidence,
            confidence_breakdown,
            review_needed,
            visibility_class,
            recurrence_group_key,
            created_at
        )
        values
            ('00000000-0000-0000-0000-000000000131', '00000000-0000-0000-0000-000000000111', 'sig.retry-loop', 'v1', 'matched', 0.98, 'phase3h-seed', '{}'::jsonb, '{}'::jsonb, false, 'internal_only', 'grp:retry-loop', '2026-05-07T20:00:00+00:00'::timestamptz),
            ('00000000-0000-0000-0000-000000000132', '00000000-0000-0000-0000-000000000112', 'sig.retry-loop', 'v1', 'matched', 0.91, 'phase3h-seed', '{}'::jsonb, '{}'::jsonb, false, 'internal_only', 'grp:retry-loop', '2026-05-07T20:05:00+00:00'::timestamptz),
            ('00000000-0000-0000-0000-000000000133', '00000000-0000-0000-0000-000000000113', 'sig.timeout', 'v1', 'matched', 0.96, 'phase3h-seed', '{}'::jsonb, '{}'::jsonb, false, 'internal_only', 'grp:timeout', '2026-05-07T20:10:00+00:00'::timestamptz),
            ('00000000-0000-0000-0000-000000000134', '00000000-0000-0000-0000-000000000114', 'sig.corrected', 'v1', 'matched', 0.95, 'phase3h-seed', '{}'::jsonb, '{}'::jsonb, false, 'internal_only', 'grp:corrected', '2026-05-07T20:15:00+00:00'::timestamptz),
            ('00000000-0000-0000-0000-000000000231', '00000000-0000-0000-0000-000000000211', 'sig.retry-loop', 'v1', 'matched', 0.97, 'phase3h-seed', '{}'::jsonb, '{}'::jsonb, false, 'internal_only', 'grp:retry-loop', '2026-05-07T20:03:00+00:00'::timestamptz)
        on conflict (id) do nothing
        """,
        """
        select
            (select id from tenants where tenant_id = 'tenant-alpha') as tenant_alpha_row_id,
            (select id from workspaces where workspace_id = 'workspace-alpha' and tenant_id = '00000000-0000-0000-0000-000000000101'::uuid) as workspace_alpha_row_id,
            (select id from service_identities where service_identity_id = 'svc-alpha' and tenant_id = '00000000-0000-0000-0000-000000000101'::uuid) as service_identity_alpha_row_id,
            (select id from tenants where tenant_id = 'tenant-beta') as tenant_beta_row_id,
            (select id from workspaces where workspace_id = 'workspace-beta' and tenant_id = '00000000-0000-0000-0000-000000000201'::uuid) as workspace_beta_row_id,
            (select id from service_identities where service_identity_id = 'svc-beta' and tenant_id = '00000000-0000-0000-0000-000000000201'::uuid) as service_identity_beta_row_id,
            (select count(*) from team_recurrence_summary where tenant_id = 'tenant-alpha') as tenant_alpha_recurrence_summary_rows,
            (select count(*) from team_recurrence_summary where tenant_id = 'tenant-beta') as tenant_beta_recurrence_summary_rows,
            (select count(*) from team_pattern_summary where tenant_id = 'tenant-alpha') as tenant_alpha_pattern_summary_rows,
            (select count(*) from team_pattern_summary where tenant_id = 'tenant-beta') as tenant_beta_pattern_summary_rows
        """,
    )
