import { useState } from 'react';
import { Delaunay } from 'd3-delaunay';
import type { Tactics } from '../../advancedTypes';
import type { Language, Metadata, Tracking } from '../../types';
import { advancedCopy, localizedName } from '../../i18n';

export const layerKeys = [
  'formation',
  'shape',
  'links',
  'space',
  'lines',
  'breaking',
  'counters',
  'pressing',
] as const;
export type Layer = (typeof layerKeys)[number];
export function usePitchLayers() {
  const [layers, setLayers] = useState<Layer[]>(() => {
    try {
      const v: unknown = JSON.parse(localStorage.getItem('everyfan.pitch-layers.v1') || 'null');
      if (Array.isArray(v)) return v.filter((x): x is Layer => layerKeys.includes(x));
    } catch {
      /* Optional viewer preference. */
    }
    return ['formation', 'shape', 'links'];
  });
  return [
    layers,
    (layer: Layer) =>
      setLayers((previous) => {
        const next = previous.includes(layer)
          ? previous.filter((v) => v !== layer)
          : [...previous, layer];
        try {
          localStorage.setItem('everyfan.pitch-layers.v1', JSON.stringify(next));
        } catch {
          /* Storage is optional. */
        }
        return next;
      }),
  ] as const;
}
export function LayerToggle({
  layers,
  onToggle,
  language,
}: {
  layers: Layer[];
  onToggle: (v: Layer) => void;
  language: Language;
}) {
  const t = advancedCopy[language];
  return (
    <div className="analysis-tabs layer-toggle" role="group" aria-label={t.layers}>
      {layerKeys.map((key) => (
        <button key={key} aria-pressed={layers.includes(key)} onClick={() => onToggle(key)}>
          {t[key]}
        </button>
      ))}
    </div>
  );
}
export function FormationBadge({
  data,
  metadata,
  language,
}: {
  data: Tactics;
  metadata: Metadata;
  language: Language;
}) {
  const t = advancedCopy[language];
  return (
    <div className="formation-badges">
      {[metadata.home, metadata.away].map((team) => (
        <span key={team.team_id}>
          {localizedName(team, language)} · {t.withBall}:{' '}
          <bdi>{data.teams[team.team_id]?.formation.in_possession?.label ?? '—'}</bdi> ·{' '}
          {t.withoutBall}:{' '}
          <bdi>{data.teams[team.team_id]?.formation.out_of_possession?.label ?? '—'}</bdi>
        </span>
      ))}
    </div>
  );
}
export function PitchLayers({
  frame,
  metadata,
  data,
  layers,
  selectedTeam,
  selectedCounter,
}: {
  frame: Tracking;
  metadata: Metadata;
  data: Tactics;
  layers: Layer[];
  selectedTeam?: string;
  selectedCounter?: number;
}) {
  const xy = new Map(frame.players.map(([id, x, y]) => [id, [x, y] as [number, number]]));
  const players = new Map(
    [...metadata.home.players, ...metadata.away.players].map((p) => [p.player_id, p]),
  );
  const teams = [metadata.home, metadata.away].filter(
    (t) => !selectedTeam || t.team_id === selectedTeam,
  );
  const points = frame.players.map(([, x, y]) => [x, y] as [number, number]);
  const voronoi =
    layers.includes('space') && points.length
      ? Delaunay.from(points).voronoi([0, 0, 105, 68])
      : null;
  return (
    <g className="pitch-layers" pointerEvents="none" transform="translate(0 68) scale(1 -1)">
      <defs>
        <marker
          id="tactics-arrow"
          viewBox="0 0 6 6"
          refX="5"
          refY="3"
          markerWidth="4"
          markerHeight="4"
          orient="auto-start-reverse"
        >
          <path d="M0 0L6 3L0 6Z" fill="context-stroke" />
        </marker>
      </defs>
      {voronoi &&
        frame.players.map(([id], i) => (
          <path
            key={id}
            d={voronoi.renderCell(i)}
            fill={
              players.get(id)?.team_id === metadata.home.team_id
                ? metadata.home.primary_color
                : metadata.away.primary_color
            }
            opacity=".16"
            stroke="white"
            strokeWidth=".1"
          />
        ))}
      {teams.map((team) => {
        const facts = data.teams[team.team_id];
        if (!facts) return null;
        const lines =
          facts.formation.in_possession?.lines ?? facts.formation.out_of_possession?.lines ?? [];
        const livePoints = frame.players
          .filter(
            ([id]) =>
              players.get(id)?.team_id === team.team_id && players.get(id)?.position !== 'GK',
          )
          .map(([, x, y]) => [x, y] as [number, number]);
        const liveHull =
          livePoints.length >= 3
            ? Array.from(Delaunay.from(livePoints).hull).map((i) => livePoints[i]!)
            : livePoints;
        return (
          <g key={team.team_id} stroke={team.primary_color} fill={team.primary_color}>
            {layers.includes('shape') && liveHull.length > 2 && (
              <polygon
                points={liveHull.map((p) => p.join(',')).join(' ')}
                opacity=".14"
                strokeWidth=".7"
              />
            )}
            {layers.includes('formation') &&
              lines.map((line, i) => (
                <polyline
                  key={i}
                  points={line.player_ids
                    .filter((id) => xy.has(id))
                    .sort((a, b) => xy.get(a)![1] - xy.get(b)![1])
                    .flatMap((id) => (xy.has(id) ? [xy.get(id)!.join(',')] : []))
                    .join(' ')}
                  fill="none"
                  strokeWidth=".8"
                  opacity=".7"
                />
              ))}
            {layers.includes('links') &&
              facts.links.map((e) => {
                const a = xy.get(e.from_player_id),
                  b = xy.get(e.to_player_id);
                return a && b ? (
                  <line
                    key={`${e.from_player_id}-${e.to_player_id}`}
                    x1={a[0]}
                    y1={a[1]}
                    x2={b[0]}
                    y2={b[1]}
                    strokeWidth={Math.min(2, e.completed_passes * 0.2)}
                    opacity=".6"
                  />
                ) : null;
              })}
            {layers.includes('lines') && facts.lines.current?.offside_x_m != null && (
              <line
                x1={facts.lines.current.offside_x_m}
                x2={facts.lines.current.offside_x_m}
                y1="0"
                y2="68"
                strokeDasharray="2 1"
                strokeWidth=".6"
              />
            )}
            {layers.includes('lines') && facts.shape.defensive_line_height_m != null && (
              <line
                x1={
                  team.team_id === metadata.home.team_id
                    ? facts.shape.defensive_line_height_m
                    : 105 - facts.shape.defensive_line_height_m
                }
                x2={
                  team.team_id === metadata.home.team_id
                    ? facts.shape.defensive_line_height_m
                    : 105 - facts.shape.defensive_line_height_m
                }
                y1="0"
                y2="68"
                strokeDasharray="4 2"
                strokeWidth=".6"
              />
            )}
            {layers.includes('breaking') &&
              facts.line_breaking.passes.map((e) => (
                <path
                  key={e.event_id}
                  d={`M${e.start_xy.join(' ')}L${e.end_xy.join(' ')}`}
                  strokeWidth=".7"
                  markerEnd="url(#tactics-arrow)"
                />
              ))}
            {layers.includes('counters') &&
              facts.counters.items[selectedCounter ?? 0]?.chain.map((e, i) =>
                e.start_x_m != null &&
                e.start_y_m != null &&
                e.end_x_m != null &&
                e.end_y_m != null ? (
                  <line
                    key={i}
                    x1={e.start_x_m}
                    y1={e.start_y_m}
                    x2={e.end_x_m}
                    y2={e.end_y_m}
                    strokeWidth="1"
                  />
                ) : null,
              )}
            {layers.includes('pressing') &&
              facts.pressing.cells.map((c) => (
                <rect
                  key={`${c.column}-${c.row}`}
                  x={
                    team.team_id === metadata.home.team_id
                      ? c.column * 17.5
                      : 105 - (c.column + 1) * 17.5
                  }
                  y={c.row * 17}
                  width="17.5"
                  height="17"
                  opacity={Math.min(0.65, 0.08 + c.count * 0.04)}
                  strokeWidth=".2"
                />
              ))}
          </g>
        );
      })}
    </g>
  );
}
