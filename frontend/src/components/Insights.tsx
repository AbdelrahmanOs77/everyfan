import { Activity, ArrowUpRight, CircleHelp, Flame, Gauge, ShieldCheck } from 'lucide-react';
import { clockLabel, copy, displayNumber, localizedName } from '../i18n';
import type { Language, Metadata, Overlay, PlayerStats, Stats } from '../types';
import { OverlayCard } from './OverlayCard';

export function Indices({
  stats,
  metadata,
  language,
  history,
}: {
  stats: Stats | null;
  metadata: Metadata;
  language: Language;
  history: Stats[];
}) {
  const t = copy[language];
  const rhythmLabels: Record<string, string> = {
    frantic: 'سريع',
    balanced: 'متوازن',
    patient: 'هادئ',
  };
  const home = stats?.teams[metadata.home.team_id];
  const away = stats?.teams[metadata.away.team_id];
  const values = history.map((s) => s.chaos_index_last_5);
  const points = values
    .map(
      (value, index) =>
        `${values.length > 1 ? (index / (values.length - 1)) * 100 : 0},${40 - value * 0.4}`,
    )
    .join(' ');
  return (
    <section className="indices" aria-label={t.indices}>
      <div className="section-heading">
        <div>
          <span className="eyebrow">{t.statsHint}</span>
          <h2>{t.indices}</h2>
        </div>
        <span className="muted timestamp" dir="ltr">
          {stats ? clockLabel(stats.game_clock_s) : '—'}
        </span>
      </div>
      <div className="metric-grid">
        <div className="metric">
          <div className="metric-label">
            <Gauge size={16} />
            {t.control}
          </div>
          <strong>
            <bdi>{displayNumber(home?.control_index_last_5)}</bdi>
            <span>
              / <bdi>{displayNumber(away?.control_index_last_5)}</bdi>
            </span>
          </strong>
          <small>
            {metadata.home.short_name} / {metadata.away.short_name}
          </small>
        </div>
        <div className="metric">
          <div className="metric-label">
            <Flame size={16} />
            {t.chaos}
          </div>
          <strong>
            <bdi>{displayNumber(stats?.chaos_index_last_5)}</bdi>
          </strong>
          {values.length > 1 ? (
            <svg className="sparkline" viewBox="0 0 100 40" aria-hidden="true">
              <polyline points={points} />
            </svg>
          ) : (
            <small>{t.statsHint}</small>
          )}
        </div>
        <div className="metric">
          <div className="metric-label">
            <Activity size={16} />
            {t.rhythm}
          </div>
          <strong className="rhythm-value">
            {stats
              ? language === 'ar'
                ? rhythmLabels[stats.rhythm_last_5.label] || stats.rhythm_last_5.label
                : stats.rhythm_last_5.label
              : '—'}
          </strong>
          <small>
            <bdi>{displayNumber(stats?.rhythm_last_5.passes_per_min)}</bdi>{' '}
            {language === 'ar' ? 'تمريرة / دقيقة' : 'passes / min'}
          </small>
        </div>
        <div className="metric">
          <div className="metric-label">
            <CircleHelp size={16} />
            {t.ppda}
          </div>
          <strong>
            <bdi>{displayNumber(home?.ppda_last_5)}</bdi>
            <span>
              / <bdi>{displayNumber(away?.ppda_last_5)}</bdi>
            </span>
          </strong>
          <small>
            {language === 'ar'
              ? 'تمريرات الخصم لكل تدخل دفاعي'
              : 'Opponent passes per defensive action'}
          </small>
        </div>
      </div>
      <div className="possession">
        <span>{localizedName(metadata.home, language)}</span>
        <bdi>{displayNumber(home?.possession_pct_match)}%</bdi>
        <div className="possession-track">
          <span style={{ width: `${home?.possession_pct_match ?? 0}%` }} />
        </div>
        <bdi>{displayNumber(away?.possession_pct_match)}%</bdi>
        <span>{localizedName(metadata.away, language)}</span>
      </div>
    </section>
  );
}

export function Commentary({
  overlays,
  language,
  onInspect,
}: {
  overlays: Overlay[];
  language: Language;
  onInspect: (o: Overlay) => void;
}) {
  const t = copy[language];
  return (
    <section className="commentary" aria-label={t.commentary}>
      <div className="section-heading">
        <h2>{t.commentary}</h2>
        <ShieldCheck size={17} />
      </div>
      <div className="commentary-stack" aria-live="polite" aria-atomic="true">
        {overlays.length ? (
          overlays.map((o) => (
            <OverlayCard key={o.overlay_id} overlay={o} language={language} onInspect={onInspect} />
          ))
        ) : (
          <div className="empty-commentary">
            <span className="pulse-ring" />
            <strong>{t.waiting}</strong>
            <p>{t.waitingHint}</p>
          </div>
        )}
      </div>
    </section>
  );
}

export function PlayerTicker({
  stats,
  language,
}: {
  stats: PlayerStats | null;
  language: Language;
}) {
  const t = copy[language];
  return (
    <section className="player-ticker">
      <div>
        <span className="eyebrow">{t.player}</span>
        <h3>{stats ? (language === 'ar' ? stats.name_ar || stats.name : stats.name) : '—'}</h3>
      </div>
      <div>
        <span>{t.distance}</span>
        <strong>
          <bdi>{displayNumber(stats?.distance_km, 2)}</bdi> km
        </strong>
      </div>
      <div>
        <span>{t.topSpeed}</span>
        <strong>
          <bdi>{displayNumber(stats?.top_speed_kmh)}</bdi> km/h
        </strong>
      </div>
      <div className="earned-badges">
        {[...new Set(stats?.badges ?? [])].map((b) => (
          <span key={b}>★ {b.replaceAll('_', ' ')}</span>
        ))}
      </div>
      {stats && (
        <small className="muted">
          {t.measuredAt} <bdi>{clockLabel(stats.at_s)}</bdi>
          <ArrowUpRight size={13} />
        </small>
      )}
    </section>
  );
}
