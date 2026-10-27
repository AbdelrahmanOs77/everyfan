import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test('demo, four perspectives, evidence, Arabic, verifier, recap and feed', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const kinds = new Set<string>();
  let sockets = 0;
  page.on('websocket', (ws) => {
    if (!ws.url().includes('/ws/demo/')) return;
    sockets++;
    ws.on('framereceived', (frame) => {
      try {
        kinds.add(JSON.parse(String(frame.payload)).type);
      } catch {
        /* Non-JSON frames are not match data. */
      }
    });
  });
  await page.goto('/');
  await expect(page.locator('.match-context-name')).toContainText('Nile FC');
  await page.getByRole('button', { name: 'Watch demo match', exact: true }).first().click();
  await expect(page.locator('.pitch-player')).toHaveCount(22);
  await page.locator('.highlight-list button').first().click();
  await expect(page.getByRole('button', { name: 'Play', exact: true })).toBeVisible({
    timeout: 20000,
  });
  await page.getByRole('button', { name: 'Perspectives', exact: true }).click();
  await expect(page.locator('.comparison-pane')).toHaveCount(4);
  await expect(page.locator('.comparison-pane .overlay-card')).toHaveCount(4);
  await page
    .locator('.comparison-pane')
    .first()
    .getByRole('button', { name: /Inspect/ })
    .first()
    .click();
  await expect(page.getByRole('dialog')).toContainText('All evidence events resolved');
  await expect(page.locator('.facts-grid dd').first()).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('combobox', { name: 'Commentary language', exact: true }).selectOption('ar');
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
  await expect(page.locator('.match-context-name')).toContainText('نادي النيل');
  await page.getByRole('combobox', { name: 'لغة التعليق', exact: true }).selectOption('en');
  expect(sockets).toBe(1);
  await page.getByRole('button', { name: 'Match', exact: true }).click();
  await page.getByRole('button', { name: /^Favorite club/ }).click();
  await page
    .getByRole('combobox', { name: 'Support a club', exact: true })
    .selectOption('delta_utd');
  await expect(page.locator('.commentary .overlay-card')).toHaveCount(1);
  await page.getByRole('button', { name: 'Judge Lab', exact: true }).click();
  await page.getByRole('button', { name: /^Break it/ }).click();
  await expect(page.locator('.rejected-panel')).toContainText('999999');
  await expect(page.locator('.approved-panel')).not.toContainText('999999');
  await page.getByRole('button', { name: 'Match', exact: true }).click();
  await page.getByRole('button', { name: 'Match story', exact: true }).first().click();
  await expect(page.locator('.recap-body')).not.toBeEmpty();
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: 'Overlay feed', exact: true }).click();
  await expect(page.locator('.feed-grid .overlay-card').first()).toBeVisible();
  expect(errors).toEqual([]);
  expect([...kinds]).toEqual(expect.arrayContaining(['tracking', 'state', 'overlay', 'reset']));
  await page.reload();
  await page.getByRole('button', { name: 'Match', exact: true }).click();
  await expect(page.getByRole('combobox', { name: 'Support a club', exact: true })).toHaveValue(
    'delta_utd',
  );
  await expect(page.getByRole('button', { name: /^Favorite club/ })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
});

test('responsive layout, accessible landing and keyboard controls', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('.match-context-name')).toContainText('Nile FC');
  const audit = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
    .analyze();
  expect(audit.violations).toEqual([]);
  for (const width of [1440, 768, 375, 320]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  }
  await page.getByRole('combobox', { name: 'Commentary language', exact: true }).selectOption('ar');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.setViewportSize({ width: 375, height: 812 });
  await page.screenshot({ path: 'test-results/phone-arabic.png', fullPage: true });
  await page.getByRole('combobox', { name: 'لغة التعليق', exact: true }).selectOption('en');
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.screenshot({ path: 'test-results/desktop.png', fullPage: true });
  await page.getByRole('button', { name: 'Watch demo match', exact: true }).first().click();
  await expect(page.locator('.pitch-player')).toHaveCount(22);
  await page.locator('body').click({ position: { x: 3, y: 150 } });
  await page.keyboard.press('Space');
  await expect(page.getByRole('button', { name: 'Play', exact: true })).toBeVisible();
  await page.keyboard.press('Space');
  await expect(page.getByRole('button', { name: 'Pause', exact: true })).toBeVisible();
  await page.locator('.highlight-list button').first().click();
  await expect(page.getByRole('button', { name: 'Play', exact: true })).toBeVisible();
  const activeAudit = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
    .analyze();
  expect(activeAudit.violations).toEqual([]);
  await page.locator('h1').focus();
  await page.screenshot({ path: 'test-results/desktop-playing.png', fullPage: true });
});

