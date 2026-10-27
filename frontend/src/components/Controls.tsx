import { BookOpen, Heart, Pause, Play, ScanLine, UserRound } from 'lucide-react';
import { useState } from 'react';
import { clockLabel, copy, localizedName, personas } from '../i18n';
import type { Language, Metadata, Preferences } from '../types';
const personaIcons = { beginner: BookOpen, tactical: ScanLine, player: UserRound, club: Heart };

export function PreferencesPanel({
  preference,
  metadata,
  onChange,
}: {
  preference: Preferences;
  metadata: Metadata | null;
  onChange: (p: Preferences) => void;
}) {
  const t = copy[preference.language];
  const players = metadata ? [...metadata.home.players, ...metadata.away.players] : [];
  return (
    <aside className="preferences-panel">
      <span className="eyebrow">{t.perspective}</span>
      <h2>{t.choose}</h2>
      <div className="perspective-options">
        {personas.map((persona) => {
          const Icon = personaIcons[persona];
          return (
            <button
              key={persona}
              className={`perspective-option ${preference.persona === persona ? 'selected' : ''}`}
              aria-pressed={preference.persona === persona}
              onClick={() => onChange({ ...preference, persona })}
            >
              <span className="persona-icon">
                <Icon size={20} />
              </span>
              <span>
                <strong>{t[persona]}</strong>
                <small>{t[`${persona}Hint`]}</small>
              </span>
            </button>
          );
        })}
      </div>
      <label className="field-label">
        {t.language}
        <select
          value={preference.language}
          onChange={(e) => onChange({ ...preference, language: e.target.value as Language })}
        >
          <option value="en">English</option>
          <option value="ar">العربية</option>
        </select>
      </label>
      <label className="field-label">
        {t.favoritePlayer}
        <select
          value={preference.player}
          disabled={!metadata}
          onChange={(e) => onChange({ ...preference, player: e.target.value })}
        >
          {players.map((p) => (
            <option key={p.player_id} value={p.player_id}>
              {localizedName(p, preference.language)} · {p.shirt_number}
            </option>
          ))}
        </select>
      </label>
      <label className="field-label">
        {t.favoriteClub}
        <select
          value={preference.club}
          disabled={!metadata}
          onChange={(e) => onChange({ ...preference, club: e.target.value })}
        >
          {metadata &&
            [metadata.home, metadata.away].map((team) => (
              <option key={team.team_id} value={team.team_id}>
                {localizedName(team, preference.language)}
              </option>
            ))}
        </select>
      </label>
      <div className="perspective-note">
        <span className="tiny-line" />
        <p>
          {preference.language === 'ar'
            ? 'يتغيّر التعليق. تبقى الحقائق الموثّقة كما هي.'
            : 'The commentary changes. The verified facts stay the same.'}
        </p>
      </div>
    </aside>
  );
}

export function Transport({
  clock,
  duration,
  playback,
  speed,
  language,
  enabled,
  mode,
  canControl,
  hold,
  onHold,
  onControl,
}: {
  clock: number;
  duration: number;
  playback: string;
  speed: number;
  language: Language;
  enabled: boolean;
  mode: 'demo' | 'live';
  canControl: boolean;
  hold: boolean;
  onHold: (v: boolean) => void;
  onControl: (action: string, value?: number) => Promise<void>;
}) {
  const t = copy[language];
  const [seek, setSeek] = useState<number | null>(null);
  const commit = () => {
    if (seek !== null) {
      void onControl('seek', seek);
      setSeek(null);
    }
  };
  const disabled = !enabled || !canControl || (mode === 'live' && playback === 'finished');
  const playable = playback === 'paused' || playback === 'finished' || playback === 'idle';
  return (
    <div className="transport">
      <div className="transport-main">
        <button
          className="play-button"
          disabled={disabled}
          aria-label={playable ? t.resume : t.pause}
          onClick={() => void onControl(playable ? 'resume' : 'pause')}
        >
          {playable ? <Play size={20} fill="currentColor" /> : <Pause size={20} />}
        </button>
        <bdi className="viewer-clock" data-testid="viewer-clock">
          {clockLabel(clock)}
        </bdi>
        <span className="clock-divider">/</span>
        <bdi className="muted duration">{clockLabel(duration)}</bdi>
        <input
          className="seek-range"
          type="range"
          aria-label={t.seek}
          min="0"
          max={(duration - 1) / 60}
          step="0.1"
          value={seek ?? clock / 60}
          disabled={disabled}
          onChange={(e) => setSeek(Number(e.target.value))}
          onPointerUp={commit}
          onKeyUp={(e) => {
            if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) commit();
          }}
        />
        <label className="speed-select">
          <span className="sr-only">{t.speed}</span>
          <select
            aria-label={t.speed}
            value={speed}
            disabled={disabled}
            onChange={(e) => void onControl('speed', Number(e.target.value))}
          >
            {(mode === 'demo' ? [1, 5, 10, 20, 60] : [1, 5, 10, 20]).map((n) => (
              <option key={n} value={n}>
                {n}×
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="transport-meta">
        <label className="hold-control">
          <input
            type="checkbox"
            checked={hold}
            onChange={(e) => onHold(e.target.checked)}
            disabled={mode === 'live'}
          />
          {language === 'ar' ? 'توقف عند الأهداف' : 'Pause at goals'}
        </label>
        <span>
          {playback === 'paused'
            ? language === 'ar'
              ? 'متوقف مؤقتًا · استكشف اللحظة'
              : 'Paused · explore this moment'
            : mode === 'demo'
              ? t.demoHint
              : t.liveHint}
        </span>
      </div>
    </div>
  );
}
