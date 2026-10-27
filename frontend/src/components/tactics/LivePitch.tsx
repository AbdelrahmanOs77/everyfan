import { useState } from 'react';
import { advancedCopy, clockLabel, displayNumber, localizedName } from '../../i18n';
import type { Language, Metadata, Tracking } from '../../types';
import type { Tactics } from '../../advancedTypes';
import { apiUrl } from '../../api';
import { Pitch } from '../Pitch';
import { FormationBadge, LayerToggle, PitchLayers, usePitchLayers } from './PitchLayers';

export function LivePitch({
  metadata,
  frame,
  data,
  language,
  onSeek,
}: {
  metadata: Metadata;
  frame: Tracking | null;
  data: Tactics;
  language: Language;
  onSeek: (at: number) => void;
}) {
  const t = advancedCopy[language];
  const [layers, toggle] = usePitchLayers();
  const [team, setTeam] = useState(metadata.home.team_id);
  const [counter, setCounter] = useState(0);
  const [rate, setRate] = useState(false);
  const facts = data.teams[team];
  const playerName = (id: string) => {
    const player = [...metadata.home.players, ...metadata.away.players].find(
      (p) => p.player_id === id,
    );
    return player ? localizedName(player, language) : id;
  };
  return (
    <section className="live-tactics">
      <LayerToggle layers={layers} onToggle={toggle} language={language} />
      <FormationBadge data={data} metadata={metadata} language={language} />
      <div className="analysis-selects">
        <label>
          {t.team}
          <select value={team} onChange={(e) => setTeam(e.target.value)}>
            {[metadata.home, metadata.away].map((x) => (
              <option key={x.team_id} value={x.team_id}>
                {localizedName(x, language)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <Pitch
        metadata={metadata}
        frame={frame}
        clock={data.at_s}
        selected=""
        language={language}
        moments={[]}
        onSelect={() => {}}
        layers={
          frame ? (
            <PitchLayers
              frame={frame}
              metadata={metadata}
              data={data}
              layers={layers}
              selectedTeam={team}
              selectedCounter={counter}
            />
          ) : undefined
        }
      />
      {facts && (
        <>
          <div className="tracking-metric-grid">
            {[
              [t.area, facts.shape.area_m2, 'm²'],
              [t.width, facts.shape.mean_width_m, 'm'],
              [t.length, facts.shape.mean_length_m, 'm'],
              [t.line, facts.shape.defensive_line_height_m, 'm'],
              [t.match, facts.shape.match_area_m2, 'm²'],
              [t.breaking, facts.line_breaking.count, ''],
              [t.counters, facts.counters.count, ''],
              [t.fastBreaks, facts.counters.fast_breaks, ''],
            ].map(([label, value, unit]) => (
              <div key={String(label)}>
                <span>{label}</span>
                <strong>
                  <bdi>{displayNumber(value as number | null)}</bdi> {unit}
                </strong>
              </div>
            ))}
          </div>
          <p className="plot-caption">{t.spatialLabel}</p>
          <div className="table-scroll">
            <table>
              <caption>
                {t.shape} / {t.lines}
              </caption>
              <thead>
                <tr>
                  <th>{t.metric}</th>
                  <th>{t.current}</th>
                  <th>{t.window}</th>
                  <th>{t.match}</th>
                </tr>
              </thead>
              <tbody>
                {[
                  [
                    t.area,
                    facts.shape.current?.area_m2,
                    facts.shape.area_m2,
                    facts.shape.match_area_m2,
                  ],
                  [
                    t.width,
                    facts.shape.current?.width_m,
                    facts.shape.mean_width_m,
                    facts.shape.match_width_m,
                  ],
                  [
                    t.length,
                    facts.shape.current?.length_m,
                    facts.shape.mean_length_m,
                    facts.shape.match_length_m,
                  ],
                  [
                    t.line,
                    facts.shape.current?.defensive_line_height_m,
                    facts.lines.window_four_m,
                    facts.lines.match_four_m,
                  ],
                  [
                    t.deepest,
                    facts.lines.current?.deepest_outfield_m,
                    facts.lines.window_deepest_m,
                    facts.lines.match_deepest_m,
                  ],
                ].map(([label, ...values]) => (
                  <tr key={String(label)}>
                    <th>{label}</th>
                    {values.map((v, i) => (
                      <td key={i}>{displayNumber(v as number | null)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <svg className="progress-chart" viewBox="0 0 600 110" role="img" aria-label={t.line}>
            <polyline
              fill="none"
              stroke="var(--accent)"
              strokeWidth="2"
              points={facts.line_timeline
                .filter((p) => p.height_m != null)
                .map((p) => `${10 + (p.at_s / Math.max(1, data.at_s)) * 580},${100 - p.height_m!}`)
                .join(' ')}
            />
          </svg>
          <details>
            <summary>
              {t.line} · {t.time}
            </summary>
            <ul>
              {facts.line_timeline.map((p) => (
                <li key={p.at_s}>
                  <bdi>{clockLabel(p.at_s)}</bdi> · {displayNumber(p.height_m)} m
                </li>
              ))}
            </ul>
          </details>
          <div className="table-scroll">
            <table>
              <caption>{t.space}</caption>
              <thead>
                <tr>
                  <th>{t.metric}</th>
                  <th>{t.current}</th>
                  <th>{t.window}</th>
                </tr>
              </thead>
              <tbody>
                {[
                  ['whole_pct', t.whole],
                  ['opponent_half_pct', t.half],
                  ['final_third_pct', t.third],
                ].map(([key, label]) => (
                  <tr key={key}>
                    <th scope="row">{label}</th>
                    <td>{displayNumber(facts.control?.current[key!])}%</td>
                    <td>{displayNumber(facts.control?.window[key!])}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <details>
            <summary>{t.formation}</summary>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>{t.time}</th>
                    <th>{t.withBall}</th>
                    <th>{t.withoutBall}</th>
                  </tr>
                </thead>
                <tbody>
                  {facts.formation_timeline.map((row) => (
                    <tr key={row.at_s}>
                      <th>{clockLabel(row.at_s)}</th>
                      <td>
                        <bdi>{row.in_possession?.label ?? '—'}</bdi>
                      </td>
                      <td>
                        <bdi>{row.out_of_possession?.label ?? '—'}</bdi>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
          <details>
            <summary>{t.links}</summary>
            {facts.links.map((link) => (
              <p key={`${link.from_player_id}-${link.to_player_id}`}>
                <bdi>
                  {playerName(link.from_player_id)} → {playerName(link.to_player_id)} ·{' '}
                  {link.completed_passes}
                </bdi>{' '}
                <a
                  className="event-link"
                  href={apiUrl(
                    `/api/matches/${data.match_id}/events/${link.evidence_event_ids[0]}`,
                  )}
                  target="_blank"
                  rel="noreferrer"
                >
                  {t.source}
                </a>
              </p>
            ))}
          </details>
          <details>
            <summary>{t.breaking}</summary>
            <p>
              {t.skipped}: <bdi>{facts.line_breaking.skipped}</bdi>
            </p>
            {facts.line_breaking.passes.map((pass) => (
              <p key={pass.event_id}>
                <a
                  className="event-link"
                  href={apiUrl(`/api/matches/${data.match_id}/events/${pass.event_id}`)}
                  target="_blank"
                  rel="noreferrer"
                >
                  {pass.event_id}
                </a>{' '}
                ·{' '}
                <bdi>
                  {pass.players_bypassed} / {pass.lines_broken}
                </bdi>
              </p>
            ))}
          </details>
          <details>
            <summary>{t.counters}</summary>
            {facts.counters.items.map((item, i) => (
              <button
                key={item.at_s}
                className="secondary-button"
                onClick={() => {
                  setCounter(i);
                  if (!layers.includes('counters')) toggle('counters');
                  onSeek(item.start_s);
                }}
              >
                {t.view}{' '}
                <bdi>
                  {clockLabel(item.start_s)} · {item.duration_s}s · {item.passes}
                </bdi>
              </button>
            ))}
          </details>
          <details>
            <summary>{t.pressing}</summary>
            <button className="text-button" onClick={() => setRate(!rate)}>
              {rate ? t.count : t.rate}
            </button>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>{t.positions}</th>
                    <th>{rate ? t.rate : t.count}</th>
                    <th>{t.distance}</th>
                    <th>{t.source}</th>
                  </tr>
                </thead>
                <tbody>
                  {facts.pressing.cells.map((c) => (
                    <tr key={`${c.column}-${c.row}`}>
                      <th>
                        <bdi>
                          {c.column} · {c.row}
                        </bdi>
                      </th>
                      <td>{displayNumber(rate ? c.rate_per_min : c.count)}</td>
                      <td>{displayNumber(c.nearest_presser_m)} m</td>
                      <td>
                        {c.evidence_event_ids.map((id) => (
                          <a
                            className="event-link"
                            key={id}
                            href={apiUrl(`/api/matches/${data.match_id}/events/${id}`)}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {id}
                          </a>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}
      <details className="metric-definitions">
        <summary>{t.definitions}</summary>
        {Object.entries(data.definitions).map(([k, v]) => (
          <p key={k}>{v}</p>
        ))}
        <a
          className="event-link"
          href={apiUrl(
            `/api/matches/${data.match_id}/tactics?at_s=${data.at_s}&window_s=${data.window_s}`,
          )}
          target="_blank"
          rel="noreferrer"
        >
          {t.source}
        </a>
      </details>
    </section>
  );
}
