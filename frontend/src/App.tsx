import { useEffect, useRef, useState } from 'react';
import {
  ArrowUpRight,
  ChevronRight,
  CircleDot,
  FlaskConical,
  Layers,
  Play,
  Radio,
  RotateCcw,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import { request } from './api';
import { clockLabel, copy, localizedName } from './i18n';
import { activeOverlays } from './stream';
import { useMatch } from './useMatch';
import { useFacts } from './useFacts';
import type { Health, Metadata, Moment, Overlay, Preferences, Scenario } from './types';
import { PreferencesPanel, Transport } from './components/Controls';
import { BreakDialog, EvidenceDialog, RecapDialog } from './components/Dialogs';
import { Feed } from './components/Feed';
import { Commentary, Indices, PlayerTicker } from './components/Insights';
import { OverlayCard } from './components/OverlayCard';
import { Pitch } from './components/Pitch';

function readPreferences(): Preferences {
  const defaults: Preferences = { persona: 'beginner', language: 'en', club: '', player: '' };
  try {
    const stored: unknown = JSON.parse(localStorage.getItem('everyfan.preferences.v1') || 'null');
    if (
      stored &&
      typeof stored === 'object' &&
      'persona' in stored &&
      ['beginner', 'tactical', 'player', 'club'].includes(String(stored.persona)) &&
      'language' in stored &&
      ['en', 'ar'].includes(String(stored.language))
    )
      return {
        ...defaults,
        persona: stored.persona as Preferences['persona'],
        language: stored.language as Preferences['language'],
        club: 'club' in stored ? String(stored.club) : '',
        player: 'player' in stored ? String(stored.player) : '',
      };
  } catch {
    /* Preferences are optional in private or restricted browsers. */
  }
  return defaults;
}

export default function App() {
  const [preference, setPreference] = useState(readPreferences);
  const [view, setView] = useState<'watch' | 'compare' | 'feed'>('watch');
  const [matchId, setMatchId] = useState('match_001');
  const [metadata, setMetadata] = useState<Metadata | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [moments, setMoments] = useState<Moment[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [bootError, setBootError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [selectedOverlay, setSelectedOverlay] = useState<Overlay | null>(null);
  const [dialog, setDialog] = useState<'break' | 'recap' | null>(null);
  const [hold, setHold] = useState(true);
  const pausedMoments = useRef(new Set<string>());
  const match = useMatch();
  const t = copy[preference.language];
  const meta = match.stream.metadata || metadata;
  const active = match.connection === 'connected';
  const facts = useFacts(
    matchId,
    match.stream.runId,
    match.stream.clock,
    preference.player,
    active,
  );
  const overlays = activeOverlays(match.stream, preference);
  const demoReady = !!health?.demo_bundles.some((b) => b.match_id === matchId && !b.stale);
  useEffect(() => {
    document.documentElement.lang = preference.language;
    document.documentElement.dir = preference.language === 'ar' ? 'rtl' : 'ltr';
    try {
      localStorage.setItem('everyfan.preferences.v1', JSON.stringify(preference));
    } catch {
      /* Storage can be unavailable. */
    }
  }, [preference]);
  useEffect(() => {
    const controller = new AbortController();
    setBootError('');
    setMetadata(null);
    setMoments([]);
    Promise.all([
      request<Health>('/api/health', { signal: controller.signal }),
      request<Scenario[]>('/api/scenarios', { signal: controller.signal }),
      request<Metadata>(`/api/matches/${matchId}/metadata`, { signal: controller.signal }),
      request<Moment[]>(`/api/matches/${matchId}/moments?min_importance=0.5`, {
        signal: controller.signal,
      }),
    ])
      .then(([h, s, m, ms]) => {
        if (controller.signal.aborted) return;
        setHealth(h);
        setScenarios(s);
        setMetadata(m);
        setMoments(ms);
        setPreference((p) => ({
          ...p,
          club: [m.home.team_id, m.away.team_id].includes(p.club) ? p.club : m.home.team_id,
          player: [...m.home.players, ...m.away.players].some((x) => x.player_id === p.player)
            ? p.player
            : (m.home.players.find((x) => x.position === 'ST') || m.home.players[0])?.player_id ||
              '',
        }));
      })
      .catch((cause) => {
        if (!controller.signal.aborted)
          setBootError(cause instanceof Error ? cause.message : 'Unable to load the match.');
      });
    return () => controller.abort();
  }, [matchId, refresh]);
  useEffect(() => {
    pausedMoments.current.clear();
    setSelectedOverlay(null);
    setDialog(null);
  }, [match.stream.runId]);
  useEffect(() => {
    if (!hold || match.mode !== 'demo' || match.stream.playback !== 'playing') return;
    const moment = match.stream.moments.find(
      (m) =>
        m.type === 'goal' &&
        match.stream.clock >= m.game_clock_s + 1 &&
        match.stream.clock < m.game_clock_s + 6 &&
        !pausedMoments.current.has(m.moment_id),
    );
    if (moment) {
      pausedMoments.current.add(moment.moment_id);
      void match.control('pause');
    }
  }, [hold, match.mode, match.stream, match.control]);
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (
        document.querySelector('dialog[open]') ||
        !(event.target instanceof HTMLElement) ||
        event.target.closest('input,select,textarea,button,a')
      )
        return;
      if (event.code === 'Space' && active) {
        event.preventDefault();
        void match.control(match.stream.playback === 'paused' ? 'resume' : 'pause');
      }
      if (['ArrowLeft', 'ArrowRight'].includes(event.key) && active && match.canControl) {
        event.preventDefault();
        void match.control(
          'seek',
          Math.max(
            0,
            Math.min(
              (meta?.match_duration_s || 5400) / 60 - 0.1,
              match.stream.clock / 60 + (event.key === 'ArrowRight' ? 1 : -1),
            ),
          ),
        );
      }
    };
    document.addEventListener('keydown', key);
    return () => document.removeEventListener('keydown', key);
  }, [
    active,
    match.control,
    match.canControl,
    match.stream.playback,
    match.stream.clock,
    meta?.match_duration_s,
  ]);
  const jump = (moment: Moment) => {
    if (moment.player_id) setPreference((p) => ({ ...p, player: moment.player_id! }));
    if (active && match.canControl)
      void match.control('seek', Math.max(0, (moment.game_clock_s - 2) / 60));
    else void match.connect('demo', matchId, Math.max(0, (moment.game_clock_s - 2) / 60));
  };
  const highlights = moments.filter((m) => m.type === 'goal' || m.type === 'red_card');
  const laboratoryMoment = highlights.find((m) => m.type === 'goal') || moments[0];
  return (
    <>
      <a className="skip-link" href="#main-content">
        {preference.language === 'ar' ? 'انتقل إلى المحتوى' : 'Skip to match'}
      </a>
      <header className="topbar">
        <a className="brand" href="#" aria-label="EveryFan home" onClick={() => setView('watch')}>
          <span className="brand-symbol">
            <CircleDot size={24} />
          </span>
          EveryFan<span className="brand-period">.</span>
        </a>
        <nav aria-label={preference.language === 'ar' ? 'التنقل الرئيسي' : 'Main navigation'}>
          {(['watch', 'compare', 'feed'] as const).map((v) => (
            <button
              key={v}
              aria-current={view === v ? 'page' : undefined}
              onClick={() => setView(v)}
            >
              {v === 'compare' && <Layers size={15} />}
              <span>{t[v]}</span>
            </button>
          ))}
        </nav>
        <div className="connection-pill" role="status">
          <span className={active ? 'status-dot connected' : 'status-dot'} />
          <span>
            {
              t[
                match.connection === 'idle'
                  ? 'idle'
                  : match.connection === 'connecting'
                    ? 'connecting'
                    : match.connection === 'connected'
                      ? 'connected'
                      : match.connection === 'error'
                        ? 'error'
                        : 'closed'
              ]
            }
          </span>
        </div>
      </header>
      <main id="main-content">
        <section className="match-heading">
          <div>
            <span className="eyebrow">{t.eyebrow}</span>
            <h1>
              {meta ? (
                <>
                  {localizedName(meta.home, preference.language)} <span className="versus">vs</span>{' '}
                  {localizedName(meta.away, preference.language)}
                </>
              ) : (
                'EveryFan'
              )}
              <span className="synthetic-tag">
                {preference.language === 'ar' ? 'مباراة خيالية' : 'SYNTHETIC MATCH'}
              </span>
            </h1>
            <p>
              {meta?.competition || t.fictional} <span className="muted">· {meta?.venue}</span>
            </p>
          </div>
          <label className="scenario-picker">
            <span className="sr-only">{t.chooseMatch}</span>
            <select
              value={matchId}
              onChange={(e) => {
                match.disconnect();
                setMatchId(e.target.value);
              }}
            >
              {scenarios.length ? (
                scenarios.map((s) => (
                  <option key={s.match_id} value={s.match_id}>
                    {s.title}
                  </option>
                ))
              ) : (
                <option value="match_001">{t.loading}</option>
              )}
            </select>
          </label>
        </section>
        {(bootError || match.error) && (
          <div className="error-banner" role="alert">
            <span>{bootError || match.error}</span>
            <button
              className="text-button"
              onClick={() => {
                setRefresh((n) => n + 1);
                if (match.connection !== 'idle')
                  void match.connect(match.mode, matchId, match.stream.clock / 60);
              }}
            >
              <RotateCcw size={15} />
              {t.retry}
            </button>
          </div>
        )}
        <section className="judge-actions" aria-label="Judge mode">
          <button
            className="judge-action primary-action"
            disabled={!demoReady || match.connection === 'connecting'}
            onClick={() => {
              setView('watch');
              void match.connect('demo', matchId);
            }}
          >
            <span className="action-icon">
              <Play size={21} fill="currentColor" />
            </span>
            <span>
              <strong>{t.demo}</strong>
              <small>{t.demoHint}</small>
            </span>
            <ArrowUpRight size={19} />
          </button>
          <button
            className="judge-action"
            disabled={!meta || match.connection === 'connecting'}
            onClick={() => {
              setView('watch');
              void match.connect('live', matchId);
            }}
          >
            <span className="action-icon">
              <Radio size={21} />
            </span>
            <span>
              <strong>{t.live}</strong>
              <small>{t.liveHint}</small>
            </span>
            <ArrowUpRight size={19} />
          </button>
          <button
            className="judge-action"
            disabled={!laboratoryMoment}
            onClick={() => setDialog('break')}
          >
            <span className="action-icon">
              <FlaskConical size={21} />
            </span>
            <span>
              <strong>{t.break}</strong>
              <small>{t.breakHint}</small>
            </span>
            <ArrowUpRight size={19} />
          </button>
        </section>
        {view === 'feed' ? (
          <Feed
            matchId={matchId}
            language={preference.language}
            mode={match.mode}
            onInspect={setSelectedOverlay}
          />
        ) : (
          <div className="broadcast-layout">
            <PreferencesPanel preference={preference} metadata={meta} onChange={setPreference} />
            <div className="broadcast-main">
              <section className="broadcast-stage" aria-label={t.watch}>
                <div className="stage-top">
                  <span className="stage-mode">
                    <span className={active ? 'status-dot connected' : 'status-dot'} />
                    {match.stream.playback === 'finished'
                      ? preference.language === 'ar'
                        ? 'نهاية المباراة'
                        : 'FULL TIME'
                      : match.mode === 'demo'
                        ? 'DEMO'
                        : 'LIVE'}{' '}
                    <span>{match.stream.playback === 'paused' ? 'Ⅱ' : active ? '●' : ''}</span>
                  </span>
                  <div
                    className="scorebug"
                    dir="ltr"
                    aria-label={preference.language === 'ar' ? 'نتيجة المباراة' : 'Match score'}
                  >
                    <span>{meta?.home.short_name || '—'}</span>
                    <strong data-testid="score-home">
                      {meta && match.stream.matchState
                        ? (match.stream.matchState.score[meta.home.team_id] ?? '—')
                        : '—'}
                    </strong>
                    <span className="score-dash">:</span>
                    <strong data-testid="score-away">
                      {meta && match.stream.matchState
                        ? (match.stream.matchState.score[meta.away.team_id] ?? '—')
                        : '—'}
                    </strong>
                    <span>{meta?.away.short_name || '—'}</span>
                    <bdi className="score-clock">
                      {active || match.stream.clock ? clockLabel(match.stream.clock) : '—'}
                    </bdi>
                  </div>
                  <button
                    className="text-button story-button"
                    disabled={!meta}
                    onClick={() => setDialog('recap')}
                  >
                    <Sparkles size={15} />
                    {t.recap}
                  </button>
                </div>
                {meta ? (
                  <Pitch
                    metadata={meta}
                    frame={match.stream.frame}
                    clock={match.stream.clock}
                    selected={preference.player}
                    language={preference.language}
                    moments={match.stream.moments}
                    onSelect={(player) =>
                      setPreference((p) => ({ ...p, player, persona: 'player' }))
                    }
                  />
                ) : (
                  <div className="pitch-skeleton" role="status">
                    {t.loading}
                  </div>
                )}
                {!match.stream.frame && (
                  <div className="stage-welcome">
                    <span className="welcome-mark">
                      <CircleDot size={38} />
                    </span>
                    <h2>{t.ready}</h2>
                    <p>{t.readyHint}</p>
                    {demoReady && (
                      <button
                        className="primary-button"
                        onClick={() => void match.connect('demo', matchId)}
                      >
                        <Play size={17} />
                        {t.demo}
                      </button>
                    )}
                  </div>
                )}
                <Transport
                  clock={match.stream.clock}
                  duration={meta?.match_duration_s || 5400}
                  playback={match.stream.playback}
                  speed={match.stream.speed}
                  language={preference.language}
                  enabled={active}
                  mode={match.mode}
                  canControl={match.canControl}
                  hold={hold}
                  onHold={setHold}
                  onControl={match.control}
                />
              </section>
              {match.mode === 'live' && !match.canControl && (
                <p className="notice-banner">{t.readonly}</p>
              )}
              {match.mode === 'live' && match.canControl && active && (
                <button
                  className="text-button stop-live"
                  onClick={async () => {
                    await match.control('stop');
                    match.disconnect();
                  }}
                >
                  {t.stop}
                </button>
              )}
              {view === 'compare' ? (
                <section className="comparison" aria-label={t.compare}>
                  <div className="section-heading">
                    <div>
                      <span className="eyebrow">
                        {preference.language === 'ar'
                          ? 'اللحظة نفسها. أربع زوايا.'
                          : 'SAME MOMENT. FOUR PERSPECTIVES.'}
                      </span>
                      <h2>{t.compare}</h2>
                    </div>
                    <ShieldCheck size={20} />
                  </div>
                  <div className="comparison-grid">
                    {(
                      [
                        { persona: 'beginner', language: 'en' },
                        { persona: 'tactical', language: 'en' },
                        { persona: 'player', language: 'en' },
                        { persona: 'beginner', language: 'ar' },
                      ] as const
                    ).map((p) => {
                      const items = activeOverlays(match.stream, { ...preference, ...p });
                      return (
                        <section
                          className="comparison-pane"
                          key={`${p.persona}-${p.language}`}
                          dir={p.language === 'ar' ? 'rtl' : 'ltr'}
                          lang={p.language}
                        >
                          <h3>
                            {copy[p.language][p.persona]} <span>{p.language.toUpperCase()}</span>
                          </h3>
                          {items.length ? (
                            items.map((o) => (
                              <OverlayCard
                                key={o.overlay_id}
                                overlay={o}
                                language={p.language}
                                onInspect={setSelectedOverlay}
                                compact
                              />
                            ))
                          ) : (
                            <p className="comparison-empty">{copy[p.language].waiting}</p>
                          )}
                        </section>
                      );
                    })}
                  </div>
                </section>
              ) : (
                <Commentary
                  overlays={overlays}
                  language={preference.language}
                  onInspect={setSelectedOverlay}
                />
              )}
              {meta && (
                <Indices
                  metadata={meta}
                  stats={facts.stats}
                  language={preference.language}
                  history={facts.history}
                />
              )}
              {facts.error && <p className="notice-banner">{t.statsUnavailable}</p>}
              {preference.persona === 'player' && (
                <PlayerTicker stats={facts.player} language={preference.language} />
              )}
            </div>
            <aside className="moments-panel">
              <div className="section-heading">
                <h2>{t.timeline}</h2>
                <CircleDot size={16} />
              </div>
              <p className="muted panel-caption">
                {preference.language === 'ar'
                  ? 'انتقل إلى لحظة بارزة في المباراة المسجلة.'
                  : 'Jump into a highlight in the recorded match.'}
              </p>
              <div className="highlight-list">
                {highlights.map((m) => (
                  <button
                    key={m.moment_id}
                    disabled={match.mode === 'live' && active && !match.canControl}
                    onClick={() => jump(m)}
                    aria-label={`${t.jump} ${clockLabel(m.game_clock_s)}`}
                  >
                    <bdi>{clockLabel(m.game_clock_s)}</bdi>
                    <span>
                      {preference.language === 'ar'
                        ? m.type === 'goal'
                          ? 'هدف'
                          : 'بطاقة حمراء'
                        : m.type.replaceAll('_', ' ')}
                    </span>
                    <ChevronRight size={15} />
                  </button>
                ))}
              </div>
              <div className="moment-history">
                {match.stream.moments
                  .filter((m) => m.game_clock_s <= match.stream.clock)
                  .slice(-5)
                  .reverse()
                  .map((m) => (
                    <div key={m.moment_id}>
                      <span className="timeline-dot" />
                      <div>
                        <bdi>{clockLabel(m.game_clock_s)}</bdi>
                        <p>{m.type.replaceAll('_', ' ')}</p>
                      </div>
                    </div>
                  ))}
              </div>
              <div className="evidence-prompt">
                <ShieldCheck size={25} />
                <h3>{t.evidence}</h3>
                <p>{t.evidenceHint}</p>
              </div>
            </aside>
          </div>
        )}
        <footer className="footer">
          <span>
            EveryFan. <span className="muted">One match. Millions of stories.</span>
          </span>
          <span>{t.fictional}</span>
          <small>{t.keyboard}</small>
        </footer>
      </main>
      {selectedOverlay && (
        <EvidenceDialog
          overlay={selectedOverlay}
          language={preference.language}
          onClose={() => setSelectedOverlay(null)}
        />
      )}
      {dialog === 'break' && laboratoryMoment && (
        <BreakDialog
          language={preference.language}
          preference={preference}
          matchId={matchId}
          momentId={laboratoryMoment.moment_id}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog === 'recap' && meta && (
        <RecapDialog
          language={preference.language}
          preference={preference}
          matchId={matchId}
          mode={match.mode}
          until={
            match.stream.playback === 'finished' || (match.mode === 'demo' && !active)
              ? meta.match_duration_s
              : Math.floor(match.stream.clock)
          }
          onClose={() => setDialog(null)}
          onSeek={(minute) => {
            if (active) void match.control('seek', minute);
            else void match.connect('demo', matchId, minute);
          }}
        />
      )}
    </>
  );
}
