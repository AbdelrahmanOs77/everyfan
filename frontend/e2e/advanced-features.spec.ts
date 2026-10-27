import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test('live layers, player analysis, checked chat and reports work in English and Arabic', async ({
  page,
}) => {
  test.setTimeout(120000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/#/tactical');
  await page.getByRole('button', { name: 'Watch demo match', exact: true }).click();
  await expect(page.locator('.pitch-player')).toHaveCount(22);
  await page.locator('.highlight-list button').first().click();
  await expect(page.getByRole('button', { name: 'Play', exact: true })).toBeVisible();
  await page.getByRole('combobox', { name: 'Analysis window', exact: true }).selectOption('60');
  await page.getByRole('button', { name: 'Live pitch', exact: true }).click();
  await expect(page.locator('.live-tactics')).toBeVisible({ timeout: 25000 });
  await expect(page.locator('.pitch-layers')).toHaveCount(1);
  await page.getByRole('button', { name: 'Space control', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Space control', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect(page.locator('.pitch-layers > path')).toHaveCount(22);
  await page.locator('.live-tactics').screenshot({ path: 'test-results/advanced-live-pitch.png' });
  await page.getByRole('button', { name: 'Player', exact: true }).click();
  await page.getByRole('combobox', { name: 'Follow a player', exact: true }).selectOption('nil_09');
  await expect(page.locator('.player-analysis')).toContainText('EveryFan role index (heuristic)', {
    timeout: 25000,
  });
  await expect(page.locator('.benchmark-radar')).toBeVisible();
  await page.getByRole('button', { name: 'Ask the match', exact: true }).click();
  await page.getByRole('button', { name: 'Compare the teams', exact: true }).click();
  await expect(page.locator('.answer-card')).toContainText('Nile FC');
  await expect(page.locator('.answer-card')).toContainText('Template');
  await page.locator('.answer-card').getByRole('button', { name: 'Evidence', exact: true }).click();
  await expect(page.locator('.feature-evidence')).toContainText('evt_');
  await page.keyboard.press('Escape');
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: 'Report so far', exact: true }).click();
  await expect(page.locator('.report-overlay')).toContainText('Stat leaders by category', {
    timeout: 25000,
  });
  await expect(page.locator('.report-overlay table').first()).toContainText('Possession');
  await page.keyboard.press('Escape');
  for (const language of ['en', 'ar']) {
    await page.locator('.language-switch select').selectOption(language);
    await expect(page.locator('.player-analysis')).toBeVisible();
    if (language === 'ar') {
      await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
      await page.getByRole('button', { name: 'اسأل المباراة', exact: true }).click();
      await page.getByRole('button', { name: 'قارن الفريقين', exact: true }).click();
      await expect(page.locator('.answer-card')).toContainText('نادي النيل');
      await page.keyboard.press('Escape');
    }
    await page.setViewportSize({ width: 375, height: 850 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    expect(
      (await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze())
        .violations,
    ).toEqual([]);
    await page
      .locator('.player-analysis')
      .screenshot({ path: `test-results/advanced-player-${language}.png` });
  }
  expect(errors).toEqual([]);
});
