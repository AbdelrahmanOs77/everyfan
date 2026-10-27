import { useState } from 'react';
import { ArrowUpRight, Network, ScanLine, ShieldCheck, Target } from 'lucide-react';
import { apiUrl } from '../api';
import { clockLabel, displayNumber, localizedName } from '../i18n';
import type { AdvancedStats, AdvancedTeam, Language, Metadata } from '../types';

const metrics: [string, string, string, string][] = [
  ['possession_pct', 'Possession', 'الاستحواذ', '%'],
  ['pass_accuracy_pct', 'Pass accuracy', 'دقة التمرير', '%'],
  ['ppda', 'PPDA', 'PPDA', ''],
  ['control_index', 'Control index', 'مؤشر التحكم', ''],
  ['passes_per_min', 'Passes / min', 'تمريرات / دقيقة', ''],
  ['passes_per_possession', 'Passes / possession', 'تمريرات / استحواذ', ''],
  ['mean_pass_distance_m', 'Mean pass distance', 'متوسط مسافة التمرير', 'm'],
  ['final_third_share_pct', 'Final-third pass share', 'حصة تمريرات الثلث الهجومي', '%'],
  ['duel_win_pct', 'Duels won', 'نسبة الالتحامات الناجحة', '%'],
  ['shot_conversion_pct', 'Shot conversion', 'تحويل التسديدات إلى أهداف', '%'],
  ['avg_shot_distance_m', 'Mean shot distance', 'متوسط مسافة التسديد', 'm'],
];
const volumes: [string, string, string][] = [
  ['passes', 'Pass attempts', 'محاولات التمرير'],
  ['passes_completed', 'Completed passes', 'تمريرات مكتملة'],
  ['forward_passes_10m', 'Forward passes ≥10m', 'تمريرات تقدم ≥10م'],
  ['final_third_entries', 'Final-third entries', 'دخول الثلث الهجومي'],
  ['box_entries', 'Box entries', 'دخول منطقة الجزاء'],
  ['shots', 'Shots', 'التسديدات'],
  ['shots_on_target', 'Shots on target', 'تسديدات على المرمى'],
  ['recoveries', 'Ball recoveries', 'استعادة الكرة'],
  ['high_recoveries', 'High recoveries', 'استعادة في الثلث الهجومي'],
  ['tackles_won', 'Tackles won', 'تدخلات ناجحة'],
  ['interceptions', 'Interceptions', 'اعتراضات'],
  ['duels_won', 'Duels won', 'التحامات ناجحة'],
  ['fouls', 'Fouls committed', 'الأخطاء'],
  ['corners', 'Corners', 'ركنيات'],
];

function PitchLines() {
  return (
    <g fill="none" stroke="var(--pitch-line)" strokeWidth=".3">
      <rect x="0" y="0" width="105" height="68" />
      <path d="M52.5 0V68M0 14H16.5V54H0M105 14H88.5V54H105" />
      <circle cx="52.5" cy="34" r="9.15" />
    </g>
  );
}
function playerName(metadata: Metadata, id: string, language: Language) {
  const p = [...metadata.home.players, ...metadata.away.players].find((p) => p.player_id === id);
  return p ? localizedName(p, language) : id;
}
function EventLink({ matchId, eventId }: { matchId: string; eventId: string }) {
  return (
    <a
      className="event-link"
      href={apiUrl(`/api/matches/${matchId}/events/${eventId}`)}
      target="_blank"
      rel="noreferrer"
    >
      <code>{eventId}</code>
      <ArrowUpRight size={14} />
    </a>
  );
}

