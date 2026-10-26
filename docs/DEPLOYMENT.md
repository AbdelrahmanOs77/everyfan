# Deploying EveryFan's backend to Azure (Azure for Students)

The full path from an empty subscription to a public, smoke-tested API takes about 30 minutes.
Every step below has been run against a simulated Azure CLI; the Bicep template compiles and lints clean.

## What gets created

One resource group, in a region your subscription allows:

| Resource | Why | Cost note |
| --- | --- | --- |
| Event Hubs namespace, **Basic**, 1 TU + hub `match-events` (2 partitions, 1-day retention) | the match event stream | $0.015 per TU-hour ≈ $11/month; a full match is ~13k messages (negligible) |
| User-assigned managed identity | passwordless access to Event Hubs | free |
| Role assignments (identity: Data Sender + Data Receiver; you: Data Owner) | least privilege | free |
| Log Analytics workspace, capped at 0.1 GB/day | container logs | capped |
| Container Apps environment + app `everyfan-api` (0.5 vCPU / 1 GiB, **min = max = 1 replica**) | the API, WebSockets, replay | first 180,000 vCPU-s and 360,000 GiB-s per month free; always-on beyond that, mostly at the reduced idle rate |
| Monthly budget with e-mail alerts at 50% / 80% / forecast 100% | protect your $100 credit | free |

The image is built by GitHub Actions and stored in **GitHub Container Registry**, because ACR Tasks
(`az acr build`) are paused for trial-credit subscriptions such as Azure for Students.

## Step 0 — Prerequisites (once)

