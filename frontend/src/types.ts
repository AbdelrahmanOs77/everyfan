export type Language = 'en' | 'ar';
export type Persona = 'beginner' | 'tactical' | 'player' | 'club';
export type Fact = string | number | boolean | null;
export interface Player {
  player_id: string;
  team_id: string;
  name: string;
  name_ar?: string;
  short_name: string;
  shirt_number: number;
  position: string;
  starter: boolean;
}
export interface Team {
  team_id: string;
  name: string;
  name_ar?: string;
  short_name: string;
  primary_color: string;
  secondary_color: string;
  players: Player[];
}
export interface Metadata {
  match_id: string;
  scenario_id: string;
  competition: string;
  venue: string;
  pitch_length_m: number;
  pitch_width_m: number;
  match_duration_s: number;
  home: Team;
  away: Team;
}
export interface Overlay {
  overlay_id: string;
  moment_id: string;
  match_id: string;
  persona: Persona;
  language: Language;
  dir: 'ltr' | 'rtl';
  slot: 'lower_third' | 'side_panel' | 'pitch';
  priority: number;
  headline: string;
  body: string;
  fields: Record<string, Fact>;
  show_at_s: number;
  ttl_s: number;
  source: 'agent' | 'template';
  verification_status: 'approved' | 'fallback' | 'rejected';
  trace_id?: string | null;
  evidence_event_ids: string[];
}
export interface Moment {
  moment_id: string;
  match_id: string;
  game_clock_s: number;
  type: string;
  importance: number;
  player_id?: string | null;
  team_id?: string | null;
  verified_facts: Record<string, Fact>;
  rule_id: string;
  evidence_event_ids: string[];
}
export interface Tracking {
  frame: number;
  period: number;
  ball: [number, number];
  players: [string, number, number][];
}
export interface MatchState {
  score: Record<string, number>;
  period?: number;
  clock_s?: number;
  players_on_pitch?: Record<string, number>;
  sent_off?: string[];
}
export interface TeamStats {
  control_index_last_5: number;
  ppda_last_5: number | null;
  momentum: number;
  possession_pct_match: number;
  pass_accuracy_pct_match: number;
  shots_match: number;
  goals: number;
}
export interface Stats {
  match_id: string;
  game_clock_s: number;
  minute: number;
  period: number;
  score: Record<string, number>;
  teams: Record<string, TeamStats>;
  chaos_index_last_5: number;
  rhythm_last_5: { label: string; passes_per_min: number; median_pass_gap_s: number };
}
export interface PlayerStats {
  player_id: string;
  name: string;
  name_ar?: string;
  at_s: number;
  distance_km: number;
  top_speed_kmh: number;
  badges: string[];
  events: Record<string, number | null>;
}

