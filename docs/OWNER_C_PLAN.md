# EveryFan — Owner C (Foundry & Agents) build plan for Codex

> Written Sun Oct 25, 2026, 21:45 Cairo, from the state of `main` at commit `ad0f898`
> (Owner B's PR merged). Goal: **all Owner C work finished today**, in the phase order below.
> The order front-loads everything that makes the demo safe even if Foundry never answers,
> so stopping at any phase still leaves a working product.

---

## 0. The one-paragraph brief (paste this to Codex first)

EveryFan is a FastAPI + plugin pipeline. Owner A built the simulator, stream, API, demo bundles and
Azure deploy. Owner B built analytics: every match event goes through a `MomentDetector` that publishes
Contract B `Moment`s (`mom_001…`) and exposes evidence via REST and in-process objects. **Owner C
(us) adds `backend/agents/`**: a pipeline plugin that listens to Owner B's moments, runs
Producer → Analyst (with read-only MCP evidence tools) → persona writers (concurrent) → Verifier
(code checks + LLM check, one repair, then deterministic template fallback), and publishes Contract C
`Overlay`s with `ctx.publish_overlay`. Code computes every number; agents only explain. Nothing
unverified is published. Everything must work with **no model at all** (templates), with a
**stub model** (tests/CI), and with **Foundry** (live).

---

## 1. What already exists that we build on (do not rewrite these)

| Thing | Where | How we use it |
| --- | --- | --- |
| Contracts (frozen) | `shared/schemas/contracts.py` | `Moment` (B), `InsightBrief` (D), `Overlay` (C). Changing a field needs every owner's OK, and CI diff-checks `shared/schemas/json`. |
| Plugin context | `backend/api/plugins.py` | `register(ctx)`, `ctx.publish_overlay()` (validates C), `ctx.spawn()` for slow work, `ctx.budget`, `ctx.demo`, `ctx.library`, `ctx.on_reset`. |
| Analytics hooks | `backend/analytics/plugin.py` | `ctx.analytics.subscribe(cb)` → `cb(moment, state)` after every **published** moment (seek bursts are not re-published, so no duplicate agent runs). `ctx.analytics.snapshot(match_id)` = live stats. |
| Evidence engine | `backend/analytics/evidence.py` `MatchEvidence(meta, events, frames)` | `.evidence(moment_id)`, `.state_at(at_s)`, `.recent_events(at_s, window_s, team_id, types)`, `.player_stats(player_id, at_s)`, `.baseline(metric, window_s, at_s, team_id)`. These are our 5 MCP tools 1:1. |
| Evidence REST | `docs/OWNER_B.md` | same 5 functions over HTTP (`/api/matches/{id}/evidence/{moment_id}` etc.). |
| Token budget | `backend/services/budget.py` | `await ctx.budget.try_reserve(n)` before calls, `await ctx.budget.settle(n, actual)` after. Default cap 200k/day (`LIVE_MODE_DAILY_TOKEN_CAP`). |
| Templates | `backend/api/template_plugin.py` | `goal_overlays(moment, names)`, `red_card_overlays(...)`, `_Names(meta)`. Analytics goal moments carry the same fact keys (`scorer_id, minute, home_score, away_score, passes_in_move, shot_speed_kmh, shot_distance_m, assist_id`), so these work on `mom_00x` goals directly. Only goal + red card exist — **we must add templates for the other 7 types.** |
| Demo cache | `backend/api/demo.py` | `ctx.demo.bundles[...]` / `DemoBundle.overlays_for(moment_id, persona, language)`; rebuilt with `python -m backend.cli build-demo --all`. |
| Cosmos writer | `backend/analytics/store.py` | `get_store().enqueue("briefs", {...})` (also `overlays`, `audit`), partition `/match_id`. No-op when `COSMOS_ENDPOINT` unset. |
| Eval set | `evals/moments_eval.jsonl` | 107 moments (35 in `match_001`, all importance ≥ 0.5), each with facts, names (EN/AR), state, expected numbers. |

**Demo match moments the agents will see (`match_001`):** goals 12:06, 31:04, 49:02, 63:03 (Hassan Nour
`nil_10`, 104 km/h); Delta press 20:08; Nile press 58:10 (PPDA 1.8 vs 4.3); control→chaos 81:09; Delta
big chance 86:07; rhythm → frantic 87:47. Types: goal, red_card, big_chance, momentum_shift,
pressing_shift, control_to_chaos, killer_pass, rhythm_change, player_milestone (milestones < 0.5 are
template-only tags — agents skip them).

**Overlay rules the validator enforces (Contract C):** persona ∈ beginner/tactical/player/club/metric;
`dir` rtl for Arabic; headline ≤ 60, body ≤ 160; template_id ∈ lower_third/stat_card/player_tag/score_bug_note;
slot ∈ lower_third/top_left/top_right/pitch/side_panel; priority 1–5; ttl 1–60; `show_at_s` =
moment `game_clock_s`; ≥ 1 real evidence id; status approved/rejected/fallback; source agent/template;
Player persona puts the player in `fields.player_id`; use `name_ar` from metadata for Arabic names.

---

## 2. Decisions made up front (to finish today)

1. **Model access behind one interface.** `backend/agents/llm.py` defines `ModelClient.complete(system, user, json_schema?) -> (text, tokens)` with three implementations: `StubModel` (deterministic, for tests/CI), `FoundryModel` (Agent Framework / Foundry), and "none" (forces templates). Chosen by `AGENT_MODE=stub|foundry|off`. CI never touches Azure.
2. **Agent Framework is the orchestrator, not the dependency of every test.** The workflow is built with Agent Framework's code-based workflow builder (the plan forbids the portal designer, which retires Dec 1, 2026). Each step is also a plain async function so tests can run the graph without the framework if the import fails. Copy imports from the **current** official samples — the package is `agent-framework-foundry` (1.x) and names have moved between versions.
3. **MCP runs in-process with the API** (mounted at `/mcp`, Streamable HTTP, key in `MCP_API_KEY`) instead of a separate Container App. The handoff explicitly allows this and it removes a deploy step for Owner A. The tools wrap `MatchEvidence` directly (no HTTP hop to ourselves). Keep `python -m backend.agents.mcp_server` as a standalone entry point too, so we can split it out later.
4. **Analyst gets the evidence pre-fetched** (`get_moment_evidence` result is in its prompt) and may make at most **2 extra tool calls**. This is what keeps it inside 2.5 s.
5. **Templates for all 9 moment types × 3 personas × EN/AR exist before any LLM code.** They are the Verifier's fallback, the "Foundry failed" plan, and the over-budget plan.
6. **Personas for MUST:** beginner, tactical, player × en, ar. `club` is SHOULD (Phase 8). `metric` is COULD.
7. **We react only to analytics moments** (`mom_001+`). When our goal overlays are live, Owner A drops `backend.api.template_plugin:register` so goals are not shown twice.
8. **Plugin order matters:** `PIPELINE_PLUGINS=backend.analytics.plugin:register,backend.agents.plugin:register` (ours after analytics, because we call `ctx.analytics.subscribe` at register time).

---

## 3. Target layout

```text
backend/agents/
  __init__.py
  config.py          env: AGENT_MODE, FOUNDRY_PROJECT_ENDPOINT, FOUNDRY_MODEL_FAST/STRONG, MCP_API_KEY, deadlines
  llm.py             ModelClient: StubModel, FoundryModel; token counting
  names.py           allowlist of player/team names (EN + AR) from MatchMetadata
  templates.py       deterministic overlays for all 9 moment types (reuses template_plugin for goal/red card)
  producer.py        air plan: which personas/langs/slot/priority; hard caps in code
  analyst.py         Moment -> InsightBrief (Contract D) using evidence + MCP tools
  writers.py         InsightBrief + persona card + language -> draft Overlay (concurrent)
  verifier.py        code checks + LLM check -> Verdict(approved|rejected, reason_code)
  workflow.py        Agent Framework graph: producer -> analyst -> writers -> verifier -> repair/fallback
  cache.py           (match_id, moment_id, persona, language) -> Overlay; memory + Cosmos + demo bundle
  telemetry.py       OpenTelemetry -> Application Insights; trace_id onto every overlay
  breakit.py         adversarial draft for POST /api/demo/break-it
  mcp_server.py      5 read-only tools over MatchEvidence; FastMCP Streamable HTTP; ASGI app for /mcp
  plugin.py          register(ctx)
  prompts/           analyst_v1.md, writer_beginner_v1.md, writer_tactical_v1.md, writer_player_v1.md,
                     writer_club_v1.md, verifier_v1.md, jargon_en.txt, jargon_ar.txt
tests/test_agents_verifier.py, test_agents_templates.py, test_agents_workflow.py, test_agents_mcp.py
evals/numeric_faithfulness.py (if Owner B hasn't added it), evals/run_agent_eval.py
docs/OWNER_C.md
```

---

## 4. Build phases — one Codex task each

Each phase = one Codex task, one branch, `pytest -q` green, `python -m pyflakes backend shared tests` clean,
then merge. Do them in order; don't start a phase until the previous one is merged.

### Phase 0 — Foundry check (you, by hand, first) — *overdue since Oct 23*

Not a Codex task — needs your Azure login.

1. In the Azure portal / `az`, try to create a Foundry resource + project `everyfan-ai`. Try **uaenorth** first (team region); if models or Foundry aren't offered there on the student subscription, try the region Owner B used (**italynorth**) or another region your subscription allows. A different region from the API is fine for model calls.
2. Deploy two models: a small fast one (writers, Producer) and a stronger one (Analyst, Verifier LLM check). Write down the deployment names.
3. Get one reply from Python (`az login`, then the quickstart from the current Foundry docs).
4. **Send the team a yes/no right away.** If no: we ship `AGENT_MODE=off` live + agent overlays pre-generated on a teammate's machine that *does* have access (or with the stub), and say so honestly in the README.

### Phase 1 — Scaffold + templates (Codex)

**Prompt for Codex:**
> Create `backend/agents/` per `OWNER_C_PLAN.md` §3 with `config.py`, `names.py`, `templates.py`, `llm.py`
> (StubModel only for now), and `plugin.py`. `plugin.register(ctx)` subscribes to `ctx.analytics.subscribe`;
> for each moment with importance ≥ 0.5 it spawns a task that publishes **template** overlays (for now) via
> `ctx.publish_overlay`. `templates.py` must produce valid Contract C overlays for every moment type in
> `MomentType` for personas beginner, tactical, player and languages en, ar — reuse `goal_overlays` and
> `red_card_overlays` from `backend/api/template_plugin.py`, and write new EN + AR templates for big_chance,
> momentum_shift, pressing_shift, control_to_chaos, killer_pass, rhythm_change using only numbers from
> `moment.verified_facts` (see fact keys in `evals/moments_eval.jsonl`). Use `name_ar` from metadata for Arabic.
> `overlay_id = f"ov_{moment_id}_{persona}_{lang}"`, `source="template"`, `verification_status="fallback"`,
> `show_at_s = moment.game_clock_s`, player persona sets `fields.player_id` and is skipped when the moment has
> no player. Add `tests/test_agents_templates.py`: every moment in `evals/moments_eval.jsonl` yields valid
> overlays for all persona×lang combos; headline ≤ 60, body ≤ 160; Arabic overlays have dir=rtl.
> Do not edit Owner A or Owner B files.

**Done when:** `PIPELINE_PLUGINS=backend.analytics.plugin:register,backend.agents.plugin:register python -m backend.cli serve`
streams template overlays for every agent-worthy moment of `match_001`. **This alone is a shippable fallback.**

### Phase 2 — Verifier + Break-it (Codex)

**Prompt:**
> Implement `backend/agents/verifier.py` with
> `verify(draft: dict, brief: InsightBrief, moment: Moment, names: NameAllowlist, persona: str) -> Verdict`
> where `Verdict = {status: "approved"|"rejected", reason_code: str|None, detail: str}`.
> Code checks, in this order, each with its reason code:
> 1. Schema: draft validates as `Overlay`; headline ≤ 60, body ≤ 160 → `TOO_LONG` (schema errors also `TOO_LONG`/`SCHEMA`).
> 2. Numbers: normalize Arabic-Indic digits (٠-٩, ۰-۹) and the Arabic decimal separator `٫` to ASCII, extract every
>    number from headline+body; each must match a value in `brief.facts` ∪ `moment.verified_facts` ∪ derived allowed
>    values (current score, display minute) within rounding (abs ≤ 0.05 for decimals, exact for ints, and
>    percentage/round-to-int equivalence) → `NUMBER_NOT_IN_EVIDENCE`.
> 3. Entities: every capitalised player/team name (EN) or known Arabic name must be in the allowlist built from
>    metadata (`name`, `short_name`, `name_ar`) → `UNKNOWN_ENTITY`.
> 4. Evidence ids ⊆ brief ids → `BAD_EVIDENCE_ID`.
> 5. Persona rules: beginner has no unexplained term from `prompts/jargon_en.txt` / `jargon_ar.txt` (explained = the
>    term is followed by "—", "means", "called", or Arabic equivalents); player persona mentions the focus player → `TONE`
>    (or `PERSONA_RULE` if we add it — do not change contracts).
> 6. Optional LLM check (only when a ModelClient is passed): asks the strong model whether any causal claim is not
>    supported by the brief or the tone is disrespectful → `UNSUPPORTED_CAUSALITY` / `TONE`. Skipped in stub mode.
> Also `backend/agents/breakit.py`: `make_adversarial_draft(overlay: dict) -> dict` that replaces one number in the
> body with an invented one, and `async def run_break_it(match_id, moment_id, persona, lang) -> dict` that returns
> `{draft, verdict, repaired_or_fallback_overlay}`. Tests in `tests/test_agents_verifier.py`: invented number rejected
> with NUMBER_NOT_IN_EVIDENCE (EN and AR with Arabic-Indic digits); a correct template overlay is approved for every
> moment in the eval set; unknown name rejected; too-long rejected.

**Then message Owner A** the Break-it signature: `await run_break_it(match_id, moment_id, persona, lang) -> dict` (default
moment = Hassan Nour's goal `mom_` at 63:03 in `match_001`, persona `tactical`, lang `en`). They expose `POST /api/demo/break-it`.

### Phase 3 — MCP server (Codex)

**Prompt:**
> Implement `backend/agents/mcp_server.py` using the official `mcp` Python SDK (FastMCP) with Streamable HTTP.
> Five read-only tools, each a thin wrapper over `backend.analytics.evidence.MatchEvidence` loaded via the match
> library: `get_match_state(match_id, at_s)`, `get_recent_events(match_id, at_s, window_s, team_id=None)`,
> `get_player_statistics(match_id, player_id, at_s=None)`, `get_moment_evidence(match_id, moment_id)`,
> `compare_to_baseline(match_id, metric, window_s, at_s, team_id=None)` (metric enum from docs/OWNER_B.md).
> Inputs validated, results JSON, at most 50 events returned. Require header `x-api-key == MCP_API_KEY` when the key is
> set. Expose `mcp_asgi_app()` so Owner A can mount it at `/mcp` with one guarded try/except in `backend/api/main.py`
> (same pattern Owner B used), and `python -m backend.agents.mcp_server --port 8001` for standalone. Also provide an
> in-process `EvidenceTools` class with the same five methods so the Analyst can call them without a network hop.
> Tests: each tool returns the same numbers as `MatchEvidence` for a moment in match_001; missing/wrong key → 401.

### Phase 4 — Analyst, writers, Producer (Codex)

**Prompt:**
> Implement `producer.py`, `analyst.py`, `writers.py` and `FoundryModel` in `llm.py`.
> **Producer** (code, no LLM required): input moment + per-persona air history; output a list of
> `(persona, lang, slot, template_id, priority, ttl)`. Rules: goals and red cards always air for all personas,
> priority 1; otherwise max one overlay per persona per 45 match-seconds; player persona only if the moment has a
> player; tactical gets `stat_card`/`side_panel`, beginner `lower_third`. Optional fast-LLM tie-break is OFF by default.
> **Analyst** (strong model): input moment + prefetched `get_moment_evidence` + `get_match_state`; may call up to 2 more
> tools from `EvidenceTools`/MCP; output a valid `InsightBrief`. `facts` must be a subset of numbers returned by tools —
> after the model replies, drop any fact key whose value is not in the tool results. Confidence high/medium/low.
> On any error or deadline, build the brief deterministically from `moment.verified_facts`.
> **Writers** (fast model, concurrent with `asyncio.gather`): one call per (persona, lang) with the persona style card
> from `prompts/writer_<persona>_v1.md`; return JSON `{headline, body, fields}`; we fill every other Overlay field in
> code (ids, evidence, show_at_s, dir, slot, priority, ttl, source="agent", model, prompt_version, trace_id).
> Arabic writers get Arabic names from metadata and must write Modern Standard Arabic, numbers allowed in Western digits.
> `FoundryModel` uses the current Agent Framework Foundry client (copy imports from the official samples; read
> `FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_MODEL_FAST`, `FOUNDRY_MODEL_STRONG`; auth with `DefaultAzureCredential`), returns
> text and total tokens. Write the prompt files. StubModel returns template text for writers and a fact-only brief
> for the Analyst, so all tests stay offline.

Persona style cards (put in the prompt files): **Beginner** — no jargon, explain exactly one term;
**Tactical** — metrics and comparison to match baseline; **Player** — always about the focus player;
**Club** — partisan for the chosen club, factual, respectful to the rival.

### Phase 5 — Workflow, repair loop, fallback, budget, cache (Codex)

**Prompt:**
> Implement `workflow.py` with the Agent Framework workflow builder (code-based, no portal designer):
> Producer → Analyst → writers (fan-out per plan item) → Verifier → publish, with a repair edge: on rejection send the
> draft back to the **same** writer with the reason code, once; second rejection, exception, or deadline → that item's
> template from `templates.py` with `verification_status="fallback"`, `source="template"`. Deadlines (configurable):
> Producer 0.5 s, Analyst 2.5 s, writers 2 s, Verifier 1 s, total 5.5 s from moment receipt. Before any model call,
> `await ctx.budget.try_reserve(est)`; if denied, use cached overlays (`ctx.demo` bundle `overlays_for`) else templates;
> always `settle` with real tokens. Cache by `(match_id, moment_id, persona, language)` in memory; write briefs to Cosmos
> `briefs`, approved overlays to `overlays`, and each verdict/repair/fallback to `audit` via `get_store().enqueue` (no-op
> without Cosmos). If the Agent Framework import fails, run the same steps as plain async functions (same results).
> Record per overlay: latency ms, attempts, reason codes. Wire into `plugin.py`: replace the Phase 1 template path with
> `ctx.spawn(run_workflow(moment, state))`. Tests (stub model): one goal → approved agent overlays for 3 personas × 2 langs;
> a stub writer that invents a number → repaired once then approved; one that always invents → template fallback;
> a slow stub → fallback within deadline; budget exhausted → no model calls.

**Done when (the plan's first milestone):** one event → moment → Analyst via MCP → writer → Verifier → overlay on
screen at the right second, locally, in `AGENT_MODE=foundry`.

### Phase 6 — Tracing (Codex)

> Add `telemetry.py`: configure `azure-monitor-opentelemetry` when `APPLICATIONINSIGHTS_CONNECTION_STRING` is set; one span
> per workflow run with child spans per agent and tool call; attributes moment_id, persona, lang, model, tokens, verdict,
> reason_code. Put the trace id on each overlay's `trace_id`. No-op without the env var. Enable Agent Framework's built-in
> OpenTelemetry if available.

Screenshot the trace in Foundry/App Insights for the README and video.

### Phase 7 — Ship to Azure + rebuild the demo (you + Owner A)

1. Merge to `main` with CI green.
2. Send Owner A (one message, as soon as Phase 5 works locally): plugin path, `AGENT_MODE=foundry`, `FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_MODEL_FAST`,
   `FOUNDRY_MODEL_STRONG`, `MCP_API_KEY` (privately, as a secret), and that MCP is mounted in-process at `/mcp`.
   Ask them to grant the API's managed identity the inference role on the Foundry resource
   (*Cognitive Services User* / *Azure AI User*) and to drop `backend.api.template_plugin:register`.
3. Rebuild the cached demo (the only time the demo costs tokens):
   ```powershell
   $env:PIPELINE_PLUGINS="backend.analytics.plugin:register,backend.agents.plugin:register"
   $env:AGENT_MODE="foundry"
   python -m backend.cli build-demo --all
   git add demo/*.bundle.json
   ```
   Spot-check the Arabic overlays with a native speaker before committing. Check `GET /api/health` → `demo_bundles`
   lists the agent plugins.

### Phase 8 — SHOULD items (after the demo is rebuilt)

In this order, cut from the bottom:
1. **Evals:** `evals/run_agent_eval.py` over `evals/moments_eval.jsonl` (≈30 moments × 3 personas × 2 langs): report raw
   writer numeric faithfulness *before* the Verifier and 100% *after* (the gap is the proof). Add Foundry evaluators
   (groundedness, relevance, fluency, coherence) via `azure-ai-evaluation` if quota allows. Save the table in `docs/OWNER_C.md`.
2. **Favorite Club persona** (`club`): writer card + template + verifier check that the rival is named respectfully.
3. **Recap agent:** end-of-match story per persona/lang built only from approved overlays; endpoint
   `GET /api/matches/{id}/recap` coordinated with Owner A.
4. `docs/OWNER_C.md`: agent roles, workflow diagram, MCP tools, reason codes, latency budget, eval table, Copilot/Codex usage.

---

## 5. Messages to send now

**To the team (now):** "Foundry in <region>: yes/no. Owner C plugin path will be
`backend.agents.plugin:register`, loaded after analytics. MCP will run inside the API at `/mcp`, no extra container."

**To Owner B:** "I'll write briefs myself via `get_store().enqueue('briefs', …)`. Please confirm the
numeric-faithfulness evaluator file name so I don't duplicate it." *(Also flag: `docs/OWNER_B.md` still says
Cosmos is in `uaenorth`; your message says Italy North.)*

**To Owner A:** Break-it signature (Phase 2), env vars + identity role (Phase 7), and the one-line mount of
`mcp_asgi_app()` at `/mcp`.

**To Owner D:** "Agent overlays use the same Contract C as the templates. Extra fields you can show: `source`
(agent/template), `verification_status`, `trace_id`, `model`, `prompt_version`. Latency readout for Tactical comes in
`fields.generated_ms` / `fields.budget_ms` (both numbers we add in code, ignored by the Verifier)."

---

## 6. If things go wrong

| Problem | Do this |
| --- | --- |
| No Foundry / no quota | Ship `AGENT_MODE=off` live (templates, still verified); generate agent overlays for the demo bundle wherever a model works; README states what is live. |
| Analyst too slow | Skip extra tool calls (prefetched evidence only); use the fast model for the Analyst. |
| Arabic writer quality poor | Keep Arabic on templates for tactical, agent only for beginner; native review before demo rebuild. |
| Agent Framework API mismatch | Plain-async fallback path already runs the same graph; document the version pinned. |
| Budget burned by judges | Demo mode is cached; live is capped by `ctx.budget`; templates after the cap. |

---

## 7. AGENTS.md (put at repo root so Codex follows the rules every task)

```markdown
# Rules for coding agents in this repo
- Python 3.12. Run `pytest -q` and `python -m pyflakes backend shared tests` before finishing; both must pass.
- Do not edit `shared/schemas/contracts.py` or `shared/schemas/json/*` (frozen contracts).
- Do not edit Owner A files (`backend/api/*`, `backend/simulator/*`, `backend/services/*`) or Owner B files
  (`backend/analytics/*`) except a single guarded try/except mount line in `backend/api/main.py` when asked.
- Owner C code lives in `backend/agents/`, tests in `tests/test_agents_*.py`.
- Tests never call Azure or a real model: use `AGENT_MODE=stub`.
- Every number shown to users comes from `moment.verified_facts` or the evidence tools; agents never compute numbers.
- Never commit `.env`, keys, tokens or `deployment/.admin-token`.
- Arabic overlays: dir="rtl", names from metadata `name_ar`.
- For Agent Framework / Foundry / MCP imports, follow the current official samples; pin versions in requirements.txt.
```
