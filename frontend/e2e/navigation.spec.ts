import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test('independent screens preserve one replay, support deep links and browser history', async ({
  page,
}) => {
  let connections = 0;
  page.on('websocket', (ws) => {
    if (ws.url().includes('/ws/demo/')) connections++;
  });
  await page.goto('/#/match');
  await page.getByRole('button', { name: 'Watch demo match', exact: true }).click();
  await expect(page.locator('.pitch-player')).toHaveCount(22);
  await page.locator('.highlight-list button').first().click();
  await expect(page.getByRole('button', { name: 'Play', exact: true })).toBeVisible();
  const clock = await page.getByTestId('viewer-clock').textContent();
  await page.getByRole('button', { name: 'Perspectives', exact: true }).click();
  await expect(page).toHaveURL(/#\/perspectives$/);
  await expect(page.locator('h1')).toBeFocused();
  await expect(page.locator('.pitch')).toHaveCount(0);
  await expect(page.locator('.indices')).toHaveCount(0);
  await expect(page.locator('.comparison-pane')).toHaveCount(4);
  await expect(page.getByTestId('viewer-clock')).toHaveText(clock!);
  await page.getByRole('button', { name: 'Insights', exact: true }).click();
  await expect(page.locator('.indices')).toBeVisible();
  await expect(page.locator('.player-ticker')).toBeVisible();
  await expect(page.locator('.pitch')).toHaveCount(0);
  await expect(page.locator('.comparison-pane')).toHaveCount(0);
  await page.goBack();
  await expect(page).toHaveURL(/#\/perspectives$/);
  await page.goForward();
  await expect(page).toHaveURL(/#\/insights$/);
  await page.getByRole('button', { name: 'Judge Lab', exact: true }).click();
  await expect(page.locator('.lab-actions')).toBeVisible();
  await expect(page.locator('.pitch,.indices,.comparison-pane')).toHaveCount(0);
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
  await expect(page.locator('.empty-commentary')).toContainText('No matching commentary');
  await expect(page.locator('.pitch,.indices,.preferences-panel,.lab-actions')).toHaveCount(0);
  await page.getByRole('button', { name: 'Match', exact: true }).click();
  await expect(page.getByTestId('viewer-clock')).toHaveText(clock!);
  expect(connections).toBe(1);
  await page.goto('/#/insights');
  await expect(page.getByRole('button', { name: 'Insights', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  );
  await expect(page.locator('.indices')).toBeVisible();
});

test('all screens are responsive and accessible in English and Arabic', async ({ page }) => {
  test.setTimeout(90000);
  await page.goto('/#/match');
  await expect(page.locator('.match-context-name')).toContainText('Nile FC');
  for (const screen of ['Match', 'Perspectives', 'Insights', 'Judge Lab', 'Overlay feed']) {
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
    await page.locator('h1').focus();
    await page.screenshot({
      path: `test-results/screen-${screen.toLowerCase().replaceAll(' ', '-')}.png`,
      fullPage: true,
    });
  }
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.getByRole('button', { name: 'Insights', exact: true }).click();
  expect(
    await page.locator('.screen-content').evaluate((el) => getComputedStyle(el).animationName),
  ).toBe('none');
  await page.setViewportSize({ width: 375, height: 812 });
  await page.addStyleTag({ content: 'body {zoom: 1.5}' });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
