# Rules for coding agents in this repo

- Python 3.12. Run `python -m pytest -q` and `python -m pyflakes backend shared tests` before finishing; both must pass.
- Use the project virtual environment. This checkout's Python 3.12 executable is `.venv/py312/Scripts/python.exe`.
- Do not edit `shared/schemas/contracts.py` or `shared/schemas/json/*` (frozen contracts).
- Owner C code lives in `backend/agents/`, tests in `tests/test_agents_*.py`, docs in `docs/OWNER_C*.md`.
- Do not edit Owner A files (`backend/api/*`, `backend/simulator/*`, `backend/services/*`) or Owner B files (`backend/analytics/*`), except the guarded MCP mount in `backend/api/main.py` when that phase is requested.
- Tests never call Azure or a real model. Use off mode for templates and `AGENT_MODE=stub` for model workflow tests.
- Every displayed number must come from verified facts or evidence tools; agents never compute numbers.
- Never commit `.env`, `.env.azure`, keys, tokens, or `deployment/.admin-token`.
- Arabic overlays use `dir="rtl"` and metadata `name_ar` for names.
- For Agent Framework, Foundry, and MCP imports, follow current official samples and pin added dependencies.
- Follow `docs/OWNER_C_PLAN.md` in phase order, with a separate branch and green checks per phase. The user explicitly authorized continuing locally without GitHub access: build each phase on the prior local commits and export patches for later team review/merge.
