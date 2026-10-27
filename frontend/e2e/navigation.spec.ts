import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test('each fan has a different interface with server-measured stats and one replay', async ({
  page,
}) => {
  let sockets = 0;
  page.on('websocket', (ws) => {
    if (ws.url().includes('/ws/demo/')) sockets++;
  });
  await page.goto('/#/beginner');
  await page.getByRole('button', { name: 'Watch demo match', exact: true }).click();
  await expect(page.locator('.pitch-player')).toHaveCount(22);
  await page.locator('.highlight-list button').first().click();
  await expect(page.getByRole('button', { name: 'Play', exact: true })).toBeVisible();
  const clock = await page.getByTestId('viewer-clock').textContent();
  await expect(page.locator('.beginner-stats')).toBeVisible();
  await expect(page.locator('.tactical-dashboard,.player-dashboard')).toHaveCount(0);
  const analysis = page.waitForResponse(
    (r) => r.url().includes('/advanced-stats?') && r.url().includes('window_s=300'),
  );
  await page.getByRole('button', { name: 'Tactical', exact: true }).click();
  const data = await (await analysis).json();
  const ppda = data.teams.nile_fc.current.ppda;
  await expect(page.locator('[data-metric="ppda-current"]')).toHaveText(
    ppda == null ? '—' : ppda.toLocaleString('en-US', { maximumFractionDigits: 1 }),
  );
  await expect(page.locator('h1')).toBeFocused();
  await expect(page.locator('.beginner-stats,.player-dashboard,.learn-panel')).toHaveCount(0);
  await expect(page.getByTestId('viewer-clock')).toHaveText(clock!);
  await page.screenshot({ path: 'test-results/fan-tactical.png', fullPage: true });
  const changed = page.waitForResponse(
    (r) => r.url().includes('/advanced-stats?') && r.url().includes('window_s=60'),
  );
  await page.getByRole('combobox', { name: 'Analysis window', exact: true }).selectOption('60');
  expect((await (await changed).json()).window_s).toBe(60);
  await page.getByRole('button', { name: 'Passing & territory', exact: true }).click();
  await expect(page.locator('.territory-grid')).toBeVisible();
  await page.screenshot({ path: 'test-results/fan-tactical-passing.png', fullPage: true });
  await page.getByRole('button', { name: 'Shots & actions', exact: true }).click();
  await expect(page.locator('.shot-evidence')).toBeVisible();
  await page.getByRole('button', { name: 'Player', exact: true }).click();
  await expect(page.locator('.player-dashboard')).toBeVisible();
  await expect(page.locator('.tactical-dashboard,.beginner-stats')).toHaveCount(0);
  await page.getByRole('combobox', { name: 'Follow a player', exact: true }).selectOption('nil_10');
  await expect(page.locator('.player-profile h2')).toHaveText('Hassan Nour');
  await expect(page.locator('.player-ticker h3')).toHaveText('Hassan Nour');
  await page.screenshot({ path: 'test-results/fan-player.png', fullPage: true });
  await page.goBack();
  await expect(page).toHaveURL(/#\/tactical$/);
  await page.goForward();
  await expect(page).toHaveURL(/#\/player$/);
  await page.getByRole('button', { name: 'My club', exact: true }).click();
  await page
    .getByRole('combobox', { name: 'Support a club', exact: true })
    .selectOption('delta_utd');
  await expect(page.locator('.club-dashboard h2')).toHaveText('Delta United');
  await page.getByRole('button', { name: 'Beginner', exact: true }).click();
  await expect(page.getByTestId('viewer-clock')).toHaveText(clock!);
  expect(sockets).toBe(1);
  await page.getByRole('button', { name: 'Judge Lab', exact: true }).click();
  await expect(page.locator('.pitch,.tactical-dashboard,.player-dashboard')).toHaveCount(0);
  await page.getByRole('button', { name: 'Overlay feed', exact: true }).click();
  await expect(page.locator('.feed-grid .overlay-card').first()).toBeVisible();
  await page
    .getByRole('combobox', { name: 'Filter by perspective', exact: true })
    .selectOption('tactical');
  await expect(page.locator('.feed-label span').first()).toHaveText('Tactical analyst');
  await page
    .getByRole('searchbox', { name: 'Search commentary', exact: true })
    .fill('no matching fictional commentary');
  await expect(page.locator('.feed-grid .overlay-card')).toHaveCount(0);
  await page.goto('/#/tactical');
  await expect(page.getByRole('button', { name: 'Tactical', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  );
});

test('all fan interfaces are accessible and responsive in English and Arabic', async ({ page }) => {
  test.setTimeout(90000);
  await page.goto('/#/beginner');
  await expect(page.locator('.match-context-name')).toContainText('Nile FC');
  for (const screen of [
    'Beginner',
    'Tactical',
    'Player',
    'My club',
    'Judge Lab',
    'Compare perspectives',
    'Overlay feed',
  ]) {
    await page.getByRole('button', { name: screen, exact: true }).click();
    const audit = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
      .analyze();
    expect(audit.violations, screen).toEqual([]);
    for (const size of [
      { width: 1440, height: 1000 },
      { width: 375, height: 812 },
      { width: 812, height: 375 },
      { width: 320, height: 800 },
    ]) {
      await page.setViewportSize(size);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
        `${screen} ${size.width}`,
      ).toBe(true);
    }
    await page
      .getByRole('combobox', { name: 'Commentary language', exact: true })
      .selectOption('ar');
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
      `${screen} RTL`,
    ).toBe(true);
    await page.getByRole('combobox', { name: 'لغة التعليق', exact: true }).selectOption('en');
    await page.setViewportSize({ width: 1440, height: 1000 });
  }
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.getByRole('button', { name: 'Tactical', exact: true }).click();
  await expect(page.locator('.screen-content')).toHaveCSS('animation-name', 'none');
  await page.setViewportSize({ width: 375, height: 812 });
  await page.addStyleTag({ content: 'body {zoom:1.5}' });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
