import { test, expect, type Page } from '@playwright/test'

const sessionId = '11111111-1111-1111-1111-111111111111'

function buildGraphNode(overrides: Record<string, unknown> = {}) {
  return {
    id: '22222222-2222-2222-2222-222222222222',
    node_kind: null,
    event_type: 'TOOL_CALL',
    action: 'review_sections',
    summary: null,
    confidence: null,
    sequence_num: 1,
    risk_flags: [],
    risk_explanations: {},
    evidence_refs: [],
    is_inflection: false,
    inflection_explanation: null,
    inputs: null,
    outputs: null,
    metadata: null,
    parent_node_id: null,
    parent_node_ids: [],
    lineage_ambiguities: [],
    ...overrides,
  }
}

async function mockSessionArtifacts(page: Page) {
  await page.route(`**/api/sessions/${sessionId}/reports`, async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify([]),
    })
  })

  await page.route(`**/api/sessions/${sessionId}/validations`, async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify([]),
    })
  })
}

test('shows matched OSS signature recognition states from backend metadata', async ({ page }) => {
  await page.route(`**/api/sessions/${sessionId}`, async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        id: sessionId,
        agent_id: 'claude-code',
        external_id: null,
        status: 'completed',
        started_at: '2026-04-21T10:00:00Z',
        ended_at: '2026-04-21T10:05:00Z',
        risk_flag_count: 2,
        has_inflection: true,
        provenance: {
          source_session_id: 'src-1',
          source_path: 'uploads/test.jsonl',
          parser_version: 'claude_code@1',
          ingested_at: '2026-04-21T10:06:00Z',
        },
        total_events: 4,
        flagged_events: 2,
        risk_summary: { coverage_gap: 2 },
        explanations: { risk_explanations: {}, inflection_explanation: null },
        signature_match: {
          status: 'matched',
          primary_mechanism_id: 'coverage_gap',
          matched_mechanism_ids: ['coverage_gap', 'verification_failure'],
          match_count: 2,
          summary: 'Matched two known failure mechanisms from local OSS-safe signals.',
          raw: null,
        },
      }),
    })
  })

  await page.route(`**/api/sessions/${sessionId}/graph`, async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        session_id: sessionId,
        provenance: null,
        nodes: [
          buildGraphNode({
            risk_flags: ['coverage_gap'],
            is_inflection: true,
          }),
        ],
        edges: [],
      }),
    })
  })

  await mockSessionArtifacts(page)

  await page.goto(`/sessions/${sessionId}`)

  await expect(page.getByText('Recognition: matched')).toBeVisible()
  await expect(page.getByText('Matched two known failure mechanisms from local OSS-safe signals.')).toBeVisible()
  await expect(page.getByText('Primary mechanism:')).toBeVisible()
  await expect(page.getByText('Matched mechanisms')).toBeVisible()
  await expect(page.getByText('Recurrence: recurring')).not.toBeVisible()
})

test('shows unavailable state when backend omits OSS signature recognition fields', async ({ page }) => {
  await page.route(`**/api/sessions/${sessionId}`, async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        id: sessionId,
        agent_id: 'claude-code',
        external_id: null,
        status: 'completed',
        started_at: '2026-04-21T10:00:00Z',
        ended_at: '2026-04-21T10:05:00Z',
        risk_flag_count: 0,
        has_inflection: false,
        provenance: null,
        total_events: 1,
        flagged_events: 0,
        risk_summary: {},
      }),
    })
  })

  await page.route(`**/api/sessions/${sessionId}/graph`, async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        session_id: sessionId,
        provenance: null,
        nodes: [
          buildGraphNode({
            event_type: 'OUTPUT',
            action: 'respond',
          }),
        ],
        edges: [],
      }),
    })
  })

  await mockSessionArtifacts(page)

  await page.goto(`/sessions/${sessionId}`)

  await expect(page.getByText('This session does not expose OSS signature recognition data yet.')).toBeVisible()
})

