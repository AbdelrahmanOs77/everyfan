import type { Dispatch, SetStateAction } from 'react';
import { Activity, Heart, ShieldCheck, Target, UserRound, Play } from 'lucide-react';
import { copy, displayNumber, localizedName, clockLabel } from '../i18n';
import type {
  Language,
  Metadata,
  Stats,
  PlayerStats,
  Preferences,
  Moment,
  AdvancedStats,
} from '../types';
import type { Screen } from '../navigation';
import { PlayerTicker } from './Insights';
import { ShotEvidence } from './TacticalDashboard';

export function FanControls({
  view,
  metadata,
  preference,
  onChange,
  active,
  demoReady,
  onDemo,
}: {
  view: Screen;
  metadata: Metadata | null;
  preference: Preferences;
  onChange: Dispatch<SetStateAction<Preferences>>;
  active: boolean;
  demoReady: boolean;
  onDemo: () => void;
}) {
  const ar = preference.language === 'ar';
  const t = copy[preference.language];
  return (
    <div className="fan-controls">
      <span>
        <ShieldCheck size={17} />
        {ar
          ? 'المنظور يتغيّر. الحقائق تبقى موثّقة.'
          : 'A perspective for you. The same verified facts.'}
      </span>
      {view !== 'beginner' && view !== 'perspectives' && !active && (
        <button className="primary-button" disabled={!demoReady} onClick={onDemo}>
          <Play size={16} />
          {t.demo}
        </button>
      )}
      {view === 'player' && (
        <label>
          {t.favoritePlayer}
          <select
            value={preference.player}
            disabled={!metadata}
            onChange={(e) => onChange((p) => ({ ...p, player: e.target.value }))}
          >
            {metadata &&
              [...metadata.home.players, ...metadata.away.players].map((p) => (
                <option key={p.player_id} value={p.player_id}>
                  {localizedName(p, preference.language)} · {p.shirt_number}
                </option>
              ))}
          </select>
        </label>
      )}
      {view === 'club' && (
        <label>
          {t.favoriteClub}
          <select
            value={preference.club}
            disabled={!metadata}
            onChange={(e) => onChange((p) => ({ ...p, club: e.target.value }))}
          >
            {metadata &&
              [metadata.home, metadata.away].map((team) => (
                <option key={team.team_id} value={team.team_id}>
                  {localizedName(team, preference.language)}
                </option>
              ))}
          </select>
        </label>
      )}
    </div>
  );
}

export function BeginnerStats({
  metadata,
  stats,
  language,
}: {
  metadata: Metadata;
  stats: Stats | null;
  language: Language;
}) {
  const ar = language === 'ar';
  return (
    <section className="beginner-stats" aria-label={ar ? 'المباراة ببساطة' : 'Match at a glance'}>
      <div className="section-heading">
        <h2>{ar ? 'المباراة ببساطة' : 'Match at a glance'}</h2>
        <Target size={18} />
      </div>
      <p>
        {ar
          ? 'التسديدات محاولات للتسجيل، والاستحواذ يوضح حصة الكرة.'
          : 'Shots are attempts to score. Possession tells you who has had the ball.'}
      </p>
      <div className="simple-team-header">
        <span>{localizedName(metadata.home, language)}</span>
        <span>{localizedName(metadata.away, language)}</span>
      </div>
      {[
        ['shots_match', ar ? 'التسديدات' : 'Shots', ''],
        ['possession_pct_match', ar ? 'الاستحواذ' : 'Time on the ball', '%'],
      ].map(([key, label, unit]) => (
        <div className="simple-stat-row" key={key}>
          <bdi>
            {displayNumber(
              stats?.teams[metadata.home.team_id]?.[key as keyof Stats['teams'][string]],
            )}
            {unit}
          </bdi>
          <span>{label}</span>
          <bdi>
            {displayNumber(
              stats?.teams[metadata.away.team_id]?.[key as keyof Stats['teams'][string]],
            )}
            {unit}
          </bdi>
        </div>
      ))}
      <small className="muted">
        {ar ? 'القياس عند' : 'Measured at'}{' '}
        <bdi>{stats ? clockLabel(stats.game_clock_s) : '—'}</bdi>
      </small>
    </section>
  );
}

