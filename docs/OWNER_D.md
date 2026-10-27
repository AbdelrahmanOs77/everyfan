# Owner D: viewer and delivery

The user reviewed Step 5 in place of Owner B and merged PR #5. Owner C's final
Step 6 handoff is complete: the reviewed backend contracts, demo content, evaluation
limits and remaining cloud dependencies are recorded in
[HANDOFF_OWNER_D.md](HANDOFF_OWNER_D.md). This change implements the React viewer
from section 8 of the Master Implementation Plan. No frozen contract or Owner A/B
Python source changes are needed.

## Implemented

The subsequent [independent-screen redesign](OWNER_D_UI.md) replaces the original
shared layout with top navigation for Match, Perspectives, Insights, Judge Lab
and Overlay feed. Playback persists between destinations; the new UI can be
tested locally before deployment. The original demo video shows the earlier UI.

- Judge actions: recorded demo, shared live broadcast and deterministic Break it.
- Real stream positions, ball, metadata team colours, player name tags and measured
  milestone badges. Score and clock come from state/tracking; no client football
  statistics are invented.
- Four perspectives, English/Arabic, favorite player and club, browser preferences.
  A single unfiltered socket keeps perspective changes on the same match clock.
- Timed, deduplicated, verified overlays with per-slot priority and expiry; early
  overlays never advance the picture. Demo pauses at goals by default so judges
  can read the cards. Uncheck that option for continuous replay.
- Four-way comparison, evidence facts/rules/events, trace ID copy, measured
  Control/Chaos/Rhythm/PPDA, possession, player distance/speed/badges, recap and
  machine-readable feed/schema links.
- Private per-viewer demo controls; in-memory live host token and read-only join.
- Responsive RTL layout, keyboard controls, native modal focus, loading/error/retry
  states, reduced-motion support and no external fonts or club assets.
- Pinned npm dependencies, unit and isolated browser tests, CI gates, Free Static
  Web Apps Bicep, SPA/security headers, and deployment after successful CI on main.

## Local setup

Use Python 3.12 and Node 22.12 or newer. From the repository root:

```powershell
$env:AGENT_MODE='off'
.\.venv\py312\Scripts\python.exe -m backend.cli serve
```

In another terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open **http://localhost:5173**. The Vite proxy forwards `/api` and `/ws` to the
local API. Local Chrome is used by browser tests; CI installs isolated Chromium.
To use the deployed backend locally, copy `.env.example` to `.env.local` inside
`frontend` and restart Vite. Vite variables are public build configuration:
never put model keys or control/admin tokens there. A different production API
also requires updating the explicit CSP `connect-src` allowlist.

```powershell
npm run format:check
npm test
npm run build
npm run test:e2e
```

Browser tests start their own off-mode API on port 8011 and viewer on 5175.
They refuse to reuse existing servers and override public API configuration.
They never call Azure or a real model.

## Verification on 2026-10-27 (Cairo)

- Python 3.12: **573 tests passed**, Pyflakes clean.
- Required stub injection gate: **236/236 published numerically faithful**;
  all **80** injected drafts caught; no model calls.
- TypeScript strict build and production bundle passed; seven scheduler tests
  passed. A deliberate priority inversion was caught by the priority test and
  restored before delivery.
- Five Chrome acceptance scenarios cover demo/four-way/evidence/RTL/club
  preferences/Break it/recap/feed, responsive keyboard/accessibility, failed API
  recovery, a complete 60× replay and seek, and live host/read-only joining.
  The accessibility pass found and fixed an SVG grouping issue; no checks were
  disabled. WCAG A/AA axe checks pass on the landing and active viewer.
- Widths 320, 375, 768 and 1440 pixels checked without horizontal page overflow;
  desktop and Arabic-phone screenshots are committed under `docs/images/`.
- npm dependency audit: **zero vulnerabilities**. Bicep compiles successfully.
- Separately, a read-only deployed-API browser smoke check verified HTTPS/WSS
  demo, evidence, Arabic, club filtering, Break it, recap and feed from its
  already trusted localhost origin, without live/model calls. This does not
  establish CORS for the eventual public Static Web Apps hostname.
- Local video: **1:55**, H.264 1920×1080 at 30 fps, AAC English narration and
  burned English captions. Raw recording and SRT retained locally.

![Desktop viewer](images/owner-d-viewer.png)

The automated checks establish local behavior, not public-site or physical-phone
acceptance. Those checks remain pending the hosting dependency below.

## Azure deployment dependency

On 2026-10-27 Cairo time, Azure MCP/CLI inspection found that the active
subscription `551facf2-3534-45ff-b57d-df6fea6b7ca2` allows only `uaenorth`,
`italynorth`, `polandcentral`, `switzerlandnorth`, `germanynorth`. The provider
lists Static Web Apps only in `centralus`, `eastus2`, `westus2`, `westeurope`,
`eastasia`. There is no overlap. No unsupported deployment or unrelated-resource
change was attempted. The backend Container App is also outside this account's
accessible resources. A live frontend URL therefore remains pending an account
with an allowed Static Web Apps region and Owner A's backend CORS update.

In that subscription, run:

```powershell
.\deployment\deploy-frontend.ps1 -Subscription '<target-subscription-id>' -Location westeurope
```

This creates only a dedicated Free Static Web App and outputs its origin. Store
its deployment token using Azure Portal → Static Web App → Manage deployment
token → GitHub repository Settings → Actions secrets:
`AZURE_STATIC_WEB_APPS_API_TOKEN`. Never paste the token into this chat or commit
it. Set repository Actions variable `FRONTEND_DEPLOY_ENABLED=true` after CORS is
ready. On a push/merge to main, CI deploys the exact tested `frontend-dist`
artifact only after both Python and browser gates succeed.

Owner A must read the existing backend `FRONTEND_ORIGIN`, append the exact
`https://<hostname>.azurestaticapps.net` origin, preserve existing trusted origins,
and update the Container App. HTTPS and WSS both use that same origin allowlist.
Verify browser demo, Arabic, evidence and Break it from the actual public site.
Do not use wildcard CORS or a proxy to evade this dependency.

Rollback: set `FRONTEND_DEPLOY_ENABLED=false`, revert the frontend change on main,
and re-enable deployment after the checks pass. Backend state and contracts are
unaffected. Watch browser errors, API health and WebSocket reconnect behavior
after rollout. Keep the site available for the judging period specified by the
submission rules; this change does not create an automatic teardown.

## Delivery and remaining human checks

[TESTING_GUIDE.md](TESTING_GUIDE.md) describes the judge flow.
[OWNER_D_DELIVERY.md](OWNER_D_DELIVERY.md) contains the English pitch, recording
script and submission checklist. Screenshots/recording are local evidence until
the final public deployment can be recorded and checked.

- Public site, cross-origin HTTPS/WSS and another device/mobile network: pending
  the Azure access/policy dependency above.
- Native Arabic review of the recorded agent overlays was completed in Step 4.
  The newly written interface strings still need native-speaker signoff.
- Evidence displays real workflow trace IDs where attached. Azure trace ingestion
  and portal deep links need Owner A's Application Insights resource access;
  unverified traces and quality-judge scores are not claimed.
- Public YouTube/Vimeo upload, logged-out URL verification and final hackathon
  submission remain account-holder actions. No submission has been sent.

Official deployment references: [Static Web Apps configuration](https://learn.microsoft.com/azure/static-web-apps/configuration),
[GitHub deployment workflow](https://docs.github.com/actions/how-tos/deploy/deploy-to-third-party-platforms/azure-static-web-app),
[Playwright browser testing](https://playwright.dev/docs/browsers).
