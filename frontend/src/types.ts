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
  events: Record<string, number>;
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
export type StreamMessage = { match_id: string; run_id: string; game_time_s: number } & (
  | { type: 'reset'; data: { reason: string } }
  | { type: 'metadata'; data: Metadata }
  | { type: 'state'; data: MatchState }
  | { type: 'tracking'; data: Tracking }
  | { type: 'overlay'; data: Overlay }
  | { type: 'moment'; data: Moment }
  | { type: 'event'; data: { event_id: string; type: string; player_id?: string } }
  | { type: 'control'; data: { action: string; speed?: number } }
  | { type: 'replay'; data: { state: string; speed: number; game_time_s: number } }
  | { type: 'hello'; data: { mode: string; broadcast_delay_s: number } }
);
