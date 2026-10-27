# English pitch and submission package

## Pitch

EveryFan turns one synthetic football match into personalised, evidence-backed
broadcast stories. A beginner gets a plain-language explanation, a tactical fan
gets context, a player fan follows their favourite, and an Arabic-speaking viewer
gets a complete RTL experience. The numbers stay tied to the same measured facts.

Built for the Multi-Agent category, EveryFan separates Producer, Analyst, persona
writers, Verifier and Recap responsibilities. Microsoft Agent Framework invokes
Foundry deployments; the Analyst can use five read-only MCP evidence tools.
The integrated backend supports Azure Event Hubs, Cosmos DB and Container Apps.
The Verifier checks contracts, entities, numeric evidence and causality; one
repair attempt is followed by a checked template when necessary. The recorded
demo works without a model call, and Break it demonstrates rejection visibly.

The measured 30-moment Foundry evaluation reports 91.0% raw numeric faithfulness
and 100.0% published numeric faithfulness across 236 outputs, including 87
template fallbacks. These are numeric-token measurements, not overall quality
scores. Model-based quality judges and trace ingestion screenshots were not
verified. The React viewer is implemented; public Static Web Apps hosting awaits
a subscription permitting its supported regions and the backend CORS update.

## Demo recording

The reproducible recording script is `frontend/scripts/record-demo.mjs`.
Run it with the local API in **off** mode and the Vite viewer already running:

```powershell
cd frontend
node scripts/record-demo.mjs
.\scripts\narrate-demo.ps1
python scripts/render-demo.py --ffmpeg '<path-to-local-ffmpeg>' --directory ../.venv/handoff/owner-d/delivery
```

It creates a 1920×1080 local draft and a chapter/narration manifest under
`.venv/handoff/owner-d/delivery/`. The first pass uses real recorded agent output
served by the off-mode API, plus an explicitly explanatory workflow slide.
It does not impersonate a live Foundry trace. English voice-over uses Windows
Zira locally; that does not implement or claim Azure AI Speech narration.

The produced `everyfan-demo.mp4` is exactly 1:55, H.264 at 30 fps with AAC audio
and burned English captions. `everyfan.srt` and `everyfan-raw.webm` are retained
beside it. Sample frames were inspected at 8, 50, 76, 95 and 107 seconds. The
video is a local review draft; it has not been uploaded or submitted.

| Time | Screen and narration purpose |
| --- | --- |
| 0–12 s | Same goal, four perspectives including Arabic |
| 12–25 s | Product, fictional data and zero-model-cost recorded demo |
| 25–45 s | Tracking, player focus, measured indices and replay controls |
| 45–70 s | Explanatory agent workflow and repair/fallback responsibilities |
| 70–85 s | Real Break it rejection and checked replacement |
| 85–100 s | Evidence panel; accurately scoped evaluation results |
| 100–115 s | Recap, reusable feed/schema and invitation to try |

Keep the raw WebM and narration as backup. The local MP4/captions are review
artifacts. Re-record against the public deployed site before claiming it works
exactly as shown from another device/network. No copyrighted music, real team
logos, real players or match footage are used.

## Account-holder completion

- Resolve the Azure region/subscription issue in [OWNER_D.md](OWNER_D.md), deploy
  the exact tested artifact and append its origin to backend CORS.
- Verify HTTPS/WSS, demo, Break it, Arabic, recap and feed in a private window on
  another device and mobile data. Obtain native review of the new Arabic shell.
- Add the final live URL to README/testing notes. Keep public access available
  for the judging period; check the current competition rules before submitting.
- Upload the reviewed video to the account holder's YouTube/Vimeo account; verify
  public playback while logged out. No video has been uploaded by this change.
- Complete the final entry with the English pitch, public repository, public
  video, live URL and [testing guide](TESTING_GUIDE.md). The eligible submitter
  confirms rules, team details and submission; no entry has been submitted here.
- Do not claim unverified Application Insights traces, model-quality evaluator
  results, GitHub Copilot Agent Mode usage, or the optional roadmap features.

Roadmap: third language, Single Metric mode, Scenario Director, Azure AI Speech
narration and studio approval. The implementing assistant here was Codex; any
separate Copilot usage must be described by the team from its actual work.