export function PlayerDashboard({
  metadata,
  stats,
  language,
  selectedPlayer,
  moments,
  clock,
  onJump,
  advanced,
}: {
  metadata: Metadata;
  stats: PlayerStats | null;
  language: Language;
  selectedPlayer: string;
  moments: Moment[];
  clock: number;
  onJump: (m: Moment) => void;
  advanced: AdvancedStats | null;
}) {
  const ar = language === 'ar';
  const player = [...metadata.home.players, ...metadata.away.players].find(
    (p) => p.player_id === selectedPlayer,
  );
  const team = player?.team_id === metadata.home.team_id ? metadata.home : metadata.away;
  const ownMoments = moments
    .filter((m) => m.player_id === selectedPlayer && m.game_clock_s <= clock)
    .slice(-4)
    .reverse();
  const metrics: [string, string, string][] = [
    ['goals', 'Goals', 'الأهداف'],
    ['assists', 'Assists', 'التمريرات الحاسمة'],
    ['shots', 'Shots', 'التسديدات'],
    ['shots_on_target', 'On target', 'على المرمى'],
    ['key_passes', 'Key passes', 'تمريرات مفتاحية'],
    ['passes_completed', 'Completed passes', 'تمريرات مكتملة'],
    ['tackles_won', 'Tackles won', 'تدخلات ناجحة'],
    ['interceptions', 'Interceptions', 'اعتراضات'],
  ];
  return (
    <section className="player-dashboard" aria-label={ar ? 'أداء اللاعب' : 'Player performance'}>
      <div className="player-profile">
        <span className="jersey-number" style={{ borderColor: team.primary_color }}>
          <bdi>{player?.shirt_number ?? '—'}</bdi>
        </span>
        <div>
          <span className="eyebrow">
            <UserRound size={15} />
            {ar ? 'ملف اللاعب' : 'PLAYER SPOTLIGHT'}
          </span>
          <h2>{player ? localizedName(player, language) : '—'}</h2>
          <p>
            {localizedName(team, language)} · <bdi>{player?.position}</bdi>
          </p>
        </div>
      </div>
      <PlayerTicker stats={stats} language={language} />
      <div className="player-metric-grid">
        {metrics.map(([key, en, arabic]) => (
          <div key={key}>
            <span>{ar ? arabic : en}</span>
            <strong>
              <bdi>{displayNumber(stats?.events[key], 0)}</bdi>
            </strong>
          </div>
        ))}
      </div>
      <details className="player-details">
        <summary>{ar ? 'تفاصيل التمرير والتسديد' : 'Passing & shooting detail'}</summary>
        <dl>
          <div>
            <dt>{ar ? 'دقة التمرير' : 'Pass completion'}</dt>
            <dd>
              <bdi>
                {stats?.events.pass_accuracy == null
                  ? '—'
                  : stats.events.pass_accuracy.toLocaleString('en-US', {
                      style: 'percent',
                      maximumFractionDigits: 1,
                    })}
              </bdi>
            </dd>
          </div>
          <div>
            <dt>{ar ? 'محاولات التمرير' : 'Pass attempts'}</dt>
            <dd>
              <bdi>{displayNumber(stats?.events.passes, 0)}</bdi>
            </dd>
          </div>
          <div>
            <dt>{ar ? 'المسافة الكلية للتمريرات' : 'Total pass distance'}</dt>
            <dd>
              <bdi>{displayNumber(stats?.events.total_pass_distance_m)}</bdi> m
            </dd>
          </div>
          <div>
            <dt>{ar ? 'أقصى سرعة تسديدة' : 'Fastest shot'}</dt>
            <dd>
              <bdi>{displayNumber(stats?.events.max_shot_speed_kmh)}</bdi> km/h
            </dd>
          </div>
          <div>
            <dt>{ar ? 'تمريرات صعبة مكتملة' : 'Difficult passes completed'}</dt>
            <dd>
              <bdi>{displayNumber(stats?.events.killer_passes, 0)}</bdi>
            </dd>
          </div>
        </dl>
      </details>
      {advanced && (
        <p className="data-stamp">
          {ar ? 'بيانات التمرير والتسديد حتى' : 'Pass and shot evidence available through'}{' '}
          <bdi>{clockLabel(advanced.at_s)}</bdi>
        </p>
      )}
      {advanced && player && (
        <details className="player-shot-detail">
          <summary>{ar ? 'خريطة تسديدات لاعبك' : 'Your player’s shot map'}</summary>
          <ShotEvidence
            metadata={metadata}
            language={language}
            shots={(advanced.teams[player.team_id]?.shot_map || []).filter(
              (s) => s.player_id === selectedPlayer,
            )}
          />
        </details>
      )}
      {ownMoments.length > 0 && (
        <div className="player-highlights">
          <h3>{ar ? 'لحظات لاعبك' : 'Your player’s moments'}</h3>
          {ownMoments.map((m) => (
            <button className="secondary-button" key={m.moment_id} onClick={() => onJump(m)}>
              <bdi>{clockLabel(m.game_clock_s)}</bdi>
              {m.type.replaceAll('_', ' ')}
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

export function ClubStats({
  metadata,
  stats,
  language,
  club,
}: {
  metadata: Metadata;
  stats: Stats | null;
  language: Language;
  club: string;
}) {
  const ar = language === 'ar';
  const team = club === metadata.away.team_id ? metadata.away : metadata.home;
  const own = stats?.teams[team.team_id];
  return (
    <section className="club-dashboard">
      <div className="section-heading">
        <div>
          <span className="eyebrow">{ar ? 'منظور مشجع النادي' : 'YOUR CLUB’S MATCHDAY'}</span>
          <h2>{localizedName(team, language)}</h2>
        </div>
        <Heart size={24} />
      </div>
      <p>
        {ar
          ? 'قصة فريقك، بالحقائق المقاسة نفسها.'
          : 'Your side of the story, grounded in the same measured match.'}
      </p>
      <div className="club-metrics">
        {[
          ['goals', ar ? 'الأهداف' : 'Goals'],
          ['shots_match', ar ? 'التسديدات' : 'Shots'],
          ['possession_pct_match', ar ? 'الاستحواذ %' : 'Possession %'],
          ['pass_accuracy_pct_match', ar ? 'دقة التمرير %' : 'Pass accuracy %'],
        ].map(([key, label]) => (
          <div key={key}>
            <span>{label}</span>
            <strong>
              <bdi>{displayNumber(own?.[key as keyof typeof own])}</bdi>
            </strong>
          </div>
        ))}
      </div>
      <span className="data-stamp">
        <Activity size={14} />
        {stats ? clockLabel(stats.game_clock_s) : '—'}
      </span>
    </section>
  );
}
