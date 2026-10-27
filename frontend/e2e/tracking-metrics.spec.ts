import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import type { AdvancedStats, FanStats } from '../src/types';

const number = (value: number | null) =>
  value == null ? '—' : value.toLocaleString('en-US', { maximumFractionDigits: 2 });

test('shape and high-intensity cards show server measurements for the selected windows', async ({
  page,
}) => {
  test.setTimeout(90000);
  await page.goto('/#/tactical');
  await page.getByRole('button', { name: 'Watch demo match', exact: true }).click();
  await expect(page.locator('.pitch-player')).toHaveCount(22);
  await page.locator('.highlight-list button').first().click();
  await expect(page.getByRole('button', { name: 'Play', exact: true })).toBeVisible();
  for (const window of [60, 300, 900, 5400]) {
    const response = page.waitForResponse(
      (r) =>
        r.url().includes('/advanced-stats?') && r.url().includes(`window_s=${window}`) && r.ok(),
    );
    await page
      .getByRole('combobox', { name: 'Analysis window', exact: true })
      .selectOption(String(window));
    const data: AdvancedStats = await (await response).json();
    expect(data.tracking).not.toBeNull();
    for (const team of ['nile_fc', 'delta_utd']) {
      await page.getByRole('combobox', { name: 'Team', exact: true }).selectOption(team);
      for (const key of ['mean_width_m', 'mean_length_m', 'defensive_line_height_m'] as const) {
        await expect(page.locator(`.team-shape [data-tracking-metric="${key}"] bdi`)).toHaveText(
          number(data.tracking!.teams[team]![key]),
        );
      }
      expect(data.tracking!.teams[team]!.evidence!.to_s).toBeLessThanOrEqual(data.at_s);
    }
  }
  await page.locator('.team-shape').screenshot({ path: 'test-results/tracking-team-shape.png' });
  await page.getByRole('button', { name: 'Player', exact: true }).click();
  for (const window of [60, 300, 900, 5400]) {
    const response = page.waitForResponse(
      (r) => r.url().includes('/fan-stats?') && r.url().includes(`window_s=${window}`) && r.ok(),
    );
    await page
      .getByRole('combobox', { name: 'High-intensity window', exact: true })
      .selectOption(String(window));
    const data: FanStats = await (await response).json();
    for (const player of ['nil_06', 'del_06']) {
      await page
        .getByRole('combobox', { name: 'Follow a player', exact: true })
        .selectOption(player);
      const row = data.tracking.players[player]!;
      await expect(
        page.locator('.high-intensity [data-tracking-metric="distance_above_threshold_m"] bdi'),
      ).toHaveText(number(row.distance_above_threshold_m));
      await expect(page.locator('.high-intensity [data-tracking-metric="sprints"] bdi')).toHaveText(
        number(row.sprints),
      );
      expect(row.evidence!.to_s).toBeLessThanOrEqual(data.at_s);
    }
  }
  await page.getByText('High-intensity frame evidence', { exact: true }).click();
  const href = await page
    .getByRole('link', { name: 'Original tracking samples', exact: true })
    .getAttribute('href');
  const raw = await page.request.get(href!);
  expect(raw.ok()).toBe(true);
  const source = await raw.json();
  expect(source.samples.every((s: { at_s: number }) => s.at_s <= source.at_s)).toBe(true);
  await page
    .locator('.high-intensity')
    .screenshot({ path: 'test-results/tracking-high-intensity.png' });
  for (const language of ['en', 'ar']) {
    await page.locator('.language-switch select').selectOption(language);
    expect(
      (await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze())
        .violations,
    ).toEqual([]);
    await page.setViewportSize({ width: 320, height: 800 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.setViewportSize({ width: 1440, height: 1000 });
  }
});
