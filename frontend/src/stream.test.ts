import { describe, expect, it } from 'vitest';
import {
  activeOverlays,
  activeCommentary,
  initialStream,
  parseMessage,
  reduceStream,
} from './stream';
import type { Overlay, Preferences, StreamMessage } from './types';

const prefs: Preferences = {
  persona: 'tactical',
  language: 'en',
  player: 'nil_10',
  club: 'nile_fc',
};
const overlay: Overlay = {
  overlay_id: 'o1',
  moment_id: 'm1',
  match_id: 'match_001',
  persona: 'tactical',
  language: 'en',
  dir: 'ltr',
  slot: 'side_panel',
  priority: 2,
  headline: 'Verified moment',
  body: 'Evidence-backed copy.',
  fields: {},
  show_at_s: 100,
  ttl_s: 8,
  source: 'agent',
  verification_status: 'approved',
  evidence_event_ids: ['evt_00001'],
};
const message = (data: Overlay): StreamMessage => ({
  type: 'overlay',
  match_id: 'match_001',
  run_id: 'r1',
  game_time_s: 100,
  data,
});
const tick = (time: number): StreamMessage => ({
  type: 'state',
  match_id: 'match_001',
  run_id: 'r1',
  game_time_s: time,
  data: { score: { nile_fc: 1, delta_utd: 0 }, period: 1 },
});

describe('broadcast timing', () => {
  it('queues early overlays without advancing the picture clock, then expires by server time', () => {
    let s = reduceStream(initialStream(), tick(94));
    s = reduceStream(s, message(overlay));
    expect(s.clock).toBe(94);
    expect(activeOverlays(s, prefs)).toEqual([]);
    s = reduceStream(s, tick(100));
    expect(activeOverlays(s, prefs)).toEqual([overlay]);
    expect(activeOverlays(reduceStream(s, tick(108)), prefs)).toEqual([]);
  });
  it('does not resurrect expired overlays when a duplicate arrives', () => {
    let s = reduceStream(initialStream(), message(overlay));
    s = reduceStream(s, tick(109));
    s = reduceStream(s, message(overlay));
    expect(s.overlays).toHaveLength(1);
    expect(activeOverlays(s, prefs)).toEqual([]);
  });
  it('uses lower-number priority, preserving independent slots', () => {
    let s = reduceStream(initialStream(), tick(100));
    for (const o of [
      overlay,
      { ...overlay, overlay_id: 'winner', priority: 1 },
      { ...overlay, overlay_id: 'lower', slot: 'lower_third' as const },
    ])
      s = reduceStream(s, message(o));
    expect(activeOverlays(s, prefs).map((o) => o.overlay_id)).toEqual(['winner', 'lower']);
  });
  it('clears the complete picture on reset and ignores messages from the old run', () => {
    const s = reduceStream(reduceStream(initialStream(), message(overlay)), {
      type: 'reset',
      match_id: 'match_001',
      run_id: 'r2',
      game_time_s: 0,
      data: { reason: 'seek' },
    });
    expect(s.overlays).toEqual([]);
    expect(s.moments).toEqual([]);
    expect(s.frame).toBeNull();
    expect(reduceStream(s, message(overlay))).toBe(s);
  });
  it('filters club and player variants using metadata IDs', () => {
    let s = reduceStream(initialStream(), tick(100));
    s = reduceStream(s, message({ ...overlay, persona: 'club', fields: { club_id: 'delta_utd' } }));
    expect(activeOverlays(s, { ...prefs, persona: 'club' })).toEqual([]);
    expect(activeOverlays(s, { ...prefs, persona: 'club', club: 'delta_utd' })).toHaveLength(1);
    expect(activeOverlays(s, { ...prefs, language: 'ar' })).toEqual([]);
    s = reduceStream(
      s,
      message({
        ...overlay,
        overlay_id: 'player',
        persona: 'player',
        fields: { player_id: 'nil_10' },
      }),
    );
    expect(activeOverlays(s, { ...prefs, persona: 'player' })).toHaveLength(1);
    expect(activeOverlays(s, { ...prefs, persona: 'player', player: 'nil_09' })).toEqual([]);
  });
  it('never displays rejected output', () => {
    const s = reduceStream(
      reduceStream(initialStream(), tick(100)),
      message({ ...overlay, verification_status: 'rejected' }),
    );
    expect(activeOverlays(s, prefs)).toEqual([]);
  });
  it('ignores unknown envelopes and non-finite clocks', () => {
    expect(parseMessage('{"type":"surprise","data":{},"run_id":"r","game_time_s":1}')).toBeNull();
    expect(parseMessage('{"type":"state","data":{},"run_id":"r","game_time_s":null}')).toBeNull();
  });
});

describe('continuous match commentary', () => {
  const action = (id: string, seq: number, show: number): StreamMessage => ({
    type: 'event',
    match_id: 'match_001',
    run_id: 'r1',
    game_time_s: 10,
    data: {
      event_id: id,
      seq,
      type: 'pass',
      team_id: 'nile_fc',
      player_id: 'nil_06',
      receiver_id: 'nil_10',
    },
    commentary: { show_at_s: show, text: { en: 'A completed pass.', ar: 'تمريرة مكتملة.' } },
  });
  it('waits for completion without moving the picture clock and removes duplicates', () => {
    let s = reduceStream(initialStream(), tick(10));
    s = reduceStream(s, action('evt_00001', 1, 12.5));
    s = reduceStream(s, action('evt_00001', 1, 12.5));
    expect(s.clock).toBe(10);
    expect(activeCommentary(s)).toEqual([]);
    s = reduceStream(s, tick(12.5));
    expect(activeCommentary(s)).toHaveLength(1);
    expect(s.commentary).toHaveLength(1);
  });
  it('orders completed actions by their display time, then source sequence', () => {
    let s = reduceStream(initialStream(), tick(20));
    s = reduceStream(s, action('evt_00001', 1, 15));
    s = reduceStream(s, action('evt_00002', 2, 11));
    s = reduceStream(s, action('evt_00003', 3, 15));
    expect(activeCommentary(s).map((e) => e.event_id)).toEqual([
      'evt_00003',
      'evt_00001',
      'evt_00002',
    ]);
  });
  it('clears action history on seeks and ignores stale-run messages', () => {
    let s = reduceStream(initialStream(), action('evt_00001', 1, 10));
    s = reduceStream(s, {
      type: 'reset',
      match_id: 'match_001',
      run_id: 'r2',
      game_time_s: 0,
      data: { reason: 'seek' },
    });
    expect(s.commentary).toEqual([]);
    expect(reduceStream(s, action('evt_00002', 2, 11))).toBe(s);
  });
  it('supports older servers and ignores invalid annotations', () => {
    const old: StreamMessage = {
      type: 'event',
      match_id: 'match_001',
      run_id: 'r1',
      game_time_s: 10,
      data: { event_id: 'old', type: 'pass' },
    };
    expect(reduceStream(initialStream(), old).commentary).toEqual([]);
    expect(reduceStream(initialStream(), { ...action('bad', 1, NaN) }).commentary).toEqual([]);
  });
});
