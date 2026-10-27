import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import type { FanStats } from '../src/types';

test('fan extras reconcile with evidence across all Tactical windows and both languages', async ({
  page,
}) => {
  test.setTimeout(90000);
  const failed: string[] = [];
  page.on('response', (r) => {
    if (/\/(fan-stats|advanced-stats|tracking-samples)/.test(r.url()) && r.status() >= 400)
      failed.push(`${r.status()} ${r.url()}`);
  });
  await page.goto('/#/tactical');
  await page.getByRole('button', { name: 'Watch demo match', exact: true }).click();
  await expect(page.locator('.pitch-player')).toHaveCount(22);
  await page.locator('.highlight-list button').first().click();
  await expect(page.getByRole('button', { name: 'Play', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Passing & territory', exact: true }).click();
  for (const window of [60, 300, 900, 5400]) {
    const response = page.waitForResponse(
      (r) => r.url().includes('/fan-stats?') && r.url().includes(`window_s=${window}`) && r.ok(),
    );
    await page
      .getByRole('combobox', { name: 'Analysis window', exact: true })
      .selectOption(String(window));
    const data: FanStats = await (await response).json();
    const positions = data.teams.nile_fc!.average_positions;
    await expect(page.locator('.tracking-positions tbody tr')).toHaveCount(positions.length);
    await expect(page.locator('.tracking-positions tbody tr').first()).toContainText(
      positions[0]!.sample_count.toString(),
    );
    const href = await page.locator('.tracking-positions tbody tr a').first().getAttribute('href');
    const source = await page.request.get(href!);
    expect(source.ok()).toBe(true);
    expect((await source.json()).total).toBe(positions[0]!.sample_count);
    await expect(page.locator('.territory-grid')).toBeVisible();
  }
  await page.locator('h1').focus();
  await page.keyboard.press('Control+Home');
  await page.screenshot({ path: 'test-results/fan-tracking.png', fullPage: true });
  await page.getByRole('button', { name: 'Shots & actions', exact: true }).click();
  await expect(page.locator('.shot-evidence')).toBeVisible();
  await page.getByRole('button', { name: 'Player', exact: true }).click();
  await expect(page.locator('.leaderboard tbody tr')).toHaveCount(5);
  const leaders = await page.request.get(
    (await page.locator('.leaderboard .data-stamp a').getAttribute('href'))!,
  );
  const playerData: FanStats = await leaders.json();
  await expect(page.locator('.leaderboard tbody tr').first()).toContainText(
    playerData.teams.nile_fc!.leaderboards.distance_km[0]!.value.toLocaleString('en-US', {
      maximumFractionDigits: 2,
    }),
  );
  await page
    .getByRole('combobox', { name: 'Leaderboard metric', exact: true })
    .selectOption('top_speed_kmh');
  await expect(page.locator('.leaderboard tbody tr').first()).toContainText(
    playerData.teams.nile_fc!.leaderboards.top_speed_kmh[0]!.value.toLocaleString('en-US', {
      maximumFractionDigits: 1,
    }),
  );
  await page.locator('.leaderboard tbody tr button').first().click();
  await expect(page.locator('.selected-player-row')).toHaveCount(1);
  await page.locator('h1').focus();
  await page.keyboard.press('Control+Home');
  await page.screenshot({ path: 'test-results/fan-leaderboard.png', fullPage: true });
  await page.getByRole('button', { name: 'My club', exact: true }).click();
  await page
    .getByRole('combobox', { name: 'Support a club', exact: true })
    .selectOption('delta_utd');
  await expect(page.locator('.club-comparison')).toContainText('PPDA');
  await expect(page.locator('.club-key-moments article')).toHaveCount(
    playerData.teams.delta_utd!.key_moments.length,
  );
  await page.locator('h1').focus();
  await page.keyboard.press('Control+Home');
  await page.screenshot({ path: 'test-results/fan-club-summary.png', fullPage: true });
  await page.getByRole('button', { name: 'Beginner', exact: true }).click();
  await expect(page.locator('.on-top')).toBeVisible();
  await page.getByText('Momentum data & evidence', { exact: true }).click();
  await expect(page.locator('.momentum-data tbody tr')).toHaveCount(
    playerData.momentum_timeline.length,
  );
  const lastPoint = playerData.momentum_timeline.at(-1)!;
  await expect(page.locator('.momentum-data tbody tr').last()).toContainText(
    lastPoint.teams.nile_fc!.value.toLocaleString('en-US', { maximumFractionDigits: 1 }),
  );
  await page.getByText('Momentum data & evidence', { exact: true }).click();
  await page.locator('h1').focus();
  await page.keyboard.press('Control+Home');
  await page.screenshot({ path: 'test-results/fan-beginner-extras.png', fullPage: true });
  for (const screen of ['Beginner', 'Tactical', 'Player', 'My club']) {
    await page.getByRole('button', { name: screen, exact: true }).click();
    await expect(page.locator('.momentum-panel')).toBeVisible();
    for (const language of ['en', 'ar']) {
      await page.locator('.language-switch select').selectOption(language);
      const audit = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
        .analyze();
      expect(audit.violations, `${screen} ${language}`).toEqual([]);
      await page.setViewportSize({ width: 320, height: 800 });
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
        `${screen} ${language} mobile`,
      ).toBe(true);
      await page.setViewportSize({ width: 1440, height: 1000 });
    }
    await page.locator('.language-switch select').selectOption('en');
  }
  const backwards = page.waitForResponse((r) => {
    const at = Number(new URL(r.url()).searchParams.get('at_s'));
    // A seek emits a reset at zero before the picture reaches its requested time.
    return r.url().includes('/fan-stats?') && r.ok() && at > 0 && at < playerData.at_s;
  });
  await page.locator('h1').focus();
  await page.keyboard.press('ArrowLeft');
  const earlier: FanStats = await (await backwards).json();
  expect(earlier.at_s).toBeLessThan(playerData.at_s);
  await expect(page.locator('.momentum-panel .data-stamp')).toContainText(
    `${Math.floor(earlier.at_s / 60)
      .toString()
      .padStart(2, '0')}:${(earlier.at_s % 60).toString().padStart(2, '0')}`,
  );
  expect(failed).toEqual([]);
});
