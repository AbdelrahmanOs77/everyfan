import { useEffect, useRef, useState } from 'react';
import { MessageCircle, BookOpen, Send } from 'lucide-react';
import { apiUrl, request } from '../../api';
import {
  advancedCopy,
  advancedMetricNames,
  clockLabel,
  displayNumber,
  localizedName,
} from '../../i18n';
import type { Language, Metadata, Preferences, FrameRange } from '../../types';
import type { Formation, TacticalTeam } from '../../advancedTypes';
import { Dialog } from '../Dialogs';
import { useAdvancedResource } from '../../useAdvancedResource';

interface Answer {
  answer_id: string;
  at_s: number;
  answer: { headline: string; body: string };
  source: string;
  verification_status: string;
  facts: Record<string, unknown>;
  evidence_event_ids: string[];
  frame_ranges: FrameRange[];
}
interface CoachNote {
  note_id: string;
  game_clock_s: number;
  team_id: string;
  headline: string;
  body: string;
  source: string;
  verification_status: string;
  facts: Record<string, unknown>;
  evidence: { evidence_event_ids: string[]; frame_range: FrameRange | null };
  formations: { before: Record<string, Formation | null>; after: Record<string, Formation | null> };
}
interface Report {
  at_s: number;
  answer: Answer['answer'];
  source: string;
  verification_status: string;
  facts: {
    score: Record<string, number>;
    numbers: Record<
      string,
      {
        half: Record<string, number | null>;
        match: Record<string, number | null>;
        line_breaking: { half: number; match: number };
      }
    >;
    tactics: Record<string, TacticalTeam>;
    moments: {
      moment_id: string;
      game_clock_s: number;
      type: string;
      evidence_event_ids: string[];
    }[];
    scorers: { player_id: string; game_time_s: number; event_id: string }[];
    standouts: Record<string, { player_id: string; value: number }[]>;
    coach_notes: CoachNote[];
    what_to_watch: Record<string, unknown>[];
  };
  evidence: { evidence_event_ids: string[]; frame_range: FrameRange | null };
}
function Evidence({
  matchId,
  facts,
  ids,
  ranges,
  language,
  onClose,
}: {
  matchId: string;
  facts: unknown;
  ids: string[];
  ranges: (FrameRange | null)[];
  language: Language;
  onClose: () => void;
}) {
  const t = advancedCopy[language];
  return (
    <Dialog title={t.source} language={language} onClose={onClose}>
      <div className="dialog-body feature-evidence">
        <h3>{t.frame}</h3>
        <pre dir="ltr">{JSON.stringify(ranges.filter(Boolean), null, 2)}</pre>
        <h3>{t.definitions}</h3>
        <pre dir="ltr">{JSON.stringify(facts, null, 2)}</pre>
        <ul>
          {ids.map((id) => (
            <li key={id}>
              <a
                href={apiUrl(`/api/matches/${matchId}/events/${id}`)}
                target="_blank"
                rel="noreferrer"
              >
                {id}
              </a>
            </li>
          ))}
        </ul>
      </div>
    </Dialog>
  );
}
function FormationDiagram({
  formation,
  title,
}: {
  formation: Formation | null | undefined;
  title: string;
}) {
  return (
    <figure className="mini-formation">
      <figcaption>
        {title} · <bdi>{formation?.label ?? '—'}</bdi>
      </figcaption>
      <svg viewBox="0 0 105 68" aria-hidden="true">
        <rect
          x=".5"
          y=".5"
          width="104"
          height="67"
          rx="2"
          fill="var(--grass-dark)"
          stroke="var(--muted)"
        />
        {formation?.lines.map((line, i) =>
          line.player_ids.map((id, j) => (
            <circle
              key={id}
              cx={15 + i * 22}
              cy={((j + 1) * 68) / (line.player_ids.length + 1)}
              r="2"
              fill="var(--accent)"
            />
          )),
        )}
      </svg>
    </figure>
  );
}
export function AgentFeatures({
  metadata,
  clock,
  runId,
  active,
  mode,
  preference,
  onSeek,
}: {
  metadata: Metadata;
  clock: number;
  runId: string | null;
  active: boolean;
  mode: string;
  preference: Preferences;
  onSeek: (seconds: number) => void;
}) {
  const language = preference.language,
    t = advancedCopy[language];
  const [drawer, setDrawer] = useState(false),
    [question, setQuestion] = useState('');
  const [answers, setAnswers] = useState<{ q: string; data: Answer }[]>([]);
  const [asking, setAsking] = useState(false),
    [error, setError] = useState(false);
  const [phase, setPhase] = useState<'half' | 'full' | 'so_far' | null>(null);
  const [report, setReport] = useState<Report | null>(null),
    [reportError, setReportError] = useState(false);
  const [evidence, setEvidence] = useState<{
    facts: unknown;
    ids: string[];
    ranges: (FrameRange | null)[];
  } | null>(null);
  const previous = useRef({ runId, clock });
  const questionController = useRef<AbortController | null>(null);
  const source = mode === 'live' ? 'live' : 'demo';
  const coach = useAdvancedResource<{ at_s: number; notes: CoachNote[] }>(
    `/api/matches/${metadata.match_id}/coach-notes?persona=tactical&language=${language}&source=${source}&until_s=${Math.floor(clock / 30) * 30}`,
    runId,
    clock,
    active && preference.persona === 'tactical',
  );
  useEffect(() => {
    questionController.current?.abort();
    setAsking(false);
    setAnswers([]);
    setPhase(null);
    setReport(null);
    setEvidence(null);
  }, [metadata.match_id, runId, language, preference.persona]);
  useEffect(() => () => questionController.current?.abort(), []);
  useEffect(() => {
    const prior = previous.current;
    previous.current = { runId, clock };
    if (!active || runId !== prior.runId || clock < prior.clock) return;
    if (prior.clock < 5400 && clock >= 5400) setPhase('full');
    else if (prior.clock < 2700 && clock >= 2700) setPhase('half');
  }, [clock, runId, active]);
  useEffect(() => {
    if (!phase) return;
    const controller = new AbortController();
    setReport(null);
    setReportError(false);
    const at = Math.floor(clock);
    request<Report>(
      `/api/matches/${metadata.match_id}/report?phase=${phase}&at_s=${at}&persona=${preference.persona}&language=${language}&club_id=${encodeURIComponent(preference.club)}&source=${source}`,
      { signal: controller.signal },
    )
      .then(setReport)
      .catch(() => {
        if (!controller.signal.aborted) setReportError(true);
      });
    return () => controller.abort();
    // The report refers to the clock at opening, rather than restarting on each frame.
  }, [phase, metadata.match_id, language, preference.persona, preference.club, source]);
  const ask = async (q: string) => {
    if (!q.trim() || asking) return;
    const controller = new AbortController();
    questionController.current = controller;
    setAsking(true);
    setError(false);
    setQuestion('');
    try {
      const data = await request<Answer>(`/api/matches/${metadata.match_id}/ask`, {
        method: 'POST',
        signal: controller.signal,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: q.trim(),
          at_s: Math.floor(clock),
          persona: preference.persona,
          language,
          player_id: preference.player || null,
          club_id: preference.club || null,
          source,
          history: answers.slice(-4).map((a) => ({ q: a.q, a: a.data.answer.body })),
        }),
      });
      if (!controller.signal.aborted) setAnswers((old) => [...old, { q, data }]);
    } catch {
      if (!controller.signal.aborted) setError(true);
    } finally {
      if (!controller.signal.aborted) setAsking(false);
    }
  };
  const metric = (key: string) =>
    advancedMetricNames[key]?.[language === 'ar' ? 1 : 0] ?? key.replaceAll('_', ' ');
  const badge = (data: { source: string; verification_status: string }) =>
    data.source === 'agent' && data.verification_status === 'approved' ? t.verified : t.template;
  const openEvidence = (facts: unknown, ids: string[], ranges: (FrameRange | null)[]) =>
    setEvidence({ facts, ids, ranges });
  const teams = [metadata.home, metadata.away],
    players = teams.flatMap((team) => team.players);
  const playerName = (id: string) => {
    const p = players.find((p) => p.player_id === id);
    return p ? localizedName(p, language) : id;
  };
  return (
    <section className="agent-features" aria-label={t.ask}>
      <div className="feature-actions">
        <button className="primary-button" onClick={() => setDrawer(true)} disabled={!active}>
          <MessageCircle size={18} />
          {t.ask}
        </button>
        <button className="secondary-button" onClick={() => setPhase('so_far')} disabled={!active}>
          <BookOpen size={18} />
          {t.soFar}
        </button>
        {clock >= 2700 && (
          <button className="text-button" onClick={() => setPhase('half')}>
            {t.halfReport}
          </button>
        )}
        {clock >= 5400 && (
          <button className="text-button" onClick={() => setPhase('full')}>
            {t.fullReport}
          </button>
        )}
      </div>
      {preference.persona === 'tactical' && (
        <div className="coach-feed extra-panel">
          <h2>{t.coach}</h2>
          {coach.error ? (
            <button onClick={coach.refresh}>{t.retry}</button>
          ) : !coach.data ? (
            <p role="status">{t.loading}</p>
          ) : !coach.data.notes.length ? (
            <p>{t.noCoach}</p>
          ) : (
            coach.data.notes
              .slice(-8)
              .reverse()
              .map((note) => (
                <article className="coach-note" key={note.note_id}>
                  <span className="verification-badge">
                    {t.coach} · {badge(note)}
                  </span>
                  <h3>{note.headline}</h3>
                  <p>{note.body}</p>
                  <div className="formation-comparison">
                    <FormationDiagram
                      formation={
                        note.formations.before.out_of_possession ??
                        note.formations.before.in_possession
                      }
                      title={t.before}
                    />
                    <FormationDiagram
                      formation={
                        note.formations.after.out_of_possession ??
                        note.formations.after.in_possession
                      }
                      title={t.after}
                    />
                  </div>
                  <button className="text-button" onClick={() => onSeek(note.game_clock_s)}>
                    {t.view} · {clockLabel(note.game_clock_s)}
                  </button>
                  <button
                    className="text-button"
                    onClick={() =>
                      openEvidence(note.facts, note.evidence.evidence_event_ids, [
                        note.evidence.frame_range,
                      ])
                    }
                  >
                    {t.source}
                  </button>
                </article>
              ))
          )}
        </div>
      )}
      {drawer && (
        <Dialog title={t.ask} language={language} onClose={() => setDrawer(false)} wide>
          <div className="dialog-body ask-drawer">
            <p>{t.chatHint}</p>
            <div className="question-chips">
              {t.suggestions.map((q) => (
                <button
                  className="secondary-button"
                  key={q}
                  onClick={() => void ask(q)}
                  disabled={asking}
                >
                  {q}
                </button>
              ))}
            </div>
            <div className="answer-list" aria-live="polite">
              {answers
                .filter((a) => a.data.at_s <= clock)
                .map(({ q, data }) => (
                  <article className="answer-card" key={data.answer_id}>
                    <p className="question-echo">{q}</p>
                    <span className="verification-badge">{badge(data)}</span>
                    <h3>{data.answer.headline}</h3>
                    <p>{data.answer.body}</p>
                    <small>
                      {t.asOf} <bdi>{clockLabel(data.at_s)}</bdi>
                    </small>{' '}
                    <button
                      className="text-button"
                      onClick={() =>
                        openEvidence(data.facts, data.evidence_event_ids, data.frame_ranges)
                      }
                    >
                      {t.source}
                    </button>
                  </article>
                ))}
            </div>
            {asking && <p role="status">{t.loading}</p>}
            {error && (
              <p role="alert" className="error-banner">
                {t.askError}
              </p>
            )}
            <form
              className="ask-form"
              onSubmit={(e) => {
                e.preventDefault();
                void ask(question);
              }}
            >
              <label htmlFor="match-question">{t.question}</label>
              <textarea
                id="match-question"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                maxLength={300}
                rows={3}
              />
              <button
                className="primary-button"
                type="submit"
                disabled={asking || !question.trim()}
              >
                <Send size={16} />
                {t.send}
              </button>
            </form>
          </div>
        </Dialog>
      )}
      {phase && (
        <Dialog
          title={phase === 'half' ? t.halfReport : phase === 'full' ? t.fullReport : t.soFar}
          language={language}
          onClose={() => setPhase(null)}
          wide
        >
          <div className="dialog-body report-overlay">
            {reportError ? (
              <p role="alert">{t.failed}</p>
            ) : !report ? (
              <p role="status">{t.loading}</p>
            ) : (
              <>
                <span className="verification-badge">{badge(report)}</span>
                <h3>{report.answer.headline}</h3>
                <p>{report.answer.body}</p>
                <p>
                  {t.asOf} <bdi>{clockLabel(report.at_s)}</bdi>
                </p>
                <ul>
                  {report.facts.scorers.map((e) => (
                    <li key={e.event_id}>
                      {playerName(e.player_id)} · <bdi>{clockLabel(e.game_time_s)}</bdi>
                    </li>
                  ))}
                </ul>
                <div className="table-scroll">
                  <table>
                    <caption>{t.numbers}</caption>
                    <thead>
                      <tr>
                        <th>{t.metric}</th>
                        {teams.map((team) => (
                          <th key={team.team_id}>
                            {localizedName(team, language)}
                            <br />
                            {t.thisHalf} / {t.matchSoFar}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {[
                        'possession_pct',
                        'shots',
                        'shots_on_target',
                        'pass_accuracy_pct',
                        'ppda',
                        'final_third_entries',
                      ].map((key) => (
                        <tr key={key}>
                          <th>{metric(key)}</th>
                          {teams.map((team) => (
                            <td key={team.team_id}>
                              {displayNumber(report.facts.numbers[team.team_id]?.half[key])} /{' '}
                              {displayNumber(report.facts.numbers[team.team_id]?.match[key])}
                            </td>
                          ))}
                        </tr>
                      ))}
                      <tr>
                        <th>{t.breaking}</th>
                        {teams.map((team) => (
                          <td key={team.team_id}>
                            {report.facts.numbers[team.team_id]?.line_breaking.half} /{' '}
                            {report.facts.numbers[team.team_id]?.line_breaking.match}
                          </td>
                        ))}
                      </tr>
                    </tbody>
                  </table>
                </div>
                <h3>{t.formation}</h3>
                <div className="formation-comparison">
                  {teams.map((team) => (
                    <div key={team.team_id}>
                      <h4>{localizedName(team, language)}</h4>
                      <FormationDiagram
                        title={t.withBall}
                        formation={report.facts.tactics[team.team_id]?.formation.in_possession}
                      />
                      <FormationDiagram
                        title={t.withoutBall}
                        formation={report.facts.tactics[team.team_id]?.formation.out_of_possession}
                      />
                    </div>
                  ))}
                </div>
                <div className="table-scroll">
                  <table>
                    <caption>{t.tacticalPicture}</caption>
                    <thead>
                      <tr>
                        <th>{t.metric}</th>
                        {teams.map((team) => (
                          <th key={team.team_id}>{localizedName(team, language)}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {[t.area, t.line, t.space, t.counters].map((label, i) => (
                        <tr key={label}>
                          <th>{label}</th>
                          {teams.map((team) => {
                            const facts = report.facts.tactics[team.team_id];
                            return (
                              <td key={team.team_id}>
                                {displayNumber(
                                  i === 0
                                    ? facts?.shape.area_m2
                                    : i === 1
                                      ? facts?.shape.defensive_line_height_m
                                      : i === 2
                                        ? facts?.control?.window.whole_pct
                                        : facts?.counters.count,
                                )}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <h3>{t.standouts}</h3>
                <ul>
                  {Object.entries(report.facts.standouts).map(([key, values]) => (
                    <li key={key}>
                      <strong>{metric(key)}:</strong>{' '}
                      {values.map((v) => `${playerName(v.player_id)} (${v.value})`).join(' · ')}
                    </li>
                  ))}
                </ul>
                <h3>{t.keyMoments}</h3>
                <ul>
                  {report.facts.moments.map((m) => (
                    <li key={m.moment_id}>
                      <button
                        className="text-button"
                        onClick={() => {
                          setPhase(null);
                          onSeek(m.game_clock_s);
                        }}
                      >
                        {t.view} · <bdi>{clockLabel(m.game_clock_s)}</bdi>
                      </button>
                    </li>
                  ))}
                </ul>
                {phase === 'half' && (
                  <>
                    <h3>{t.whatToWatch}</h3>
                    <p>{t.watchHint}</p>
                    {report.facts.coach_notes.slice(-3).map((n) => (
                      <p key={n.note_id}>
                        {teams.find((x) => x.team_id === n.team_id) &&
                          localizedName(
                            teams.find((x) => x.team_id === n.team_id)!,
                            language,
                          )}{' '}
                        · <bdi>{clockLabel(n.game_clock_s)}</bdi>
                        {'counter_count' in n.facts ? (
                          <>
                            {' '}
                            · {t.counters}: <bdi>{String(n.facts.counter_count)}</bdi>
                          </>
                        ) : (
                          <>
                            {' · '}
                            {t.before}:{' '}
                            <bdi>
                              {String(
                                n.facts.before_label ??
                                  n.facts.before_m ??
                                  n.facts.before_m2 ??
                                  n.facts.before_column ??
                                  '—',
                              )}
                            </bdi>
                            {' → '}
                            {t.after}:{' '}
                            <bdi>
                              {String(
                                n.facts.after_label ??
                                  n.facts.after_m ??
                                  n.facts.after_m2 ??
                                  n.facts.after_column ??
                                  '—',
                              )}
                            </bdi>
                            {n.facts.after_m != null ? ' m' : n.facts.after_m2 != null ? ' m²' : ''}
                          </>
                        )}
                      </p>
                    ))}
                  </>
                )}
                <button
                  className="secondary-button"
                  onClick={() =>
                    openEvidence(report.facts, report.evidence.evidence_event_ids, [
                      report.evidence.frame_range,
                    ])
                  }
                >
                  {t.source}
                </button>
              </>
            )}
          </div>
        </Dialog>
      )}
      {evidence && (
        <Evidence
          matchId={metadata.match_id}
          language={language}
          {...evidence}
          onClose={() => setEvidence(null)}
        />
      )}
    </section>
  );
}
