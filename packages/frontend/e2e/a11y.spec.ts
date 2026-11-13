import { test, expect, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag22aa'];

async function assertNoA11yViolations(page: Page, name: string) {
  const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();

  const violations = results.violations.map((v) => ({
    id: v.id,
    impact: v.impact,
    description: v.description,
    nodes: v.nodes.length,
    help: v.helpUrl,
  }));

  expect(violations, `${name}: accessibility violations found`).toEqual([]);
}

// ---------------------------------------------------------------------------
// Public pages — no auth required
// ---------------------------------------------------------------------------

test.describe('Public pages', () => {
  test('/ (landing)', async ({ page }) => {
    await page.goto('/');
    await assertNoA11yViolations(page, 'Landing');
  });

  test('/login', async ({ page }) => {
    await page.goto('/login');
    await assertNoA11yViolations(page, 'Login');
  });

  test('/signup', async ({ page }) => {
    await page.goto('/signup');
    await assertNoA11yViolations(page, 'Sign up');
  });

  test('/forgot-password', async ({ page }) => {
    await page.goto('/forgot-password');
    await assertNoA11yViolations(page, 'Forgot password');
  });
});

// ---------------------------------------------------------------------------
// Authenticated pages — require a session cookie.
//
// The backend must be running with a test user. Set E2E_SESSION_COOKIE in the
// environment (value: the full `sessionid=<value>` cookie string).
// When absent the tests are skipped so the CI gate doesn't break before a
// test backend is available.
// ---------------------------------------------------------------------------

const sessionCookie = process.env.E2E_SESSION_COOKIE;

test.describe('Dashboard pages', () => {
  test.skip(!sessionCookie, 'E2E_SESSION_COOKIE not set — skipping authenticated pages');

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

  const dashboardPages: [string, string][] = [
    ['/dashboard', 'Dashboard'],
    ['/agents', 'Agents list'],
    ['/agents/new', 'New agent'],
    ['/tools', 'Tools'],
    ['/knowledge', 'Knowledge'],
    ['/schedules', 'Schedules'],
    ['/policies', 'Policies'],
    ['/end-users', 'End users'],
    ['/insights', 'Insights'],
    ['/runs', 'Runs'],
    ['/settings', 'Settings'],
    ['/keys', 'API keys'],
    ['/billing', 'Billing'],
    ['/workspace/members', 'Members'],
  ];

  for (const [path, name] of dashboardPages) {
    test(`${path} (${name})`, async ({ page }) => {
      const response = await page.goto(path);
      expect(response?.status(), `${name}: expected 200, got ${response?.status()}`).toBe(200);
      await assertNoA11yViolations(page, name);
    });
  }
});
