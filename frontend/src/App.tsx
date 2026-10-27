import { useEffect, useRef, useState } from 'react';
import {
  ArrowRight,
  BarChart3,
  BookOpen,
  Braces,
  CircleDot,
  FlaskConical,
  Layers,
  Play,
  RotateCcw,
  ShieldCheck,
} from 'lucide-react';
import { request } from './api';
import { copy, localizedName, clockLabel } from './i18n';
import { activeOverlays } from './stream';
import { useMatch } from './useMatch';
import { useFacts } from './useFacts';
import { useNavigation, screenCopy } from './navigation';
import type { Health, Metadata, Moment, Overlay, Preferences, Scenario, Language } from './types';
import { PreferencesPanel, Transport } from './components/Controls';
import { EvidenceDialog, RecapDialog } from './components/Dialogs';
import { Feed } from './components/Feed';
import { Commentary, Indices, PlayerTicker } from './components/Insights';
import { MatchStage } from './components/MatchStage';
import { Comparison } from './components/Comparison';
import { MomentTimeline } from './components/MomentTimeline';
import { JudgeLab } from './components/JudgeLab';
const navIcons = {
  match: Play,
  perspectives: Layers,
  insights: BarChart3,
  lab: FlaskConical,
  feed: Braces,
};
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
  const { view, navigate, headingRef } = useNavigation();
  const [matchId, setMatchId] = useState('match_001');
  const [metadata, setMetadata] = useState<Metadata | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [moments, setMoments] = useState<Moment[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [bootError, setBootError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [selectedOverlay, setSelectedOverlay] = useState<Overlay | null>(null);
  const [dialog, setDialog] = useState<'recap' | null>(null);
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
    setSelectedOverlay(null);
    setDialog(null);
  }, [view]);
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
        !['match', 'perspectives', 'insights'].includes(view) ||
        document.querySelector('dialog[open]') ||
        !(event.target instanceof HTMLElement) ||
        event.target.closest('input,select,textarea,button,a')
      )
        return;
      if (event.code === 'Space' && active && match.canControl) {
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
    view,
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

  const labels = screenCopy[preference.language];
  const startDemo = () => {
    void match.connect('demo', matchId);
    navigate('match');
  };
  const transport = (
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
  );
  const timeline = (
    <MomentTimeline
      highlights={highlights}
      language={preference.language}
      disabled={match.mode === 'live' && active && !match.canControl}
      onJump={jump}
    />
  );
  const preferences = (
    <PreferencesPanel preference={preference} metadata={meta} onChange={setPreference} />
  );
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        {preference.language === 'ar' ? 'انتقل إلى المحتوى' : 'Skip to content'}
      </a>
      <header className="app-header">
        <div className="header-top">
          <a className="brand" href="#/match" aria-label="EveryFan home">
            <span className="brand-symbol">
              <CircleDot size={25} />
            </span>
            EveryFan<span className="brand-period">.</span>
          </a>
          <span className="brand-descriptor">{labels.tagline}</span>
          <div className="header-utilities">
            <span className="connection-pill" role="status">
              <span className={active ? 'status-dot connected' : 'status-dot'} />
              {
                t[
                  match.connection === 'connected'
                    ? 'connected'
                    : match.connection === 'connecting'
                      ? 'connecting'
                      : match.connection === 'idle'
                        ? 'idle'
                        : 'closed'
                ]
              }
            </span>
            <label className="language-switch">
              <span className="sr-only">{t.language}</span>
              <select
                value={preference.language}
                onChange={(e) =>
                  setPreference((p) => ({ ...p, language: e.target.value as Language }))
                }
              >
                <option value="en">English</option>
                <option value="ar">العربية</option>
              </select>
            </label>
          </div>
        </div>
        <nav
          className="screen-nav"
          aria-label={preference.language === 'ar' ? 'التنقل الرئيسي' : 'Main navigation'}
        >
          {(['match', 'perspectives', 'insights', 'lab', 'feed'] as const).map((id) => {
            const Icon = navIcons[id];
            return (
              <button
                key={id}
                aria-current={view === id ? 'page' : undefined}
                onClick={() => navigate(id)}
              >
                <Icon size={18} />
                <span>{labels[id]}</span>
              </button>
            );
          })}
        </nav>
      </header>
      <main id="main-content" className={`workspace workspace-${view}`}>
        <div className="page-heading">
          <div>
            <span className="eyebrow">{labels.eyebrow[view]}</span>
            <h1 ref={headingRef} tabIndex={-1}>
              {labels.titles[view]}
            </h1>
            <p>{labels.descriptions[view]}</p>
          </div>
          <span className="page-symbol" aria-hidden="true">
            {view === 'match' ? (
              <CircleDot />
            ) : view === 'perspectives' ? (
              <Layers />
            ) : view === 'insights' ? (
              <BarChart3 />
            ) : view === 'lab' ? (
              <ShieldCheck />
            ) : (
              <Braces />
            )}
          </span>
        </div>
        <section className="match-context" aria-label={labels.currentMatch}>
          <div className="match-context-name">
            <span className="status-dot" />
            <strong>
              {meta ? (
                <>
                  {localizedName(meta.home, preference.language)} <span className="versus">vs</span>{' '}
                  {localizedName(meta.away, preference.language)}
                </>
              ) : (
                t.loading
              )}
            </strong>
            <span className="context-clock" dir="ltr">
              {match.stream.clock ? clockLabel(match.stream.clock) : '—'}
            </span>
          </div>
          <label>
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
              <RotateCcw size={16} />
              {t.retry}
            </button>
          </div>
        )}
        <div className="screen-content" key={view}>
          {view === 'match' && (
            <div className="watch-layout">
              <div className="watch-main">
                <MatchStage
                  meta={meta}
                  match={match}
                  preference={preference}
                  setPreference={setPreference}
                  hold={hold}
                  setHold={setHold}
                  demoReady={demoReady}
                  onRecap={() => setDialog('recap')}
                />
                <Commentary
                  overlays={overlays}
                  language={preference.language}
                  onInspect={setSelectedOverlay}
                />
                <button className="destination-link" onClick={() => navigate('insights')}>
                  <BarChart3 size={18} />
                  {labels.exploreInsights}
                  <ArrowRight size={18} />
                </button>
              </div>
              <div className="watch-sidebar">
                {preferences}
                {timeline}
              </div>
            </div>
          )}
          {view === 'perspectives' && (
            <>
              <div className="screen-toolbar">
                <span>
                  <Layers size={18} />
                  {labels.synchronized}
                </span>
                {!active && (
                  <button
                    className="primary-button"
                    disabled={!demoReady}
                    onClick={() => void match.connect('demo', matchId)}
                  >
                    <Play size={16} />
                    {t.demo}
                  </button>
                )}
              </div>
              <div className="perspectives-layout">
                <div>
                  <Comparison
                    stream={match.stream}
                    preference={preference}
                    onInspect={setSelectedOverlay}
                  />
                  {transport}
                </div>
                <div className="watch-sidebar">
                  {preferences}
                  {timeline}
                </div>
              </div>
            </>
          )}
          {view === 'insights' && (
            <>
              <div className="screen-toolbar">
                <span>
                  <ShieldCheck size={18} />
                  {labels.measuredOnly}
                </span>
                {!active && (
                  <button
                    className="primary-button"
                    disabled={!demoReady}
                    onClick={() => void match.connect('demo', matchId)}
                  >
                    <Play size={16} />
                    {t.demo}
                  </button>
                )}
              </div>
              <div className="insights-layout">
                <div className="insights-main">
                  {meta && (
                    <Indices
                      metadata={meta}
                      stats={facts.stats}
                      language={preference.language}
                      history={facts.history}
                    />
                  )}
                  <section className="insight-player">
                    <div className="section-heading">
                      <h2>{t.player}</h2>
                      <label>
                        <span className="sr-only">{t.favoritePlayer}</span>
                        <select
                          value={preference.player}
                          onChange={(e) => setPreference((p) => ({ ...p, player: e.target.value }))}
                        >
                          {meta &&
                            [...meta.home.players, ...meta.away.players].map((p) => (
                              <option key={p.player_id} value={p.player_id}>
                                {localizedName(p, preference.language)}
                              </option>
                            ))}
                        </select>
                      </label>
                    </div>
                    <PlayerTicker stats={facts.player} language={preference.language} />
                  </section>
                  {facts.error && <p className="notice-banner">{t.statsUnavailable}</p>}
                  <div className="insights-controls">{transport}</div>
                </div>
                {timeline}
              </div>
            </>
          )}
          {view === 'lab' && (
            <JudgeLab
              language={preference.language}
              preference={preference}
              matchId={matchId}
              momentId={laboratoryMoment?.moment_id}
              demoReady={demoReady}
              connecting={match.connection === 'connecting'}
              onDemo={startDemo}
              onLive={() => {
                void match.connect('live', matchId);
                navigate('match');
              }}
            />
          )}
          {view === 'feed' && (
            <Feed
              matchId={matchId}
              language={preference.language}
              mode={match.mode}
              onInspect={setSelectedOverlay}
            />
          )}
        </div>
        <footer className="footer">
          <span>
            EveryFan. <span className="muted">{labels.tagline}</span>
          </span>
          <span>{t.fictional}</span>
          <button className="text-button" disabled={!meta} onClick={() => setDialog('recap')}>
            <BookOpen size={16} />
            {t.recap}
          </button>
        </footer>
      </main>
      {selectedOverlay && (
        <EvidenceDialog
          overlay={selectedOverlay}
          language={preference.language}
          onClose={() => setSelectedOverlay(null)}
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
            navigate('match');
            if (active) void match.control('seek', minute);
            else void match.connect('demo', matchId, minute);
          }}
        />
      )}
    </div>
  );
}
