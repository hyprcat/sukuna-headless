import { test, expect } from '@playwright/test';

// ---------------------------------------------------------------------------
// Run detail timeline smoke test.
//
// Exercises `/runs/[id]` against a run seeded with RunEvent rows. Like the
// authenticated a11y suite, it needs a live test backend: provide the session
// cookie (E2E_SESSION_COOKIE) and a seeded run UID (E2E_RUN_UID). When either
// is absent the suite skips so the CI gate stays green before a test backend
// is wired up.
//
// Optionally set E2E_RUN_EVENT_LABELS to a comma-separated list of the event
// labels expected, in order, to assert exact projection + ordering (e.g.
// "Run started,Tool call: search,Tool result: search,Usage checkpoint,Run completed").
// ---------------------------------------------------------------------------

const sessionCookie = process.env.E2E_SESSION_COOKIE;
const runUid = process.env.E2E_RUN_UID;
const expectedLabels = (process.env.E2E_RUN_EVENT_LABELS ?? '')
  .split(',')
  .map((s) => s.trim())
  .filter(Boolean);

test.describe('Run detail timeline', () => {
  test.skip(
    !sessionCookie || !runUid,
    'E2E_SESSION_COOKIE / E2E_RUN_UID not set — skipping run detail test',
  );

  test.beforeEach(async ({ context }) => {
    const baseURL = process.env.E2E_BASE_URL || 'http://localhost:4321';
    const url = new URL(baseURL);
    await context.addCookies([
      {
        name: 'sessionid',
        value: sessionCookie!.replace(/^sessionid=/, ''),
        domain: url.hostname,
        path: '/',
      },
    ]);
  });

  test('renders the event timeline in sequence order', async ({ page }) => {
    const response = await page.goto(`/runs/${runUid}`);
    expect(response?.status(), 'expected run detail page to load').toBe(200);

    const timeline = page.locator('[data-run-timeline]');
    await expect(timeline).toBeVisible();

    const events = timeline.locator('.timeline-event');
    const count = await events.count();
    expect(count, 'expected at least one seeded RunEvent').toBeGreaterThan(0);

    // Every event must render a non-empty label and a category dot.
    for (let i = 0; i < count; i++) {
      const event = events.nth(i);
      await expect(event.locator('.timeline-label')).not.toBeEmpty();
      await expect(event.locator('.timeline-dot')).toHaveCount(1);
    }

    // Exact projection + ordering when the expected labels are provided.
    if (expectedLabels.length > 0) {
      const rendered = await events.locator('.timeline-label').allInnerTexts();
      expect(rendered.map((s) => s.trim())).toEqual(expectedLabels);
    }
  });
});
