import type {
  Metadata,
  MatchState,
  Moment,
  Overlay,
  Preferences,
  StreamMessage,
  Tracking,
} from './types';

export interface StreamState {
  runId: string | null;
  clock: number;
  metadata: Metadata | null;
  frame: Tracking | null;
  matchState: MatchState | null;
  overlays: Overlay[];
  moments: Moment[];
  events: string[];
  playback: 'idle' | 'playing' | 'paused' | 'finished';
  speed: number;
}
export const initialStream = (): StreamState => ({
  runId: null,
  clock: 0,
  metadata: null,
  frame: null,
  matchState: null,
  overlays: [],
  moments: [],
  events: [],
  playback: 'idle',
  speed: 20,
});

export function reduceStream(state: StreamState, message: StreamMessage): StreamState {
  if (message.type === 'reset')
    return {
      ...initialStream(),
      runId: message.run_id,
      speed: state.speed,
      playback: state.playback,
    };
  if (state.runId && message.run_id !== state.runId && message.type !== 'hello') return state;
  switch (message.type) {
    case 'hello':
      return { ...state, runId: message.run_id };
    case 'metadata':
      return { ...state, metadata: message.data };
    case 'state':
      return {
        ...state,
        matchState: message.data,
        clock: Math.max(state.clock, message.game_time_s),
      };
    case 'tracking':
      return { ...state, frame: message.data, clock: Math.max(state.clock, message.game_time_s) };
    case 'overlay': {
      const o = message.data;
      const verified =
        (o.source === 'agent' && o.verification_status === 'approved') ||
        (o.source === 'template' && o.verification_status === 'fallback');
      if (!verified || state.overlays.some((x) => x.overlay_id === o.overlay_id)) return state;
      return { ...state, overlays: [...state.overlays, o] };
    }
    case 'moment':
      return state.moments.some((m) => m.moment_id === message.data.moment_id)
        ? state
        : { ...state, moments: [...state.moments, message.data] };
    case 'event':
      return state.events.includes(message.data.event_id)
        ? state
        : { ...state, events: [...state.events, message.data.event_id] };
    case 'replay':
      return {
        ...state,
        speed: message.data.speed,
        playback:
          message.data.state === 'finished'
            ? 'finished'
            : message.data.state === 'paused'
              ? 'paused'
              : 'playing',
      };
    case 'control':
      return {
        ...state,
        speed: message.data.speed ?? state.speed,
        playback:
          message.data.action === 'run_finished'
            ? 'finished'
            : message.data.action === 'paused'
              ? 'paused'
              : 'playing',
      };
  }
}

export function matchesPreference(o: Overlay, p: Preferences): boolean {
  return (
    o.persona === p.persona &&
    o.language === p.language &&
    (p.persona !== 'club' || o.fields.club_id === p.club) &&
    (p.persona !== 'player' || o.fields.player_id === p.player)
  );
}

export function activeOverlays(state: StreamState, preference: Preferences): Overlay[] {
  const chosen = new Map<string, Overlay>();
  for (const overlay of state.overlays) {
    if (
      !matchesPreference(overlay, preference) ||
      overlay.show_at_s > state.clock ||
      state.clock >= overlay.show_at_s + overlay.ttl_s
    )
      continue;
    const previous = chosen.get(overlay.slot);
    if (
      !previous ||
      overlay.priority < previous.priority ||
      (overlay.priority === previous.priority && overlay.show_at_s > previous.show_at_s)
    )
      chosen.set(overlay.slot, overlay);
  }
  return [...chosen.values()];
}

export function parseMessage(raw: string): StreamMessage | null {
  const value: unknown = JSON.parse(raw);
  if (
    !value ||
    typeof value !== 'object' ||
    !('type' in value) ||
    !('data' in value) ||
    !('run_id' in value) ||
    typeof value.run_id !== 'string' ||
    !('game_time_s' in value) ||
    typeof value.game_time_s !== 'number' ||
    !Number.isFinite(value.game_time_s)
  )
    return null;
  if (
    ![
      'hello',
      'reset',
      'metadata',
      'state',
      'tracking',
      'overlay',
      'moment',
      'event',
      'control',
      'replay',
    ].includes(String(value.type))
  )
    return null;
  // The adapter consumes the server's frozen, validated envelope. Unknown kinds never enter UI state.
  return value as StreamMessage;
}