export function ShotEvidence({
  shots,
  metadata,
  language,
}: {
  shots: AdvancedTeam['shot_map'];
  metadata: Metadata;
  language: Language;
}) {
  const ar = language === 'ar';
  const outcomes: Record<string, string> = ar
    ? {
        goal: 'هدف',
        saved: 'تصدى لها الحارس',
        off_target: 'خارج المرمى',
        blocked: 'تصدى لها مدافع',
        post: 'القائم',
      }
    : { goal: 'Goal', saved: 'Saved', off_target: 'Off target', blocked: 'Blocked', post: 'Post' };
  return (
    <section className="shot-evidence">
      <div className="section-heading">
        <h3>{ar ? 'مواقع التسديدات' : 'Shot locations'}</h3>
        <Target size={19} />
      </div>
      <svg
        className="analysis-pitch"
        viewBox="-3 -3 111 74"
        role="img"
        aria-label={
          ar
            ? 'مواقع التسديدات من أحداث المباراة، التفاصيل في الجدول'
            : 'Shot event locations; details and outcomes in the table below'
        }
      >
        <PitchLines />
        {shots.map((shot) => (
          <g key={shot.event_id}>
            <circle
              cx={shot.x_m}
              cy={68 - shot.y_m}
              r={shot.outcome === 'goal' ? 2.1 : 1.6}
              fill={shot.outcome === 'goal' ? 'var(--accent)' : 'var(--surface)'}
              stroke={shot.outcome === 'goal' ? 'var(--accent)' : '#dbe5df'}
              strokeWidth=".6"
            />
            <title>
              {playerName(metadata, shot.player_id, language)} ·{' '}
              {outcomes[shot.outcome] || shot.outcome}
            </title>
          </g>
        ))}
      </svg>
      <p className="plot-caption">
        {ar
          ? 'الدائرة الممتلئة: هدف. الفارغة: بقية التسديدات.'
          : 'Filled circle: goal. Open circle: other shots.'}
      </p>
      {!shots.length ? (
        <p className="analysis-empty">
          {ar ? 'لم تُسجل تسديدة في هذه الفترة.' : 'No shot events in this period.'}
        </p>
      ) : (
        <div className="table-scroll">
          <table>
            <caption className="sr-only">{ar ? 'أدلة التسديد' : 'Shot evidence'}</caption>
            <thead>
              <tr>
                <th>{ar ? 'الوقت واللاعب' : 'Time / player'}</th>
                <th>{ar ? 'النتيجة' : 'Outcome'}</th>
                <th>{ar ? 'المسافة' : 'Distance'}</th>
                <th>{ar ? 'الدليل' : 'Evidence'}</th>
              </tr>
            </thead>
            <tbody>
              {shots.map((s) => (
                <tr key={s.event_id}>
                  <th scope="row">
                    <bdi>{clockLabel(s.game_time_s)}</bdi>{' '}
                    {playerName(metadata, s.player_id, language)}
                  </th>
                  <td>{outcomes[s.outcome] || s.outcome}</td>
                  <td>
                    <bdi>{displayNumber(s.distance_m)}</bdi> m
                  </td>
                  <td>
                    <EventLink matchId={metadata.match_id} eventId={s.event_id} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function TacticalDashboard({
  metadata,
  data,
  error,
  loading,
  language,
  window,
  onWindow,
  onRetry,
}: {
  metadata: Metadata;
  data: AdvancedStats | null;
  error: boolean;
  loading: boolean;
  language: Language;
  window: number;
  onWindow: (v: number) => void;
  onRetry: () => void;
}) {
  const [teamId, setTeamId] = useState(metadata.home.team_id);
  const [tab, setTab] = useState<'overview' | 'passing' | 'chances'>('overview');
  const ar = language === 'ar';
  const selected =
    [metadata.home, metadata.away].find((t) => t.team_id === teamId) || metadata.home;
  const team = data?.teams[selected.team_id];
  return (
    <section
      className="tactical-dashboard"
      aria-label={ar ? 'تحليل تكتيكي متقدم' : 'Advanced tactical analysis'}
    >
      <div className="analysis-heading">
        <div>
          <span className="eyebrow">
            {ar ? 'تحليل مقاس من الأحداث' : 'MEASURED FROM THE EVENT STREAM'}
          </span>
          <h2>{ar ? 'مكتب التحليل التكتيكي' : 'The tactical workbench'}</h2>
          <p>
            {ar
              ? 'الفترة المحددة مقابل المباراة حتى التوقيت المعروض.'
              : 'Your selected window, compared with the match up to the same time.'}
          </p>
        </div>
        <div className="analysis-selects">
          <label>
            {ar ? 'الفريق' : 'Team'}
            <select value={selected.team_id} onChange={(e) => setTeamId(e.target.value)}>
              {[metadata.home, metadata.away].map((t) => (
                <option key={t.team_id} value={t.team_id}>
                  {localizedName(t, language)}
                </option>
              ))}
            </select>
          </label>
          <label>
            {ar ? 'فترة التحليل' : 'Analysis window'}
            <select value={window} onChange={(e) => onWindow(Number(e.target.value))}>
              <option value={60}>{ar ? 'آخر دقيقة' : 'Last minute'}</option>
              <option value={300}>{ar ? 'آخر 5 دقائق' : 'Last 5 minutes'}</option>
              <option value={900}>{ar ? 'آخر 15 دقيقة' : 'Last 15 minutes'}</option>
              <option value={5400}>{ar ? 'المباراة حتى الآن' : 'Match so far'}</option>
            </select>
          </label>
        </div>
      </div>
      <div
        className="analysis-tabs"
        role="group"
        aria-label={ar ? 'أقسام التحليل' : 'Analysis sections'}
      >
        {(['overview', 'passing', 'chances'] as const).map((v, i) => {
          const Icon = [ScanLine, Network, Target][i]!;
          return (
            <button key={v} aria-pressed={tab === v} onClick={() => setTab(v)}>
              <Icon size={17} />
              {ar
                ? {
                    overview: 'الأداء والضغط',
                    passing: 'التمرير والسيطرة',
                    chances: 'التسديدات والأفعال',
                  }[v]
                : {
                    overview: 'Performance & pressure',
                    passing: 'Passing & territory',
                    chances: 'Shots & actions',
                  }[v]}
            </button>
          );
        })}
      </div>
      <div className="analysis-status" role="status">
        <ShieldCheck size={15} />
        {data ? (
          <>
            {ar ? 'الفترة' : 'Window'}{' '}
            <bdi>
              {clockLabel(data.window_start_s)}–{clockLabel(data.at_s)}
            </bdi>{' '}
            · {localizedName(selected, language)}
          </>
        ) : ar ? (
          'ابدأ العرض لتحميل التحليل.'
        ) : (
          'Start playback to load the analysis.'
        )}
        {loading && <span>{ar ? 'جارٍ التحديث…' : 'Updating…'}</span>}
      </div>
      {error && (
        <p className="notice-banner" role="alert">
          {ar ? 'تعذّر تحديث التحليل.' : 'Analysis could not be updated.'}{' '}
          <button className="text-button" onClick={onRetry}>
            {ar ? 'أعد المحاولة' : 'Retry analysis'}
          </button>
        </p>
      )}
      {team && tab === 'overview' && (
        <>
          <div className="tactical-kpis">
            {[
              ['ppda', 'PPDA', 'PPDA'],
              ['control_index', 'Control index', 'التحكم'],
              ['final_third_share_pct', 'Final-third pass share %', 'حصة الثلث الهجومي %'],
              ['passes_per_min', 'Passes / min', 'تمريرات / دقيقة'],
            ].map(([key, en, arabic]) => (
              <div key={key}>
                <span>{ar ? arabic : en}</span>
                <strong>
                  <bdi>{displayNumber(team.current[key!])}</bdi>
                </strong>
                <small>
                  {ar ? 'المباراة' : 'Match'} <bdi>{displayNumber(team.match[key!])}</bdi>
                </small>
              </div>
            ))}
          </div>
          <div className="table-scroll">
            <table className="comparison-table">
              <caption>
                {ar
                  ? 'النسب والمعدلات: الفترة مقابل المباراة'
                  : 'Rates and percentages · selected window vs match so far'}
              </caption>
              <thead>
                <tr>
                  <th>{ar ? 'المقياس' : 'Metric'}</th>
                  <th>{ar ? 'الفترة' : 'Window'}</th>
                  <th>{ar ? 'المباراة' : 'Match'}</th>
                  <th>{ar ? 'الفارق' : 'Difference'}</th>
                </tr>
              </thead>
              <tbody>
                {metrics.map(([key, en, arabic, unit]) => (
                  <tr key={key}>
                    <th scope="row">
                      {ar ? arabic : en} {unit && <small>({unit})</small>}
                    </th>
                    <td data-metric={`${key}-current`}>
                      <bdi>{displayNumber(team.current[key])}</bdi>
                    </td>
                    <td>
                      <bdi>{displayNumber(team.match[key])}</bdi>
                    </td>
                    <td>
                      <bdi>
                        {team.deltas[key] != null && team.deltas[key]! > 0 ? '+' : ''}
                        {displayNumber(team.deltas[key])}
                      </bdi>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="pressure-evidence">
            <h3>{ar ? 'ما وراء PPDA' : 'Behind the PPDA'}</h3>
            <p>
              {ar ? 'تمريرات الخصم في منطقة الضغط' : 'Opponent passes in the pressing zone'}:{' '}
              <bdi>{displayNumber(team.current.opponent_passes_ppda_zone, 0)}</bdi> ·{' '}
              {ar ? 'الأفعال الدفاعية' : 'Defensive actions'}:{' '}
              <bdi>{displayNumber(team.current.defensive_actions_ppda_zone, 0)}</bdi>
            </p>
            <p className="muted">
              {ar
                ? 'تقل PPDA مع زيادة كثافة الأفعال الدفاعية نسبةً لتمريرات الخصم. تظهر شرطة عند غياب مقام صالح.'
                : 'Lower PPDA means more defensive actions relative to opponent passes. A dash means there is no valid denominator.'}
            </p>
          </div>
        </>
      )}
      {team && tab === 'passing' && (
        <div className="tactical-spatial">
          <section>
            <h3>{ar ? 'شبكة التمريرات المكتملة' : 'Completed-pass network'}</h3>
            <p className="plot-caption">
              {ar
                ? 'المواضع: متوسط أصول التمرير والاستلام المسجلة، وليست تمركز اللاعبين.'
                : 'Positions are observed pass origins/receptions, averaged by the backend. They are not formation or tracking positions.'}
            </p>
            <svg
              className="analysis-pitch"
              viewBox="-3 -3 111 74"
              role="img"
              aria-label={
                ar
                  ? 'شبكة التمرير مع تفاصيل الروابط في الجدول'
                  : 'Passing network; link counts and source events appear in the table'
              }
            >
              <PitchLines />
              {team.pass_network.edges.map((edge) => {
                const from = team.pass_network.nodes.find(
                  (n) => n.player_id === edge.from_player_id,
                );
                const to = team.pass_network.nodes.find((n) => n.player_id === edge.to_player_id);
                return from && to ? (
                  <line
                    key={`${edge.from_player_id}-${edge.to_player_id}`}
                    x1={from.x_m}
                    y1={68 - from.y_m}
                    x2={to.x_m}
                    y2={68 - to.y_m}
                    stroke="var(--accent)"
                    strokeWidth={Math.min(2.4, 0.3 + edge.completed_passes / 5)}
                    opacity=".6"
                  />
                ) : null;
              })}
              {team.pass_network.nodes.map((node) => (
                <g key={node.player_id}>
                  <circle
                    cx={node.x_m}
                    cy={68 - node.y_m}
                    r="2"
                    fill={selected.primary_color}
                    stroke="white"
                    strokeWidth=".4"
                  />
                  <text
                    x={node.x_m}
                    y={68 - node.y_m - 3}
                    textAnchor="middle"
                    fill="white"
                    fontSize="2.2"
                  >
                    {
                      [...metadata.home.players, ...metadata.away.players].find(
                        (p) => p.player_id === node.player_id,
                      )?.shirt_number
                    }
                  </text>
                </g>
              ))}
            </svg>
            <div className="table-scroll">
              <table>
                <caption className="sr-only">
                  {ar ? 'أقوى روابط التمرير' : 'Strongest passing links'}
                </caption>
                <thead>
                  <tr>
                    <th>{ar ? 'من ← إلى' : 'From → to'}</th>
                    <th>{ar ? 'مكتملة' : 'Completed'}</th>
                    <th>{ar ? 'دليل' : 'Evidence'}</th>
                  </tr>
                </thead>
                <tbody>
                  {team.pass_network.edges.map((e) => (
                    <tr key={`${e.from_player_id}-${e.to_player_id}`}>
                      <th scope="row">
                        {playerName(metadata, e.from_player_id, language)} →{' '}
                        {playerName(metadata, e.to_player_id, language)}
                      </th>
                      <td>
                        <bdi>{e.completed_passes}</bdi>
                      </td>
                      <td>
                        {e.evidence_event_ids[0] && (
                          <EventLink
                            matchId={metadata.match_id}
                            eventId={e.evidence_event_ids[0]}
                          />
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!team.pass_network.edges.length && (
              <p className="analysis-empty">
                {ar
                  ? 'لا توجد تمريرات مكتملة مرتبطة بلاعبين في هذه الفترة.'
                  : 'No linked completed passes in this period.'}
              </p>
            )}
          </section>
          <section>
            <h3>{ar ? 'وجهات التمريرات' : 'Where completed passes arrive'}</h3>
            <p className="plot-caption">
              {ar
                ? 'عدد نقاط نهاية التمرير، من جهة مرماك إلى مرمى الخصم.'
                : 'Completed-pass endpoints, normalized from own goal toward the opponent goal.'}
            </p>
            <div
              className="territory-grid"
              aria-label={
                ar
                  ? 'مناطق التمرير، تفاصيل العدد في كل منطقة'
                  : 'Passing zones, with server-measured counts in each zone'
              }
            >
              {Array.from({ length: 24 }, (_, i) => {
                const cell = team.territory.find(
                  (c) => c.row === Math.floor(i / 6) && c.column === i % 6,
                );
                return (
                  <div key={i} className={cell ? 'occupied' : ''}>
                    <bdi>{cell?.completed_passes ?? '—'}</bdi>
                  </div>
                );
              })}
            </div>
            <div className="territory-direction">
              {ar ? 'مرماك ← مرمى الخصم' : 'Own goal → opponent goal'}
            </div>
            <dl className="progression-stats">
              {volumes.slice(0, 5).map(([key, en, arabic]) => (
                <div key={key}>
                  <dt>{ar ? arabic : en}</dt>
                  <dd>
                    <bdi>{displayNumber(team.current[key], 0)}</bdi>
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        </div>
      )}
      {team && tab === 'chances' && (
        <>
          <ShotEvidence shots={team.shot_map} metadata={metadata} language={language} />
          <div className="table-scroll">
            <table>
              <caption>
                {ar ? 'عدد الأحداث في الفترة المحددة' : 'Event counts in the selected window'}
              </caption>
              <thead>
                <tr>
                  <th>{ar ? 'الفعل' : 'Action'}</th>
                  {[metadata.home, metadata.away].map((t) => (
                    <th key={t.team_id}>{localizedName(t, language)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {volumes.map(([key, en, arabic]) => (
                  <tr key={key}>
                    <th scope="row">{ar ? arabic : en}</th>
                    {[metadata.home, metadata.away].map((t) => (
                      <td key={t.team_id}>
                        <bdi>{displayNumber(data?.teams[t.team_id]?.current[key], 0)}</bdi>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {data && (
        <details className="metric-definitions">
          <summary>{ar ? 'تعريفات المقاييس ومصادرها' : 'Metric definitions & provenance'}</summary>
          <p>
            {ar
              ? 'تُحسب جميع القيم على الخادم من الأحداث السابقة للتوقيت المعروض.'
              : 'Every value is calculated by the server from events at or before the displayed timestamp.'}
          </p>
          <dl>
            {Object.entries(data.definitions).map(([key, value]) => (
              <div key={key}>
                <dt>{key.replaceAll('_', ' ')}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
          <a
            className="text-button"
            target="_blank"
            rel="noreferrer"
            href={apiUrl(
              `/api/matches/${metadata.match_id}/advanced-stats?at_s=${data.at_s}&window_s=${data.window_s}`,
            )}
          >
            {ar ? 'افتح بيانات التحليل' : 'Open analysis JSON'}
            <ArrowUpRight size={15} />
          </a>
        </details>
      )}
    </section>
  );
}
