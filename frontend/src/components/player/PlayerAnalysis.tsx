import { advancedCopy, advancedMetricNames, clockLabel, displayNumber } from '../../i18n';
import { apiUrl } from '../../api';
import type { Language, Metadata } from '../../types';
import type { Profile, Run } from '../../advancedTypes';

export function PlayerMovementLayer({ data }: { data: Profile }) {
  return (
    <g
      pointerEvents="none"
      fill="none"
      stroke="var(--accent)"
      transform="translate(0 68) scale(1 -1)"
    >
      {data.trail.slice(1).map((p, i) => (
        <line
          key={p.at_s}
          x1={data.trail[i]!.x_m}
          y1={data.trail[i]!.y_m}
          x2={p.x_m}
          y2={p.y_m}
          strokeWidth=".8"
          opacity={0.1 + (0.8 * i) / Math.max(1, data.trail.length)}
        />
      ))}
      {data.sprints.map((run, i) => (
        <path
          key={`s${i}`}
          d={`M${run.start_xy.join(' ')}L${run.end_xy.join(' ')}`}
          stroke={run.period === 1 ? 'var(--accent)' : 'white'}
          strokeWidth=".7"
        />
      ))}
      {data.off_ball_runs.items.map((run, i) => (
        <path
          key={`r${i}`}
          d={`M${run.start_xy.join(' ')}L${run.end_xy.join(' ')}`}
          strokeDasharray="1 .8"
          strokeWidth=".6"
        />
      ))}
    </g>
  );
}
export function PlayerAnalysis({
  data,
  metadata,
  language,
  onSeek,
}: {
  data: Profile;
  metadata: Metadata;
  language: Language;
  onSeek: (t: number) => void;
}) {
  const t = advancedCopy[language],
    ar = language === 'ar';
  const name = (key: string) => advancedMetricNames[key]?.[ar ? 1 : 0] ?? key;
  const players = [...metadata.home.players, ...metadata.away.players];
  const source = (
    <a
      className="event-link"
      href={apiUrl(
        `/api/matches/${data.match_id}/players/${data.player.player_id}/profile?at_s=${data.at_s}&window_s=${data.window_s}`,
      )}
      target="_blank"
      rel="noreferrer"
    >
      {t.source}
    </a>
  );
  const point = (percent: number, i: number, total: number) => {
    const a = (i * 2 * Math.PI) / total - Math.PI / 2;
    return `${100 + percent * 0.8 * Math.cos(a)},${100 + percent * 0.8 * Math.sin(a)}`;
  };
  const rows = data.benchmark.rows;
  const runs = (items: Run[], off = false) => (
    <>
      <svg
        className="analysis-pitch"
        viewBox="0 0 105 68"
        role="img"
        aria-label={off ? t.offBall : t.sprints}
      >
        <rect width="105" height="68" fill="var(--grass-dark)" />
        {items.map((run, i) => (
          <g key={i}>
            <path
              d={`M${run.start_xy[0]} ${68 - run.start_xy[1]!}L${run.end_xy[0]} ${68 - run.end_xy[1]!}`}
              stroke={run.period === 1 ? 'var(--accent)' : 'white'}
              strokeWidth=".6"
              strokeDasharray={off ? '1 .7' : undefined}
            />
            <circle cx={run.end_xy[0]} cy={68 - run.end_xy[1]!} r=".8" fill="var(--accent)" />
          </g>
        ))}
      </svg>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>{t.time}</th>
              <th>{t.distance}</th>
              <th>{t.duration}</th>
              <th>{off ? t.depth : t.speed}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((run, i) => (
              <tr key={i}>
                <th>
                  <button className="text-button" onClick={() => onSeek(run.start_s)}>
                    {clockLabel(run.start_s)}–{clockLabel(run.end_s)}
                  </button>
                </th>
                <td>{displayNumber(run.distance_m)} m</td>
                <td>{displayNumber(run.duration_s)} s</td>
                <td>
                  {displayNumber(off ? run.depth_gain_m : run.max_speed_kmh)} {off ? 'm' : 'km/h'}{' '}
                  {off && run.received_pass_event_id && (
                    <a
                      href={apiUrl(
                        `/api/matches/${data.match_id}/events/${run.received_pass_event_id}`,
                      )}
                      className="event-link"
                      target="_blank"
                      rel="noreferrer"
                    >
                      {t.received}
                    </a>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
  return (
    <section className="player-analysis extra-panel" aria-label={t.profile}>
      <div className="section-heading">
        <h2>{t.profile}</h2>
        {source}
      </div>
      <p className="data-stamp">
        {t.asOf} <bdi>{clockLabel(data.at_s)}</bdi> · {t.minutes}:{' '}
        <bdi>{displayNumber(data.minutes_played)}</bdi>
      </p>
      <details open>
        <summary>{t.benchmark}</summary>
        <p>
          {t.pool}: <bdi>{data.benchmark.pool_size}</bdi> · <bdi>{data.benchmark.group}</bdi>
        </p>
        {!data.benchmark.reliable && <p className="notice-banner">{t.early}</p>}
        <svg
          className={`benchmark-radar${data.benchmark.reliable ? '' : ' unreliable'}`}
          viewBox="0 0 200 200"
          role="img"
          aria-label={t.benchmark}
        >
          <polygon
            points={rows.map((_, i) => point(50, i, rows.length)).join(' ')}
            fill="none"
            stroke="var(--muted)"
            strokeDasharray="3 2"
          />
          <polygon
            points={rows.map((r, i) => point(r.percentile ?? 0, i, rows.length)).join(' ')}
            fill="var(--accent)"
            fillOpacity=".2"
            stroke="var(--accent)"
          />
          {rows.map((r, i) => (
            <line
              key={r.metric}
              x1="100"
              y1="100"
              x2={point(100, i, rows.length).split(',')[0]}
              y2={point(100, i, rows.length).split(',')[1]}
              stroke="var(--line)"
            />
          ))}
        </svg>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>{t.metric}</th>
                <th>{t.player}</th>
                <th>{t.median}</th>
                <th>{t.percentile}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.metric}>
                  <th>
                    {name(r.metric)}{' '}
                    <small>{r.normalization === 'per_90' ? t.per90 : t.native}</small>
                    <a
                      className="event-link"
                      href={
                        r.evidence_event_ids[0]
                          ? apiUrl(
                              `/api/matches/${data.match_id}/events/${r.evidence_event_ids[0]}`,
                            )
                          : apiUrl(
                              `/api/matches/${data.match_id}/players/${data.player.player_id}/profile?at_s=${data.at_s}&sections=benchmark`,
                            )
                      }
                      target="_blank"
                      rel="noreferrer"
                    >
                      {t.source}
                    </a>
                  </th>
                  <td>{displayNumber(r.value)}</td>
                  <td>{displayNumber(r.peer_median)}</td>
                  <td>{displayNumber(r.percentile)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <details>
          <summary>{t.pool}</summary>
          <p className="peer-ids">{data.benchmark.peer_ids.join(', ')}</p>
        </details>
      </details>
      <details open>
        <summary>{t.role}</summary>
        <strong className="role-index">
          <bdi>{displayNumber(data.role_index.value)}</bdi>
        </strong>
        <p>
          <code>{data.role_index.formula}</code>
        </p>
        <div className="role-breakdown">
          {data.role_index.parts.map((p) => (
            <div key={p.metric}>
              <span>
                {name(p.metric)} ·{' '}
                <bdi>
                  {p.weight} × {p.percentile}%
                </bdi>
              </span>
              <meter min="0" max="10" value={p.contribution} aria-label={name(p.metric)} />
              <bdi>{p.contribution}</bdi>
            </div>
          ))}
        </div>
      </details>
      <details>
        <summary>{t.progress}</summary>
        <svg className="progress-chart" viewBox="0 0 600 140" role="img" aria-label={t.progress}>
          <polyline
            fill="none"
            stroke="#efcc8c"
            strokeWidth="3"
            points={data.progress
              .filter((p) => p.role_index.value != null)
              .map(
                (p) =>
                  `${10 + (p.at_s / Math.max(1, data.at_s)) * 580},${130 - p.role_index.value! * 12}`,
              )
              .join(' ')}
          />
          {rows.map((r, j) => (
            <polyline
              key={r.metric}
              fill="none"
              stroke={j % 2 ? 'var(--text)' : 'var(--accent)'}
              strokeDasharray={j % 2 ? '4 2' : undefined}
              points={data.progress
                .map(
                  (p) =>
                    `${10 + (p.at_s / Math.max(1, data.at_s)) * 580},${130 - (p.benchmark.rows.find((x) => x.metric === r.metric)?.percentile ?? 0) * 1.2}`,
                )
                .join(' ')}
            />
          ))}
        </svg>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>{t.time}</th>
                <th>{t.role}</th>
                {rows.map((r) => (
                  <th key={r.metric}>{name(r.metric)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.progress.map((p) => (
                <tr key={p.at_s}>
                  <th>{clockLabel(p.at_s)}</th>
                  <td>{displayNumber(p.role_index.value)}</td>
                  {p.benchmark.rows.map((r) => (
                    <td key={r.metric}>
                      {displayNumber(r.value)} · {displayNumber(r.percentile)}%
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
      <details open>
        <summary>{t.heatmap}</summary>
        <svg className="analysis-pitch" viewBox="0 0 105 68" role="img" aria-label={t.heatmap}>
          <rect width="105" height="68" fill="var(--grass-dark)" />
          {data.heatmap.cells.map((c) => (
            <rect
              key={`${c.column}-${c.row}`}
              x={(c.column * 105) / data.heatmap.columns}
              y={68 - ((c.row + 1) * 68) / data.heatmap.rows}
              width={105 / data.heatmap.columns}
              height={68 / data.heatmap.rows}
              fill="var(--accent)"
              opacity={Math.min(0.9, 0.1 + c.share_pct / 10)}
            />
          ))}
          <polyline
            points={data.trail.map((p) => `${p.x_m},${68 - p.y_m}`).join(' ')}
            fill="none"
            stroke="white"
            strokeWidth=".5"
          />
        </svg>
        <p>
          {t.samples}: <bdi>{data.heatmap.sample_count}</bdi>
        </p>
        <details>
          <summary>{t.positions}</summary>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>{t.positions}</th>
                  <th>{t.samples}</th>
                  <th>%</th>
                </tr>
              </thead>
              <tbody>
                {data.heatmap.cells.map((c) => (
                  <tr key={`${c.column}-${c.row}`}>
                    <th>
                      {c.column} · {c.row}
                    </th>
                    <td>{c.count}</td>
                    <td>{c.share_pct}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </details>
      <details>
        <summary>{t.sprints}</summary>
        {runs(data.sprints)}
      </details>
      <details>
        <summary>
          {t.offBall} · <bdi>{data.off_ball_runs.count}</bdi>
        </summary>
        {runs(data.off_ball_runs.items, true)}
      </details>
      <details>
        <summary>{t.fatigue}</summary>
        <p>{t.noPrediction}</p>
        <svg className="progress-chart" viewBox="0 0 600 150" role="img" aria-label={t.fatigue}>
          {data.fatigue.map((b, i) => (
            <g key={b.start_s}>
              <title>
                {clockLabel(b.start_s)}: {displayNumber(b.distance_per_min_m)} m/min ·{' '}
                {displayNumber(b.first_block_pct)}%
              </title>
              <rect
                x={10 + (i * 580) / Math.max(1, data.fatigue.length)}
                y={140 - Math.min(130, (b.distance_per_min_m ?? 0) * 0.65)}
                width={500 / Math.max(1, data.fatigue.length)}
                height={Math.min(130, (b.distance_per_min_m ?? 0) * 0.65)}
                fill="var(--accent)"
                opacity=".8"
              />
            </g>
          ))}
        </svg>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>{t.time}</th>
                <th>{t.distanceRate}</th>
                <th>{t.highRate}</th>
                <th>{t.sprints}</th>
                <th>{t.speed}</th>
                <th>{t.firstBlock}</th>
              </tr>
            </thead>
            <tbody>
              {data.fatigue.map((b) => (
                <tr key={b.start_s}>
                  <th>
                    {clockLabel(b.start_s)}–{clockLabel(b.end_s)}
                  </th>
                  <td>{displayNumber(b.distance_per_min_m)}</td>
                  <td>{displayNumber(b.high_intensity_per_min_m)}</td>
                  <td>{displayNumber(b.sprints)}</td>
                  <td>{displayNumber(b.top_speed_kmh)}</td>
                  <td>{displayNumber(b.first_block_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
      <details>
        <summary>{t.matchup}</summary>
        {data.matchup ? (
          <>
            <h3>
              {players.find((p) => p.player_id === data.matchup!.opponent_id)?.[
                ar ? 'name_ar' : 'name'
              ] ?? data.matchup.opponent_id}
            </h3>
            <dl className="tracking-metric-grid">
              {[
                [t.distance, data.matchup.mean_distance_m, 'm'],
                [t.nearest, data.matchup.nearest_share_pct, '%'],
                [t.duelsWon, data.matchup.duels_won, ''],
                [t.duelsLost, data.matchup.duels_lost, ''],
              ].map(([label, value, unit]) => (
                <div key={String(label)}>
                  <dt>{label}</dt>
                  <dd>
                    {displayNumber(value as number)} {unit}
                  </dd>
                </div>
              ))}
            </dl>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>{t.metric}</th>
                    <th>{t.player}</th>
                    <th>{t.matchup}</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.keys(data.matchup.player_metrics.values).map((key) => (
                    <tr key={key}>
                      <th>
                        {name(key)}
                        <small>
                          {data.matchup!.player_metrics.normalizations[key] === 'per_90'
                            ? t.per90
                            : t.native}
                        </small>
                      </th>
                      <td>{displayNumber(data.matchup!.player_metrics.values[key])}</td>
                      <td>{displayNumber(data.matchup!.opponent_metrics.values[key])}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <p>{t.unavailable}</p>
        )}
      </details>
      <details>
        <summary>{t.definitions}</summary>
        {Object.values(data.definitions).map((v) => (
          <p key={v}>{v}</p>
        ))}
        {source}
      </details>
    </section>
  );
}
