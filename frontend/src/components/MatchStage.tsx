import { CircleDot, Play, Sparkles } from 'lucide-react';
import { copy, clockLabel } from '../i18n';
import type { Metadata, Preferences } from '../types';
import type { useMatch } from '../useMatch';
import { Pitch } from './Pitch';
import { Transport } from './Controls';
export function MatchStage({
  meta,
  match,
  preference,
  onPlayer,
  hold,
  setHold,
  demoReady,
  onRecap,
  showStartButton = true,
}: {
  meta: Metadata | null;
  match: ReturnType<typeof useMatch>;
  preference: Preferences;
  onPlayer: (player: string) => void;
  hold: boolean;
  setHold: (v: boolean) => void;
  demoReady: boolean;
  onRecap: () => void;
  showStartButton?: boolean;
}) {
  const t = copy[preference.language];
  const active = match.connection === 'connected';
  const matchId = meta?.match_id || 'match_001';
  return (
    <>
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
          <button className="text-button story-button" disabled={!meta} onClick={() => onRecap()}>
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
            onSelect={onPlayer}
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
            {demoReady && showStartButton && (
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
      {match.mode === 'live' && !match.canControl && <p className="notice-banner">{t.readonly}</p>}
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
    </>
  );
}
