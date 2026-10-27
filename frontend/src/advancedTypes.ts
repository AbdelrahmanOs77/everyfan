import type { FrameRange, Player } from './types';
export interface Formation {
  label: string;
  separation_score: number;
  frame_count: number;
  lines: { player_ids: string[]; mean_depth_m: number }[];
}
export interface TacticalTeam {
  line_timeline: { at_s: number; height_m: number | null }[];
  formation: {
    in_possession: Formation | null;
    out_of_possession: Formation | null;
    stable_label: Record<string, string | null>;
  };
  formation_timeline: {
    at_s: number;
    in_possession: Formation | null;
    out_of_possession: Formation | null;
  }[];
  shape: {
    mean_width_m: number | null;
    mean_length_m: number | null;
    defensive_line_height_m: number | null;
    area_m2: number | null;
    match_area_m2: number | null;
    match_width_m: number | null;
    match_length_m: number | null;
    current: {
      hull: number[][];
      area_m2: number | null;
      width_m: number | null;
      length_m: number | null;
      defensive_line_height_m: number | null;
    } | null;
  };
  lines: {
    current: { offside_x_m: number | null; deepest_outfield_m: number | null } | null;
    window_deepest_m: number | null;
    match_deepest_m: number | null;
    window_four_m: number | null;
    match_four_m: number | null;
  };
  links: {
    from_player_id: string;
    to_player_id: string;
    completed_passes: number;
    evidence_event_ids: string[];
  }[];
  control: { current: Record<string, number | null>; window: Record<string, number | null> } | null;
  line_breaking: {
    count: number;
    match_count: number;
    skipped: number;
    passes: {
      event_id: string;
      start_xy: number[];
      end_xy: number[];
      players_bypassed: number;
      lines_broken: number;
    }[];
  };
  counters: {
    count: number;
    match_count: number;
    fast_breaks: number;
    items: {
      start_s: number;
      at_s: number;
      duration_s: number;
      passes: number;
      shot_outcome: string;
      evidence_event_ids: string[];
      chain: { start_x_m?: number; start_y_m?: number; end_x_m?: number; end_y_m?: number }[];
    }[];
  };
  pressing: {
    ppda: number | null;
    cells: {
      column: number;
      row: number;
      count: number;
      rate_per_min: number;
      nearest_presser_m: number | null;
      evidence_event_ids: string[];
    }[];
  };
}
export interface Tactics {
  match_id: string;
  at_s: number;
  window_s: number;
  teams: Record<string, TacticalTeam>;
  definitions: Record<string, string>;
  evidence: { frame_range: FrameRange | null; evidence_event_ids: string[] };
}
export interface BenchmarkRow {
  metric: string;
  value: number | null;
  peer_median: number | null;
  percentile: number | null;
  normalization: string;
  pool_size: number;
  evidence_event_ids: string[];
  frame_range: FrameRange | null;
}
export interface Benchmark {
  group: string;
  reliable: boolean;
  pool_size: number;
  peer_ids: string[];
  rows: BenchmarkRow[];
}
export interface RoleIndex {
  value: number | null;
  formula: string;
  parts: { metric: string; weight: number; percentile: number; contribution: number }[];
}
export interface Run {
  start_s: number;
  end_s: number;
  start_xy: number[];
  end_xy: number[];
  duration_s: number;
  distance_m: number;
  max_speed_kmh: number;
  depth_gain_m: number;
  period: number;
  evidence: FrameRange;
  box_run?: boolean;
  final_third_run?: boolean;
  received_pass_event_id?: string | null;
}
export interface Profile {
  match_id: string;
  player: Player;
  at_s: number;
  window_s: number;
  window_start_s: number;
  minutes_played: number;
  metrics: Record<string, number | null>;
  benchmark: Benchmark;
  role_index: RoleIndex;
  progress: { at_s: number; benchmark: Benchmark; role_index: RoleIndex }[];
  heatmap: {
    columns: number;
    rows: number;
    sample_count: number;
    cells: { column: number; row: number; count: number; share_pct: number }[];
    evidence: FrameRange | null;
  };
  trail: { at_s: number; x_m: number; y_m: number; period: number }[];
  sprints: Run[];
  off_ball_runs: { count: number; items: Run[] };
  fatigue: {
    start_s: number;
    end_s: number;
    minutes_played: number;
    distance_per_min_m: number | null;
    high_intensity_per_min_m: number | null;
    top_speed_kmh: number | null;
    sprints: number | null;
    first_block_pct: number | null;
  }[];
  matchup: {
    opponent_id: string;
    mean_distance_m: number;
    nearest_share_pct: number;
    shared_frames: number;
    duels_won: number;
    duels_lost: number;
    evidence_event_ids: string[];
    player_metrics: {
      values: Record<string, number | null>;
      minutes_played: number;
      normalizations: Record<string, string>;
    };
    opponent_metrics: {
      values: Record<string, number | null>;
      minutes_played: number;
      normalizations: Record<string, string>;
    };
  } | null;
  definitions: Record<string, string>;
  evidence: { evidence_event_ids: string[]; frame_range: FrameRange | null };
}