export interface AdvancedTeam {
  current: Record<string, number | null>;
  match: Record<string, number | null>;
  deltas: Record<string, number | null>;
  evidence_event_ids: string[];
  pass_network: {
    nodes: { player_id: string; x_m: number; y_m: number; evidence_event_ids: string[] }[];
    edges: {
      from_player_id: string;
      to_player_id: string;
      completed_passes: number;
      evidence_event_ids: string[];
    }[];
  };
  shot_map: {
    event_id: string;
    player_id: string;
    game_time_s: number;
    x_m: number;
    y_m: number;
    outcome: string;
    distance_m: number | null;
    speed_kmh: number | null;
  }[];
  territory: {
    column: number;
    row: number;
    completed_passes: number;
    evidence_event_ids: string[];
  }[];
}
export interface AdvancedStats {
  match_id: string;
  at_s: number;
  window_s: number;
  window_start_s: number;
  definitions_version: string;
  definitions: Record<string, string>;
  teams: Record<string, AdvancedTeam>;
  evidence_event_ids: string[];
  tracking: TrackingStats | null;
}
export interface FrameRange {
  first_frame: number;
  last_frame: number;
  from_s: number;
  to_s: number;
  sample_count: number;
}
export interface TrackingStats {
  at_s: number;
  window_s: number;
  window_start_s: number;
  thresholds: {
    distance_threshold_kmh: number;
    sprint_threshold_kmh: number;
    sprint_min_duration_s: number;
  };
  defensive_line_players: number;
  teams: Record<
    string,
    {
      mean_width_m: number | null;
      mean_length_m: number | null;
      defensive_line_height_m: number | null;
      defensive_line_sample_count: number;
      evidence: FrameRange | null;
    }
  >;
  players: Record<
    string,
    {
      distance_above_threshold_m: number | null;
      sprints: number | null;
      speed_sample_count: number;
      window_evidence: FrameRange | null;
      evidence: FrameRange | null;
    }
  >;
}
export interface FanStats {
  match_id: string;
  at_s: number;
  window_s: number;
  window_start_s: number;
  definitions: Record<string, string>;
  control_window_s: number;
  on_top: { status: 'leading' | 'mixed' | 'insufficient'; team_id: string | null };
  teams: Record<
    string,
    {
      summary: {
        goals: number;
        shots_match: number;
        possession_pct_match: number | null;
        pass_accuracy_pct_match: number | null;
        ppda_match: number | null;
        control_index_last_5: number | null;
        momentum: number;
      };
      average_positions: {
        player_id: string;
        x_m: number;
        y_m: number;
        sample_count: number;
        first_frame: number;
        last_frame: number;
      }[];
      leaderboards: Record<
        'distance_km' | 'top_speed_kmh',
        { rank: number; player_id: string; value: number; tracking_until_s: number }[]
      >;
      key_moments: Moment[];
    }
  >;
  momentum_timeline: {
    at_s: number;
    teams: Record<string, { value: number; evidence_event_ids: string[] }>;
  }[];
  evidence_event_ids: string[];
  tracking: TrackingStats;
}
export interface Evidence {
  moment: Moment;
  facts: Record<string, Fact>;
  rule: { rule_id: string; description: string };
  evidence_events: { event_id: string; type: string; game_time_s: number; player_id?: string }[];
  all_evidence_resolved: boolean;
}
export interface Recap {
  headline: string;
  body: string;
  dir: 'ltr' | 'rtl';
  source: 'agent' | 'template';
  verification_status: string;
  final: boolean;
  key_moments: { moment_id: string; minute: number; headline: string; body: string }[];
  evidence_overlay_ids: string[];
}
export interface Scenario {
  match_id: string;
  title: string;
  description: string;
  scenario_id: string;
}
export interface Health {
  status: string;
  version: string;
  agents: { mode?: string };
  budget: { live_ai_enabled: boolean };
  demo_bundles: {
    match_id: string;
    stale: boolean;
    recaps: number;
    counts: Record<string, number>;
    overlay_sources: Record<string, number>;
  }[];
}
export interface BreakResult {
  draft: Overlay;
  verdict: { status: string; reason_code: string; detail: string };
  repaired_or_fallback_overlay: Overlay;
}
export interface Preferences {
  persona: Persona;
  language: Language;
  club: string;
  player: string;
}
export interface ActionCommentary {
  show_at_s: number;
  text: Record<Language, string>;
}
export interface PlayByPlayEntry extends ActionCommentary {
  event_id: string;
  seq: number;
  type: string;
  team_id?: string;
  player_id?: string;
  receiver_id?: string;
}
export type StreamMessage = { match_id: string; run_id: string; game_time_s: number } & (
  | { type: 'reset'; data: { reason: string } }
  | { type: 'metadata'; data: Metadata }
  | { type: 'state'; data: MatchState }
  | { type: 'tracking'; data: Tracking }
  | { type: 'overlay'; data: Overlay }
  | { type: 'moment'; data: Moment }
  | {
      type: 'event';
      data: {
        event_id: string;
        seq?: number;
        type: string;
        team_id?: string;
        player_id?: string;
        receiver_id?: string;
      };
      commentary?: ActionCommentary;
    }
  | { type: 'control'; data: { action: string; speed?: number } }
  | { type: 'replay'; data: { state: string; speed: number; game_time_s: number } }
  | { type: 'hello'; data: { mode: string; broadcast_delay_s: number } }
);