test('keeps the investigation view alive when graph payload omits lineage fields', async ({ page }) => {
  await page.route(`**/api/sessions/${sessionId}`, async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        id: sessionId,
        agent_id: 'claude-code',
        external_id: null,
        status: 'completed',
        started_at: '2026-04-21T10:00:00Z',
        ended_at: '2026-04-21T10:05:00Z',
        risk_flag_count: 2,
        has_inflection: true,
        provenance: null,
        total_events: 4,
        flagged_events: 2,
        risk_summary: { coverage_gap: 2 },
        explanations: { risk_explanations: {}, inflection_explanation: null },
        signature_match: {
          status: 'matched',
          primary_mechanism_id: 'coverage_gap',
          matched_mechanism_ids: ['coverage_gap'],
          match_count: 1,
          summary: 'Matched one known failure mechanism from local OSS-safe signals.',
          raw: null,
        },
      }),
    })
  })

  await page.route(`**/api/sessions/${sessionId}/graph`, async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        session_id: sessionId,
        provenance: null,
        nodes: [
          {
            id: '22222222-2222-2222-2222-222222222222',
            event_type: 'TOOL_CALL',
            action: 'review_sections',
            sequence_num: 1,
            risk_flags: ['coverage_gap'],
            risk_explanations: {},
            is_inflection: true,
            inflection_explanation: null,
            inputs: null,
            outputs: null,
            metadata: null,
            parent_node_id: null,
          },
        ],
        edges: [],
      }),
    })
  })

  await mockSessionArtifacts(page)

  await page.goto(`/sessions/${sessionId}`)

  await expect(page.getByText('Recognition: matched')).toBeVisible()
  await expect(page.getByText('Investigation graph')).toBeVisible()
  await expect(page.getByText('Root node')).toBeVisible()
})

test('shows node evidence refs even when no explanations were returned', async ({ page }) => {
  await page.route(`**/api/sessions/${sessionId}`, async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        id: sessionId,
        agent_id: 'claude-code',
        external_id: null,
        status: 'completed',
        started_at: '2026-04-21T10:00:00Z',
        ended_at: '2026-04-21T10:05:00Z',
        risk_flag_count: 0,
        has_inflection: false,
        provenance: null,
        total_events: 1,
        flagged_events: 0,
        risk_summary: {},
      }),
    })
  })

  await page.route(`**/api/sessions/${sessionId}/graph`, async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        session_id: sessionId,
        provenance: null,
        nodes: [
          buildGraphNode({
            event_type: 'OUTPUT',
            action: 'respond',
            evidence_refs: ['event:22222222-2222-2222-2222-222222222222', 'artifact_refs[0]'],
          }),
        ],
        edges: [],
      }),
    })
  })

  await mockSessionArtifacts(page)

  await page.goto(`/sessions/${sessionId}`)
  await page.getByRole('button', { name: /respond/i }).click()
  await page.getByRole('tab', { name: 'Evidence' }).click()

  await expect(page.getByText('Node evidence')).toBeVisible()
  await expect(page.getByText('event:22222222-2222-2222-2222-222222222222')).toBeVisible()
  await expect(page.getByText('artifact_refs[0]')).toBeVisible()
  await expect(page.getByText('No evidence refs were returned for this node.')).not.toBeVisible()
})

test('uses parent_node_ids fallback for single-parent timeline labels', async ({ page }) => {
  await page.route(`**/api/sessions/${sessionId}`, async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        id: sessionId,
        agent_id: 'claude-code',
        external_id: null,
        status: 'completed',
        started_at: '2026-04-21T10:00:00Z',
        ended_at: '2026-04-21T10:05:00Z',
        risk_flag_count: 0,
        has_inflection: false,
        provenance: null,
        total_events: 2,
        flagged_events: 0,
        risk_summary: {},
      }),
    })
  })

  await page.route(`**/api/sessions/${sessionId}/graph`, async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        session_id: sessionId,
        provenance: null,
        nodes: [
          buildGraphNode({
            id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            action: 'root',
            sequence_num: 0,
          }),
          buildGraphNode({
            id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
            action: 'child',
            sequence_num: 1,
            parent_node_id: null,
            parent_node_ids: ['aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'],
          }),
        ],
        edges: [
          {
            source: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            target: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
            relationship: 'explicit_parent',
            confidence: 1,
            inferred: false,
            reason: null,
            evidence_refs: [],
          },
        ],
      }),
    })
  })

  await mockSessionArtifacts(page)

  await page.goto(`/sessions/${sessionId}`)

  await expect(page.getByText('Parent aaaaaaaa…')).toBeVisible()
  await expect(page.getByText('Parent undefined…')).not.toBeVisible()
})