- Azure CLI ([install](https://aka.ms/installazurecli)) and Python 3.11+.
- Your team's **public** GitHub repository containing this code (`main` branch).
- Find your allowed regions: Portal → **Policy → Assignments → "Allowed resource deployment regions"** →
  Parameters → *Allowed locations*. Use one of them for **every** team resource (tell Owners B and C).

## Step 1 — Publish the image

1. Push to `main`. The **image** workflow (Actions tab) builds the container, runs it, smoke-tests it,
   and only then pushes `ghcr.io/<owner>/<repo>-backend:<sha>` and `:latest`.
2. First time only: GitHub → your profile/org → **Packages** → `<repo>-backend` → Package settings →
   **Change visibility → Public** (so Azure can pull it without credentials; the repo is public anyway).

## Step 2 — Deploy

Windows (PowerShell):
```powershell
pip install -r requirements-dev.txt
./deployment/deploy.ps1 -Location <allowed-region> `
    -Image ghcr.io/<owner>/<repo>-backend:latest `
    -FrontendOrigin https://<your-static-web-app>.azurestaticapps.net `
    -AlertEmail <you@example.com>
```
macOS / Linux / Cloud Shell:
```bash
./deployment/deploy.sh --location <allowed-region> --image ghcr.io/<owner>/<repo>-backend:latest \
    --frontend-origin https://<your-static-web-app>.azurestaticapps.net --alert-email <you@example.com>
```

The script logs you in, registers providers, deploys `deployment/azure/main.bicep`, waits for health,
and runs the smoke test (13 checks, including a live run through Event Hubs). It prints the API URL and saves:
- `deployment/.admin-token` — the `X-Admin-Token` (git-ignored, keep it private),
- `.env.azure` — Event Hubs settings for your laptop (no secrets; you were given the Data Owner role).

Other owners' settings go in as environment variables:
`-ExtraEnvJson '[{"name":"FOUNDRY_PROJECT_ENDPOINT","value":"https://..."},{"name":"COSMOS_ENDPOINT","value":"https://..."}]'`
and their plugins via `PIPELINE_PLUGINS` (redeploy with the same command; it is idempotent).

If you don't know the frontend URL yet, deploy with the default and re-run with `-FrontendOrigin` later.
Several origins: `-FrontendOrigin "https://a.azurestaticapps.net,http://localhost:5173"`.

## Step 2b — Turn on the integrated pipeline (agents, Foundry, Cosmos, tracing)

The app runs analytics + agents by default. With no settings the agents publish **checked templates**
(zero model cost). To switch on live Foundry agents on the running app, no redeploy needed:

```powershell
copy deployment\integration.env.example deployment\integration.env   # git-ignored; paste FOUNDRY_API_KEY etc.
./deployment/enable-integration.ps1                                   # -CosmosAccount <name> -CosmosResourceGroup <rg>
```
```bash
cp deployment/integration.env.example deployment/integration.env
./deployment/enable-integration.sh                                    # --cosmos-account <name> --cosmos-rg <rg>
```

It creates Application Insights on the existing Log Analytics workspace, stores `FOUNDRY_API_KEY`, `MCP_API_KEY`
(generated into the git-ignored `deployment/.mcp-api-key`), `COSMOS_KEY` and the App Insights connection string as
Container Apps secrets, sets `PIPELINE_PLUGINS`, `AGENT_*`, `FOUNDRY_*`, `MCP_*`, `COSMOS_*`, waits for the new
revision and runs the smoke test (now also: agents loaded, overlay feed, Arabic recap, Break it, MCP with and
without the key, verified live overlays). The full `deploy.*` scripts read the same file. Why a key for
Foundry: the app's managed identity is in this Azure account, Foundry is in Owner C's, and roles cannot be
granted across tenants.

## Step 3 — Use Event Hubs from your laptop (optional)

```powershell
copy .env.azure .env
az login
python -m backend.cli eh-check
python -m backend.cli consume                     # terminal 1
python -m backend.cli replay --speed 20           # terminal 2 (shares the hub with the cloud API)
```
Role assignments can take up to ~10 minutes to apply after the first deployment.

## Step 4 — Ship updates

Every push to `main` publishes a tested image. Roll the app forward with the tag from the workflow summary:
```powershell
./deployment/update-image.ps1 -Image ghcr.io/<owner>/<repo>-backend:<sha>
```
Roll back the same way with an older tag. Never deploy `:latest` blindly during judging.

## Step 5 — Before you submit (Oct 27)

- [ ] `python -m backend.cli smoke --url <api> --origin <frontend> --live --admin-token <token>` → 13/13
- [ ] Open the frontend on a phone, on mobile data, in a private window
- [ ] `/api/health`: `transport` is `eventhubs`, `transport_fallback_reason` is `null`, `pipeline.errors` is 0
- [ ] `demo_bundles` shows the agent plugins and `overlay_sources` with `agent/approved` (record it with
      `./deployment/build-demo-agents.ps1 -Scenario derby_balanced`, see [INTEGRATION.md](INTEGRATION.md))
- [ ] `agents.mode` is `foundry` with `auth: key`, `agents.tools.transport` is `McpEvidenceTools`
- [ ] Budget alert e-mail address is right (Portal → Cost Management → Budgets)
- [ ] Note the deployed image tag in the README

## Judging period (Oct 27 – Nov 10): run book

The app is built to survive unattended: cached demo for judges (zero model cost), per-IP rate limits,
one live broadcast per match with a control token, idle live broadcasts stopped after 5 minutes,
a daily model-token cap, self-healing Event Hubs fallback, min replicas = 1, health probes that restart a hung container.

Daily (2 minutes):
1. `python -m backend.cli smoke --url <api>` (no `--live`, costs nothing).
2. Look at `/api/budget` and Portal → Cost Management → Cost analysis.

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Smoke: health fails | revision crashed or image pull failed | `az containerapp logs show -n everyfan-api -g rg-everyfan-hackathon --tail 100`; `az containerapp revision list -n everyfan-api -g rg-everyfan-hackathon -o table`; roll back with `update-image` |
| Image pull error on deploy | GHCR package is private | Step 1.2 (make it public) |
| `transport_fallback_reason` set | Event Hubs role not applied yet / namespace issue | wait 10 min (app re-checks every minute); `az role assignment list --scope <namespace id> -o table` |
| `RequestDisallowedByAzure` | region not allowed | re-run with an allowed `-Location` |
| `MissingSubscriptionRegistration` | provider not registered | `az provider register --namespace Microsoft.App --wait` (the script does this) |
| Budget step fails | budgets unsupported for the offer | the script retries without it; create the budget in the portal |
| Judges see 409 on Run live | someone else's live broadcast is running | expected: they can join it, or use the demo; admin can take over with `X-Admin-Token` |
| Live overlays become templates | daily token cap reached, or the 30k tokens/min Foundry quota at high replay speed | expected cost protection; run live at 1x/5x, raise capacity, or `AGENT_CLUB_PERSONA=0` |
| `agents.fast` missing or overlays all templates after enabling | wrong/missing `FOUNDRY_API_KEY` or endpoint | `az containerapp logs show ...`; re-run `enable-integration` with the right key |
| Traces missing in App Insights | connection string not set, or Log Analytics daily cap (0.1 GB) reached | re-run `enable-integration`; raise `dailyQuotaGb` in `main.bicep` if needed |
| Credit running low | | `az containerapp update -n everyfan-api -g rg-everyfan-hackathon --set-env-vars LIVE_MODE_DAILY_TOKEN_CAP=0` (demo keeps working) |

Do not push risky changes to the deployed app during judging; if you must, deploy a tested tag and smoke test it.

## After Nov 10

```bash
az group delete -n rg-everyfan-hackathon --yes --no-wait
```

## Security summary

- No keys in the repo or the image; the app authenticates to Event Hubs with its managed identity.
- The admin token is a Container Apps secret; `deployment/.admin-token` and `.env*` are git-ignored.
- The container runs as a non-root user; CORS is restricted to the frontend origin(s).
- The Event Hubs namespace keeps local (SAS) auth enabled only for a first laptop test; set
  `disableLocalAuth: true` in `main.bicep` once everyone uses `az login`.
