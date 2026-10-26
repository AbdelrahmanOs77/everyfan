// Run against an off-mode local API and the Vite viewer. Output is a local draft,
// not a public submission. Windows Zira narration is added by the delivery script.
import { chromium } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const output = path.resolve('../.venv/handoff/owner-d/delivery');
await mkdir(output, { recursive: true });
const chapters = [
  [
    0,
    12,
    'One goal. Four perspectives. EveryFan explains the same verified moment for a beginner, a tactical analyst, a player fan, and an Arabic-speaking viewer.',
  ],
  [
    12,
    25,
    'EveryFan is a personalised football broadcast built for the Multi-Agent category. Every club, player, and match is fictional. The recorded demo costs no model tokens to watch.',
  ],
  [
    25,
    45,
    'The pitch uses actual simulator tracking. Scores, match time, player statistics, and game indices come from backend evidence. Choose your player or club, switch language, pause the replay, and explore the same match from your perspective.',
  ],
  [
    45,
    70,
    'Distinct agents share responsibility. The Producer plans the coverage. The Analyst reads evidence through read-only MCP tools. Persona writers draft the story. The Verifier checks names, numbers, contracts, and evidence. Rejected copy gets one repair attempt, then a checked template. Only verified output reaches the delayed broadcast.',
  ],
  [
    70,
    85,
    'Break it makes that safeguard visible. An invented number enters a draft. The Verifier rejects it, and a checked replacement is shown. This deterministic demonstration never calls a model.',
  ],
  [
    85,
    100,
    'Open the evidence behind a card: measured facts, the detection rule, and source events. Our thirty-moment Foundry evaluation measured ninety-one percent raw numeric faithfulness, and one hundred percent after verification, including template fallbacks.',
  ],
  [
    100,
    115,
    'A personalised recap tells the story so far. The public overlay feed and schema make verified commentary reusable on other screens. EveryFan: one match, millions of stories. Try the demo, then test the Verifier.',
  ],
];
await writeFile(path.join(output, 'chapters.json'), JSON.stringify(chapters, null, 2));
const browser = await chromium.launch({ channel: process.env.CI ? undefined : 'chrome' });
const context = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  recordVideo: { dir: output, size: { width: 1920, height: 1080 } },
});
const page = await context.newPage();
const video = page.video();
const started = Date.now();
const until = async (seconds) => {
  const remaining = started + seconds * 1000 - Date.now();
  if (remaining > 0) await page.waitForTimeout(remaining);
};
const goal = async () => {
  await page.getByRole('button', { name: 'Watch demo match', exact: true }).first().click();
  await page.locator('.pitch-player').first().waitFor();
  await page.locator('.highlight-list button').last().click();
  await page.getByRole('button', { name: 'Play', exact: true }).waitFor();
};
await page.goto('http://localhost:5173');
await goal();
await page.getByRole('button', { name: 'Four-way view', exact: true }).click();
await page.locator('.comparison').scrollIntoViewIfNeeded();
await until(12);
await page.getByRole('button', { name: 'Watch', exact: true }).click();
await page.evaluate(() => scrollTo(0, 0));
await until(25);
await page.getByRole('button', { name: /^Player focus/ }).click();
await page.getByRole('button', { name: 'Player names', exact: true }).click();
await page.getByRole('checkbox', { name: 'Pause at goals', exact: true }).uncheck();
await page.getByRole('combobox', { name: 'Replay speed', exact: true }).selectOption('5');
await page.getByRole('button', { name: 'Play', exact: true }).click();
await page.locator('.broadcast-stage').scrollIntoViewIfNeeded();
await until(36);
await page.locator('.indices').scrollIntoViewIfNeeded();
await until(45);
await page.setContent(
  `<!doctype html><html lang="en"><meta charset="utf-8"><title>EveryFan workflow</title><style>body{margin:0;padding:100px 120px;background:#101719;color:#eff4f1;font:24px 'Segoe UI',sans-serif}small{color:#c5ee70;letter-spacing:4px}h1{font-size:70px;letter-spacing:-3px;margin:20px 0 25px}p{color:#abbcaf;line-height:1.8}ol{display:grid;grid-template-columns:repeat(3,1fr);gap:25px;padding:0;list-style:none;margin-top:60px}li{border:1px solid #42543d;border-radius:12px;padding:28px;background:#1b2924;min-height:140px}b{display:block;color:#c5ee70;margin-bottom:20px;font-size:30px}span{font-size:20px;color:#c7d4ca}footer{border-top:1px solid #39473d;margin-top:35px;padding-top:25px;color:#a7bca6}</style><small>EVERYFAN / HOW VERIFICATION WORKS</small><h1>Many voices. One evidence trail.</h1><p>Recorded Foundry output in the demo. Shared facts, distinct responsibilities.</p><ol><li><b>Producer</b><span>Plans the coverage and perspectives.</span></li><li><b>Analyst + MCP</b><span>Reads measured facts and evidence.</span></li><li><b>Persona writers</b><span>Explain the play in the viewer’s language.</span></li><li><b>Verifier</b><span>Checks contracts, numbers, entities and evidence.</span></li><li><b>Repair or fallback</b><span>One repair attempt, then a checked template.</span></li><li><b>Broadcast + recap</b><span>Publishes verified stories on the match clock.</span></li></ol><footer>Simulator → Event Hubs → analytics → agents → verified overlays → viewer</footer></html>`,
);
await until(70);
await page.goto('http://localhost:5173');
await page.getByRole('button', { name: /^Break it/ }).click();
await page.locator('.approved-panel').waitFor();
await until(85);
await page.keyboard.press('Escape');
await goal();
await page
  .locator('.commentary')
  .getByRole('button', { name: 'Inspect evidence', exact: true })
  .first()
  .click();
await page.locator('.facts-grid').waitFor();
await until(100);
await page.keyboard.press('Escape');
await page.getByRole('button', { name: 'Match story', exact: true }).click();
await page.locator('.recap-body').waitFor();
await until(108);
await page.keyboard.press('Escape');
await page.getByRole('button', { name: 'Overlay feed', exact: true }).click();
await page.locator('.feed-grid .overlay-card').first().waitFor();
await page.evaluate(() => scrollTo(0, 0));
await until(115);
await context.close();
await video.saveAs(path.join(output, 'everyfan-raw.webm'));
await browser.close();
console.log(`Recorded local demo to ${output}`);
