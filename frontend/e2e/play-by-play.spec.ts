import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test('routine commentary follows passes before any big moment in every fan interface', async ({
  page,
}) => {
  const calls = new Map<string, { show_at_s: number; text: { en: string; ar: string } }>();
  let clock = 0;
  let sockets = 0;
  page.on('websocket', (ws) => {
    if (!ws.url().includes('/ws/demo/')) return;
    sockets++;
    ws.on('framereceived', (frame) => {
      const msg = JSON.parse(String(frame.payload));
      if (msg.type === 'event' && msg.commentary) calls.set(msg.data.event_id, msg.commentary);
      if (['state', 'tracking'].includes(msg.type)) clock = msg.game_time_s;
    });
  });
  await page.goto('/#/beginner');
  await page.getByRole('button', { name: 'Watch demo match', exact: true }).click();
  await expect(page.locator('.play-by-play [data-event-type="pass"]').first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Show earlier plays', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Pause', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Play', exact: true })).toBeVisible();
  await expect(page.locator('.commentary .overlay-card')).toHaveCount(0);
  const latest = page.locator('.play-latest');
  const id = (await latest.getAttribute('data-event-id'))!;
  await expect(latest.locator('p')).toHaveText(calls.get(id)!.text.en);
  for (const id of await page
    .locator('.play-by-play [data-event-id]')
    .evaluateAll((els) => els.map((el) => el.getAttribute('data-event-id')!))) {
    expect(calls.get(id)!.show_at_s).toBeLessThanOrEqual(clock);
  }
  const href = (await latest.getByRole('link').getAttribute('href'))!;
  const source = await page.request.get(href);
  expect(source.ok()).toBe(true);
  expect((await source.json()).event_id).toBe(id);
  const before = await page.locator('.play-history li').count();
  await page.getByRole('button', { name: 'Show earlier plays', exact: true }).click();
  expect(await page.locator('.play-history li').count()).toBeGreaterThan(before);
  await page.getByRole('button', { name: 'Watch at match speed', exact: true }).click();
  await expect(page.getByRole('combobox', { name: 'Replay speed', exact: true })).toHaveValue('1');
  for (const fan of ['Tactical', 'Player', 'My club', 'Beginner']) {
    await page.getByRole('button', { name: fan, exact: true }).click();
    await expect(page.locator('.play-latest')).toHaveAttribute('data-event-id', id);
  }
  expect(sockets).toBe(1);
  await page.locator('.language-switch select').selectOption('ar');
  await expect(page.locator('.play-by-play')).toHaveAttribute('dir', 'rtl');
  await expect(page.locator('.play-latest > p')).toHaveText(calls.get(id)!.text.ar);
  expect(
    (
      await new AxeBuilder({ page })
        .include('.play-by-play')
        .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
        .analyze()
    ).violations,
  ).toEqual([]);
  await page.setViewportSize({ width: 375, height: 812 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.locator('.play-by-play').screenshot({ path: 'test-results/play-by-play-arabic.png' });
});