test('failed bootstrap shows a retry that recovers', async ({ page }) => {
  await page.route('**/api/health', (route) => route.abort());
  await page.goto('/');
  await expect(page.getByRole('alert')).toBeVisible();
  await page.unroute('**/api/health');
  await page.getByRole('button', { name: 'Retry connection', exact: true }).click();
  await expect(page.locator('.match-context-name')).toContainText('Nile FC');
  await expect(page.getByRole('alert')).toHaveCount(0);
});

test('one full replay stays faithful to state, expires cards and resets cleanly', async ({
  page,
}) => {
  test.setTimeout(125000);
  let latestState: { score: Record<string, number> } | null = null;
  let latestClock = 0;
  const seen = new Set<string>();
  page.on('websocket', (ws) =>
    ws.on('framereceived', (frame) => {
      const message = JSON.parse(String(frame.payload));
      if (message.type === 'state') latestState = message.data;
      if (message.type === 'tracking' || message.type === 'state')
        latestClock = message.game_time_s;
      if (message.type === 'overlay') seen.add(message.data.overlay_id);
    }),
  );
  await page.goto('/');
  await page.getByRole('button', { name: 'Watch demo match', exact: true }).first().click();
  await expect(page.locator('.pitch-player')).toHaveCount(22);
  await page.getByRole('checkbox', { name: 'Pause at goals', exact: true }).uncheck();
  await page.getByRole('combobox', { name: 'Replay speed', exact: true }).selectOption('60');
  await expect(page.locator('.stage-mode')).toContainText('FULL TIME', { timeout: 110000 });
  expect(latestState).not.toBeNull();
  await expect(page.getByTestId('score-home')).toHaveText(String(latestState!.score.nile_fc));
  await expect(page.getByTestId('score-away')).toHaveText(String(latestState!.score.delta_utd));
  expect(latestClock).toBeGreaterThanOrEqual(5399);
  expect(seen.size).toBeGreaterThan(100);
  await expect(page.locator('.commentary .overlay-card')).toHaveCount(0);
  await page.getByRole('button', { name: 'Match story', exact: true }).first().click();
  await expect(page.getByRole('dialog')).toContainText('Full time');
  await page.keyboard.press('Escape');
  await page.locator('.highlight-list button').first().click();
  await expect(page.getByTestId('score-away')).toHaveText('0');
  await expect(page.getByTestId('viewer-clock')).not.toHaveText('90:00');
});

test('live host controls stay private and a second viewer joins read-only', async ({ browser }) => {
  const host = await browser.newContext();
  const viewer = await browser.newContext();
  const hostPage = await host.newPage();
  const viewerPage = await viewer.newPage();
  await hostPage.goto('http://localhost:5175');
  await hostPage.getByRole('button', { name: 'Judge Lab', exact: true }).click();
  await hostPage.getByRole('button', { name: /^Run live/ }).click();
  await expect(hostPage.locator('.pitch-player')).toHaveCount(22, { timeout: 15000 });
  await viewerPage.goto('http://localhost:5175');
  await viewerPage.getByRole('button', { name: 'Judge Lab', exact: true }).click();
  await viewerPage.getByRole('button', { name: /^Run live/ }).click();
  await expect(viewerPage.locator('.notice-banner')).toContainText('Its host controls playback');
  await expect(viewerPage.getByRole('button', { name: 'Pause', exact: true })).toBeDisabled();
  expect(await hostPage.evaluate(() => Object.values(localStorage).join(' '))).not.toContain(
    'control_token',
  );
  await hostPage.getByRole('button', { name: 'Pause', exact: true }).click();
  await expect(hostPage.getByRole('button', { name: 'Play', exact: true })).toBeVisible();
  await hostPage.getByRole('button', { name: 'Stop live broadcast', exact: true }).click();
  await host.close();
  await viewer.close();
});
