import { test, expect } from '@playwright/test'

const sessionId = '11111111-1111-1111-1111-111111111111'

test('shows matched signature and recurrence states from backend metadata', async ({ page }) => {
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
          primary_family_id: 'coverage_gap',
          matched_family_ids: ['coverage_gap', 'verification_failure'],
          match_count: 2,
          summary: 'Matched two known failure families.',
          raw: null,
        },
        recurrence_status: {
          status: 'recurring',
          cluster_id: 'cluster-42',
          recurrence_count: 3,
          summary: 'Seen in three related runs.',
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

  await page.route(`**/api/sessions/${sessionId}/reports`, async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify([]),
    })
  })

  await page.goto(`/sessions/${sessionId}`)

  await expect(page.getByText('Signature: matched')).toBeVisible()
  await expect(page.getByText('Recurrence: recurring')).toBeVisible()
  await expect(page.getByText('Matched two known failure families.')).toBeVisible()
  await expect(page.getByText('Seen in three related runs.')).toBeVisible()
  await expect(page.getByText('Primary family:')).toBeVisible()
  await expect(page.getByText('Cluster:')).toBeVisible()
})

test('shows unavailable state when backend omits signature and recurrence fields', async ({ page }) => {
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
          {
            id: '22222222-2222-2222-2222-222222222222',
            event_type: 'OUTPUT',
            action: 'respond',
            sequence_num: 1,
            risk_flags: [],
            risk_explanations: {},
            is_inflection: false,
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

  await page.route(`**/api/sessions/${sessionId}/reports`, async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify([]),
    })
  })

  await page.goto(`/sessions/${sessionId}`)

  await expect(page.getByText('This session does not expose signature or recurrence data yet.')).toBeVisible()
})
