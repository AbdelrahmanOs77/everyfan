# Rules for coding agents in this repo

- Python 3.12. Run `python -m pytest -q` and `python -m pyflakes backend shared tests` before finishing; both must pass.
- Use the project virtual environment. This checkout's Python 3.12 executable is `.venv/py312/Scripts/python.exe`.
- Do not edit `shared/schemas/contracts.py` or `shared/schemas/json/*` (frozen contracts).
- Owner C code lives in `backend/agents/`, tests in `tests/test_agents_*.py`, docs in `docs/OWNER_C*.md`.
- Do not edit Owner A files (`backend/api/*`, `backend/simulator/*`, `backend/services/*`) or Owner B files (`backend/analytics/*`) unless the task is cross-owner integration; record such changes in `docs/INTEGRATION.md`.
- The pipeline is `backend.analytics.plugin:register,backend.agents.plugin:register`; never also load `backend.api.template_plugin:register` (goals would air twice).
- Persona keys are (persona, language, club_id): Favorite Club overlays exist once per club.
- Tests never call Azure or a real model. Use off mode for templates and `AGENT_MODE=stub` for model workflow tests.
- Every displayed number must come from verified facts or evidence tools; agents never compute numbers.
- Never commit `.env`, `.env.azure`, keys, tokens, or `deployment/.admin-token`.
- Arabic overlays use `dir="rtl"` and metadata `name_ar` for names.
- For Agent Framework, Foundry, and MCP imports, follow current official samples and pin added dependencies.
- `docs/OWNER_C_PLAN.md` phases 1–8 are implemented; `docs/INTEGRATION.md` lists what remains for people.
- Before finishing also run `python -m evals.run_agent_eval --mode stub --inject 0.3 --quiet --no-write` (must report 100% published faithfulness).
