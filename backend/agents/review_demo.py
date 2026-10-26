"""Export Arabic copy and recheck a demo against the original match evidence."""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from shared.schemas import Moment, Overlay
from backend.analytics.evidence import MatchEvidence
from backend.api.demo import DemoBundle, fingerprint

from .names import NameAllowlist
from .producer import produce
from .recap import Recap, RecapText, deterministic_recap, verify_recap
from .verifier import DIGITS, DISPLAY_NUMBER, brief_from_moment, numeric_values, number_supported, verify


def _content_draft(raw):
    # Workflow.cached uses the same separation: these are code-owned diagnostics.
    return {**raw, 'fields': {k: v for k, v in raw['fields'].items() if k not in {'reason_codes', 'attempts'}}}


def _name_spelling(text):
    # Accept diacritic/ya spelling repairs of the same name, never a different entity.
    return re.sub(r'[\u064b-\u065f\u0670]', '', text).replace('ى', 'ي')


def review_bundle(path, match, *, require_complete=True):
    path = Path(path)
    bundle = DemoBundle.load(path)
    evidence = MatchEvidence(match.metadata, match.events, match.frames)
    moments = {m.moment_id: m for m in evidence.moments}
    names = NameAllowlist(match.metadata)
    errors, arabic, seen = [], [], set()
    if bundle.fingerprint != fingerprint(match.events) or bundle.match_id != match.metadata.match_id:
        errors.append('Bundle does not match the current simulation')
    recorded = {i['data']['moment_id']: Moment.model_validate(i['data']) for i in bundle.items if i['type'] == 'moment'}
    if require_complete and set(recorded) != set(moments):
        errors.append('Incomplete recorded moment set')
    for mid, moment in recorded.items():
        if mid not in moments or moment != moments[mid]:
            errors.append(f'{mid}: recorded facts differ from the evidence engine')
    for item in bundle.items:
        if item['type'] != 'overlay':
            continue
        overlay = Overlay.model_validate(item['data'])
        moment = moments.get(overlay.moment_id)
        if overlay.overlay_id in seen:
            errors.append(f'{overlay.overlay_id}: duplicate ID')
        seen.add(overlay.overlay_id)
        if moment is None:
            errors.append(f'{overlay.overlay_id}: unknown moment')
            continue
        verdict = verify(_content_draft(overlay.model_dump()), brief_from_moment(moment), moment, names, overlay.persona)
        if verdict.status != 'approved':
            errors.append(f'{overlay.overlay_id}: {verdict.reason_code}: {verdict.detail}')
        allowed = numeric_values(moment.verified_facts) + [moment.game_clock_s // 60 + 1]
        if any(not number_supported(m.group(), allowed) for m in DISPLAY_NUMBER.finditer(
                (overlay.headline + '\n' + overlay.body).translate(DIGITS))):
            errors.append(f'{overlay.overlay_id}: NUMBER_NOT_IN_EVIDENCE in display copy')
        if item['game_time_s'] != overlay.show_at_s:
            errors.append(f'{overlay.overlay_id}: inconsistent playback time')
        if ((overlay.source, overlay.verification_status) not in {('agent', 'approved'), ('template', 'fallback')}
                or (overlay.source == 'agent' and overlay.model in {None, 'stub'})):
            errors.append(f'{overlay.overlay_id}: invalid provenance')
        if overlay.language == 'ar':
            arabic.append({'id': overlay.overlay_id, 'minute': overlay.show_at_s // 60 + 1,
                           'persona': overlay.persona, 'club_id': overlay.fields.get('club_id'),
                           'source': overlay.source, 'headline': overlay.headline, 'body': overlay.body})
    if require_complete:
        history, expected = {}, set()
        for moment in evidence.moments:
            if moment.importance < .5:
                continue
            for item in produce(moment, history, tuple(names.teams)):
                identity = f'club_{item.club_id}_{item.language}' if item.club_id else f'{item.persona}_{item.language}'
                expected.add(f'ov_{moment.moment_id}_{identity}')
        if seen != expected:
            errors.append(f'Incomplete overlay set: missing={sorted(expected - seen)}, extra={sorted(seen - expected)}')
        if len(bundle.recaps) != 10:
            errors.append(f'Incomplete recap set: {len(bundle.recaps)}/10')
    for key, raw in bundle.recaps.items():
        recap = Recap.model_validate({k: v for k, v in raw.items() if k not in {'feed_source', 'run_id'}})
        base = deterministic_recap(match.metadata, bundle.overlays(), persona=recap.persona,
                                   language=recap.language, club_id=recap.club_id, until_s=recap.until_s)
        reason = verify_recap(RecapText(headline=recap.headline, body=recap.body), base, names)
        identity = f'{recap.persona}|{recap.language}|{recap.club_id or ""}'
        if (reason or key != identity or recap.match_id != base.match_id or recap.dir != base.dir
                or recap.facts != base.facts or recap.final != base.final
                or recap.key_moments != base.key_moments or recap.evidence_overlay_ids != base.evidence_overlay_ids):
            errors.append(f'{key}: recap evidence mismatch ({reason})')
        if recap.language == 'ar':
            arabic.append({'id': key, 'minute': 'recap', 'persona': recap.persona, 'club_id': recap.club_id,
                           'source': recap.source, 'headline': recap.headline, 'body': recap.body})
    export = path.with_name('arabic_review.txt')
    export.write_text('\n\n'.join(f"[{r['id']}] minute={r['minute']} persona={r['persona']} club={r['club_id']} source={r['source']}\n"
                                   f"{r['headline']}\n{r['body']}" for r in arabic) + '\n', encoding='utf-8')
    path.with_name('arabic_review.json').write_text(json.dumps(arabic, ensure_ascii=False, indent=2), encoding='utf-8')
    report = {'valid': not errors, 'errors': errors, 'counts': bundle.counts(),
              'overlay_sources': bundle.overlay_sources(), 'recaps': len(bundle.recaps),
              'arabic_items': len(arabic), 'arabic_review': str(export)}
    path.with_name('verification-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def apply_arabic_edits(path, match, edits):
    """Apply text-only corrections atomically, preserving all numbers and names."""
    path = Path(path)
    raw = json.loads(path.read_text(encoding='utf-8'))
    names = NameAllowlist(match.metadata)
    moments = {m.moment_id: m for m in MatchEvidence(match.metadata, match.events, match.frames).moments}
    overlays = {i['data']['overlay_id']: i['data'] for i in raw['items'] if i['type'] == 'overlay'}
    targets = overlays | raw.get('recaps', {})
    audit = path.with_name('arabic_changes.json')
    changes = json.loads(audit.read_text(encoding='utf-8')) if audit.exists() else []
    for oid, fields in edits.items():
        if oid not in targets or targets[oid]['language'] != 'ar' or not fields or set(fields) - {'headline', 'body'}:
            raise ValueError(f'{oid}: edits must target Arabic headline/body only')
        original = targets[oid].copy()
        if all(original.get(k) == v for k, v in fields.items()):
            continue
        changed = original | fields
        before, after = (o['headline'] + '\n' + o['body'] for o in (original, changed))
        numbers = lambda text: Counter(m.group().strip() for m in DISPLAY_NUMBER.finditer(text.translate(DIGITS)))
        if numbers(before) != numbers(after):
            raise ValueError(f'{oid}: edits must preserve numbers')
        if any(_name_spelling(before).count(_name_spelling(name)) != _name_spelling(after).count(_name_spelling(name))
               for name in names.allowed):
            raise ValueError(f'{oid}: edits must preserve metadata names')
        if oid in overlays:
            moment = moments[original['moment_id']]
            verdict = verify(_content_draft(changed), brief_from_moment(moment), moment, names, original['persona'])
            if verdict.status != 'approved':
                raise ValueError(f'{oid}: {verdict.reason_code}')
        else:
            base = deterministic_recap(match.metadata, list(overlays.values()), persona=original['persona'],
                                       language='ar', club_id=original.get('club_id'), until_s=original['until_s'])
            reason = verify_recap(RecapText(headline=changed['headline'], body=changed['body']), base, names)
            if reason:
                raise ValueError(f'{oid}: {reason}')
        targets[oid].update(fields)
        changes.append({'id': oid, 'before': {k: original[k] for k in fields}, 'after': fields})
    # Recap evidence excerpts follow the reviewed overlay wording; IDs and facts stay fixed.
    for recap in raw.get('recaps', {}).values():
        for moment in recap['key_moments']:
            if moment['overlay_id'] in edits:
                moment.update(edits[moment['overlay_id']])
    backup = path.with_name('match_001.pre-arabic-review.bundle.json')
    if not backup.exists():
        backup.write_bytes(path.read_bytes())
    temporary = path.with_suffix('.reviewed.tmp')
    temporary.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding='utf-8')
    temporary.replace(path)
    audit.write_text(json.dumps(changes, ensure_ascii=False, indent=2), encoding='utf-8')
    return changes


def main():
    import asyncio
    from backend.api.library import MatchLibrary
    from backend.api.settings import Settings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    args = parser.parse_args()

    async def run():
        match = await MatchLibrary(Settings().data_dir).get('match_001')
        report = review_bundle(args.bundle, match)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return int(not report['valid'])
    return asyncio.run(run())


if __name__ == '__main__':
    raise SystemExit(main())
