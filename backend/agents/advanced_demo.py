"""Offline advanced recordings. Existing bundle events/overlays remain untouched."""

import asyncio
import json
import hashlib

from backend.analytics.evidence import MatchEvidence
from backend.analytics.reference_pool import reference_pool
from backend.api.demo import DemoBundle
from backend.api.library import MatchLibrary
from backend.api.settings import ROOT
from backend.services.budget import DailyTokenBudget
from .ask import AskRequest, answer_question
from .coach import coach_facts, coach_notes
from .config import AgentConfig
from .llm import StubModel
from .mcp_server import EvidenceTools
from .reports import match_report
from .templates import ALL_PERSONAS, LANGUAGES

QUESTIONS = {
    "en": ["Who is on top?", "Compare the teams", "How is my player performing?", "Explain the pressing", "What changed tactically?", "What happened recently?"],
    "ar": ["من المتفوق الآن؟", "قارن الفريقين", "كيف يؤدي لاعبي؟", "اشرح الضغط", "ما التغير التكتيكي؟", "ماذا حدث مؤخراً؟"],
}


def pack(value):
    """Content-address repeated evidence/facts, without changing endpoint responses."""
    objects = {}

    def visit(item):
        if isinstance(item, list):
            result = [visit(v) for v in item]
        elif isinstance(item, dict):
            result = {key: visit(v) for key, v in item.items()}
        else:
            return item
        encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(encoded) < 800:
            return result
        key = hashlib.sha256(encoded.encode()).hexdigest()[:24]
        objects.setdefault(key, result)
        return {"$ref": key}
    root = visit(value)
    return {"packed": root, "objects": objects}


def unpack(value):
    if "packed" not in value:
        return value
    cache = {}

    def visit(item):
        if isinstance(item, list):
            return [visit(v) for v in item]
        if isinstance(item, dict):
            if set(item) == {"$ref"}:
                key = item["$ref"]
                if key not in cache:
                    cache[key] = visit(value["objects"][key])
                return cache[key]
            return {key: visit(v) for key, v in item.items()}
        return item
    return visit(value["packed"])


async def record_advanced(out=ROOT / "demo", mode="stub"):
    # This build never reads Azure credentials or constructs a network model.
    if mode not in {"stub", "off"}:
        raise ValueError("Advanced offline recording supports stub/off only; live model use is explicit through live endpoints.")
    library, cfg = MatchLibrary(ROOT / "data", max_loaded=1), AgentConfig(mode=mode)
    model = StubModel() if mode == "stub" else None
    budget = DailyTokenBudget(50_000_000)
    counts = []
    for item in library.catalog():
        mid = item["match_id"]
        match = await library.get(mid)
        ev = await asyncio.to_thread(MatchEvidence, match.metadata, match.events, match.frames)
        reference = await reference_pool(library, mid)
        tools = EvidenceTools(library)
        tools._cache[mid] = ev
        await asyncio.to_thread(coach_facts, ev, cfg)
        bundle = DemoBundle.load(out / f"{mid}.bundle.json")
        data = {"version": 1, "recording_mode": mode, "arabic_review": "pending_native_review", "reports": {}, "coach_notes": {}, "questions": []}
        for persona in ALL_PERSONAS:
            for language in LANGUAGES:
                clubs = [match.metadata.home.team_id, match.metadata.away.team_id] if persona == "club" else [None]
                for club in clubs:
                    key = f"{persona}|{language}|{club or ''}"
                    data["coach_notes"][key] = await coach_notes(ev, 5400, language, persona, model=model, budget=budget, config=cfg)
                    for phase, at in (("half", 2700), ("full", 5400)):
                        data["reports"][f"{phase}|{key}"] = await match_report(ev, phase, at, persona, language, club, reference=reference, model=model, budget=budget, config=cfg, published_overlays=bundle.overlays())
                player = next(p.player_id for p in match.metadata.home.players if p.position == "ST" and p.starter)
                for at in (1200, 3600, 5280):
                    for question in QUESTIONS[language]:
                        body = AskRequest(question=question, at_s=at, persona=persona, language=language,
                                          player_id=player, club_id=match.metadata.home.team_id)
                        answer = await answer_question(ev, body, tools, model=model, budget=budget, config=cfg)
                        data["questions"].append({"request": body.model_dump(), "response": answer})
        # StubModel returns the supplied template. Do not badge offline fixtures as
        # paid/model-authored AI prose when judges play the committed demo.
        records = [*data["reports"].values(), *[q["response"] for q in data["questions"]],
                   *[n for notes in data["coach_notes"].values() for n in notes]]
        for result in records:
            result.update(source="template", verification_status="fallback", recording_mode=mode)
        bundle.advanced = pack(data)
        bundle.save(out)
        counts.append({"match_id": mid, "reports": len(data["reports"]), "coach_variants": len(data["coach_notes"]), "questions": len(data["questions"])})
        print(json.dumps(counts[-1]), flush=True)
    return counts
