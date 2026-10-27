import { useState } from 'react';
import { Activity, ArrowUpRight, Trophy } from 'lucide-react';
import { apiUrl } from '../api';
import { clockLabel, displayNumber, localizedName } from '../i18n';
import type { FanStats, Language, Metadata, Moment } from '../types';

type Props = { metadata: Metadata; data: FanStats; language: Language };

function playerName(metadata: Metadata, id: string, language: Language) {
  const player = [...metadata.home.players, ...metadata.away.players].find(
    (p) => p.player_id === id,
  );
  return player ? localizedName(player, language) : id;
}
function sourceUrl(data: FanStats) {
  return `/api/matches/${data.match_id}/fan-stats?at_s=${data.at_s}&window_s=${data.window_s}`;
}
function SourceLink({ path, language }: { path: string; language: Language }) {
  return (
    <a className="event-link" href={apiUrl(path)} target="_blank" rel="noreferrer">
      {language === 'ar' ? 'المصدر' : 'Source'}
      <ArrowUpRight size={14} />
    </a>
  );
}
function EventSources({
  ids,
  data,
  language,
}: {
  ids: string[];
  data: FanStats;
  language: Language;
}) {
  const [open, setOpen] = useState(false);
  return (
    <details className="extra-evidence" onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>{language === 'ar' ? 'الأحداث الداعمة' : 'Supporting events'}</summary>
      {open && (
        <div className="source-list">
          {ids.slice(0, 16).map((id) => (
            <a
              key={id}
              className="event-link"
              href={apiUrl(`/api/matches/${data.match_id}/events/${id}`)}
              target="_blank"
              rel="noreferrer"
            >
              <code>{id}</code>
            </a>
          ))}
          <SourceLink path={sourceUrl(data)} language={language} />
          <small>
            {language === 'ar'
              ? 'جميع المعرّفات والتعريفات في المصدر الكامل.'
              : 'All event IDs and definitions are in the full source snapshot.'}
          </small>
        </div>
      )}
    </details>
  );
}
function Stamp({ data, language }: { data: FanStats; language: Language }) {
  return (
    <p className="data-stamp">
      {language === 'ar' ? 'القياس عند' : 'Measured at'} <bdi>{clockLabel(data.at_s)}</bdi>
      <SourceLink path={sourceUrl(data)} language={language} />
    </p>
  );
}

export function OnTop({ metadata, data, language }: Props) {
  const ar = language === 'ar';
  const team = [metadata.home, metadata.away].find((t) => t.team_id === data.on_top.team_id);
  return (
    <section
      className="on-top extra-panel"
      aria-label={ar ? 'من يتفوق الآن؟' : 'Who is on top right now?'}
    >
      <span className="eyebrow">
        <Activity size={16} />
        {ar ? 'من يتفوق الآن؟' : 'WHO IS ON TOP RIGHT NOW?'}
      </span>
      <h2>
        {team
          ? ar
            ? `${localizedName(team, language)} يتقدم في اللعب`
            : `${localizedName(team, language)} has the edge`
          : data.on_top.status === 'insufficient'
            ? ar
              ? 'ننتظر مزيداً من اللعب'
              : 'Waiting for more play'
            : ar
              ? 'لا أفضلية واضحة'
              : 'No clear edge'}
      </h2>
      <p>
        {team
          ? ar
            ? 'فريقه أفضل في التحكم بالكرة خلال الفترة الأخيرة، وصنع هجمات أخطر مؤخراً. هذا لا يتنبأ بالفائز.'
            : 'They have controlled the ball better in the recent window and produced more recent attacking activity. This does not predict the winner.'
          : data.on_top.status === 'insufficient'
            ? ar
              ? 'لا تتوفر تمريرات واستحواذ كافيان للمقارنة بعد.'
              : 'There is not enough passing and possession evidence to compare both teams yet.'
            : ar
              ? 'التحكم بالكرة والنشاط الهجومي متعادلان أو يشيران إلى اتجاهين مختلفين.'
              : 'Ball control and attacking activity are tied or point in different directions.'}
      </p>
      <details className="extra-evidence">
        <summary>{ar ? 'كيف عرفنا؟' : 'How do we know?'}</summary>
        <p>
          {ar
            ? 'لا نسمي فريقاً متفوقاً إلا إذا تقدم في المؤشرين معاً.'
            : 'A team gets the edge only when it leads both measures.'}
        </p>
        <div className="table-scroll">
          <table>
            <caption>{ar ? 'المقاييس المستخدمة' : 'Measures behind this explanation'}</caption>
            <thead>
              <tr>
                <th>{ar ? 'الفريق' : 'Team'}</th>
                <th>{ar ? 'التحكم' : 'Control index'}</th>
                <th>{ar ? 'الزخم' : 'Momentum'}</th>
              </tr>
            </thead>
            <tbody>
              {[metadata.home, metadata.away].map((t) => (
                <tr key={t.team_id}>
                  <th scope="row">{localizedName(t, language)}</th>
                  <td>
                    <bdi>{displayNumber(data.teams[t.team_id]?.summary.control_index_last_5)}</bdi>
                  </td>
                  <td>
                    <bdi>{displayNumber(data.teams[t.team_id]?.summary.momentum)}</bdi>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <EventSources ids={data.evidence_event_ids} data={data} language={language} />
      </details>
      <Stamp data={data} language={language} />
    </section>
  );
}

export function MomentumChart({ metadata, data, language }: Props) {
  const ar = language === 'ar';
  const [showTable, setShowTable] = useState(false);
  const teams = [metadata.home, metadata.away];
  const points = data.momentum_timeline;
  // Only chart geometry is calculated here; every plotted measurement comes from the API.
  const series = (id: string) =>
    points.flatMap((p) => (p.teams[id] ? [{ at_s: p.at_s, ...p.teams[id] }] : []));
  const peak = Math.max(0, ...teams.flatMap((t) => series(t.team_id).map((p) => p.value)));
  const ceiling = Math.max(1, peak);
  const x = (t: number) => 40 + (640 * t) / Math.max(data.at_s, 1);
  const y = (v: number) => 184 - (154 * v) / ceiling;
  return (
    <section
      className="momentum-panel extra-panel"
      aria-label={ar ? 'الزخم عبر الوقت' : 'Momentum over time'}
    >
      <div className="section-heading">
        <div>
          <span className="eyebrow">{ar ? 'إيقاع الهجوم' : 'THE ATTACKING PICTURE'}</span>
          <h2>{ar ? 'الزخم عبر الوقت' : 'Momentum over time'}</h2>
        </div>
        <Activity size={22} />
      </div>
      <p>
        {ar
          ? 'يرتفع المؤشر مع التسديدات والتقدم الهجومي، ويقل بمرور الوقت. ليس احتمال تسجيل.'
          : 'Shots and attacking progress lift the index; it fades over time. It is not a scoring probability.'}
      </p>
      <div className="momentum-legend">
        {teams.map((t, i) => (
          <span key={t.team_id}>
            <i className={i ? 'line-key dashed' : 'line-key'} />
            {localizedName(t, language)} ·{' '}
            <bdi>{displayNumber(points.at(-1)?.teams[t.team_id]?.value)}</bdi>
          </span>
        ))}
      </div>
      <svg
        className="momentum-chart"
        viewBox="0 0 720 222"
        role="img"
        aria-label={
          ar
            ? 'زخم الفريقين عبر الوقت؛ القيم والأدلة في الجدول'
            : 'Momentum of both teams over time; values and sources in the data table'
        }
      >
        <path d="M40 30V184H680M40 107H680M40 30H680" fill="none" stroke="var(--line)" />
        {(peak ? [0, peak] : [0]).map((v) => (
          <text key={v} x="32" y={y(v) + 4} textAnchor="end" fill="var(--muted)" fontSize="12">
            {displayNumber(v)}
          </text>
        ))}
        {teams.map((t, i) => (
          <polyline
            key={t.team_id}
            points={series(t.team_id)
              .map((p) => `${x(p.at_s)},${y(p.value)}`)
              .join(' ')}
            fill="none"
            stroke={i ? 'var(--text)' : 'var(--accent)'}
            strokeWidth="2.5"
            strokeDasharray={i ? '7 5' : undefined}
            strokeLinejoin="round"
          />
        ))}
        <text x="40" y="210" fill="var(--muted)" fontSize="12">
          {clockLabel(points[0]?.at_s ?? 0)}
        </text>
        <text x="680" y="210" textAnchor="end" fill="var(--muted)" fontSize="12">
          {clockLabel(data.at_s)}
        </text>
      </svg>
      <Stamp data={data} language={language} />
      <details className="extra-evidence" onToggle={(e) => setShowTable(e.currentTarget.open)}>
        <summary>{ar ? 'جدول الزخم والأدلة' : 'Momentum data & evidence'}</summary>
        {showTable && (
          <div className="table-scroll momentum-data">
            <table>
              <caption className="sr-only">
                {ar ? 'قيم الزخم والأحداث الداعمة' : 'Momentum values and contributing events'}
              </caption>
              <thead>
                <tr>
                  <th>{ar ? 'الوقت' : 'Time'}</th>
                  {teams.map((t) => (
                    <th key={t.team_id}>{localizedName(t, language)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {points.map((p) => (
                  <tr key={p.at_s}>
                    <th scope="row">
                      <bdi>{clockLabel(p.at_s)}</bdi>
                    </th>
                    {teams.map((t) => (
                      <td key={t.team_id}>
                        <bdi>{displayNumber(p.teams[t.team_id]?.value)}</bdi>
                        <EventSources
                          ids={p.teams[t.team_id]?.evidence_event_ids ?? []}
                          data={data}
                          language={language}
                        />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </details>
    </section>
  );
}

export function TrackingPositions({
  metadata,
  data,
  language,
  teamId,
}: Props & { teamId: string }) {
  const ar = language === 'ar';
  const team = teamId === metadata.away.team_id ? metadata.away : metadata.home;
  const positions = data.teams[team.team_id]?.average_positions ?? [];
  return (
    <section className="tracking-positions">
      <div className="section-heading">
        <h3>{ar ? 'متوسط تمركز اللاعبين من التتبع' : 'Average positions from tracking'}</h3>
      </div>
      <p className="plot-caption">
        {ar
          ? 'متوسط عينات التتبع في الفترة المحددة، وليست تشكيلة ثابتة. الفريق المضيف يهاجم يميناً في الإحداثيات الأصلية.'
          : 'Sample averages in the selected window, not a fixed formation. Original coordinates: home attacks right.'}
      </p>
      <Stamp data={data} language={language} />
      {!positions.length ? (
        <p className="analysis-empty">
          {ar ? 'لا تتوفر عينات تتبع في هذه الفترة.' : 'No tracking samples in this window.'}
        </p>
      ) : (
        <>
          <svg
            className="analysis-pitch tracking-pitch"
            viewBox="-3 -3 111 74"
            role="img"
            aria-label={
              ar
                ? 'متوسط مواضع اللاعبين؛ الأسماء والإحداثيات في الجدول'
                : 'Average player positions; names and coordinates in the table'
            }
          >
            <g fill="none" stroke="var(--pitch-line)" strokeWidth=".3">
              <rect width="105" height="68" />
              <path d="M52.5 0V68M0 14H16.5V54H0M105 14H88.5V54H105" />
              <circle cx="52.5" cy="34" r="9.15" />
            </g>
            {positions.map((p) => (
              <g key={p.player_id}>
                <circle
                  cx={p.x_m}
                  cy={68 - p.y_m}
                  r="2.3"
                  fill={team.primary_color}
                  stroke="white"
                  strokeWidth=".4"
                />
                <text
                  x={p.x_m}
                  y={68 - p.y_m - 3.6}
                  textAnchor="middle"
                  fill="white"
                  fontSize="2.5"
                >
                  {team.players.find((t) => t.player_id === p.player_id)?.shirt_number}
                </text>
                <title>{playerName(metadata, p.player_id, language)}</title>
              </g>
            ))}
          </svg>
          <div className="table-scroll">
            <table>
              <caption>{ar ? 'إحداثيات مقاسة بالمتر' : 'Measured coordinates in metres'}</caption>
              <thead>
                <tr>
                  <th>{ar ? 'اللاعب' : 'Player'}</th>
                  <th>x · y (m)</th>
                  <th>{ar ? 'العينات' : 'Samples'}</th>
                  <th>{ar ? 'التتبع' : 'Tracking'}</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.player_id}>
                    <th scope="row">{playerName(metadata, p.player_id, language)}</th>
                    <td>
                      <bdi>
                        {displayNumber(p.x_m, 2)} · {displayNumber(p.y_m, 2)}
                      </bdi>
                    </td>
                    <td>
                      <bdi>{p.sample_count}</bdi>
                    </td>
                    <td>
                      <SourceLink
                        language={language}
                        path={`/api/matches/${data.match_id}/players/${p.player_id}/tracking-samples?at_s=${data.at_s}&window_s=${data.window_s}`}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

export function Leaderboard({
  metadata,
  data,
  language,
  playerId,
  onPlayer,
}: Props & { playerId: string; onPlayer: (id: string) => void }) {
  const ar = language === 'ar';
  const [metric, setMetric] = useState<'distance_km' | 'top_speed_kmh'>('distance_km');
  const team = metadata.away.players.some((p) => p.player_id === playerId)
    ? metadata.away
    : metadata.home;
  const rows = data.teams[team.team_id]?.leaderboards[metric] ?? [];
  return (
    <section className="leaderboard extra-panel">
      <div className="section-heading">
        <div>
          <span className="eyebrow">
            <Trophy size={16} />
            {localizedName(team, language)}
          </span>
          <h2>{ar ? 'متصدرو الفريق' : 'Team leaders'}</h2>
        </div>
        <label>
          {ar ? 'مقياس الترتيب' : 'Leaderboard metric'}
          <select value={metric} onChange={(e) => setMetric(e.target.value as typeof metric)}>
            <option value="distance_km">{ar ? 'المسافة · كم' : 'Distance · km'}</option>
            <option value="top_speed_kmh">{ar ? 'أقصى سرعة · كم/س' : 'Top speed · km/h'}</option>
          </select>
        </label>
      </div>
      <p>
        {ar
          ? 'أفضل خمسة حسب التتبع المتاح حتى الآن. السرعة ليست عدد مرات الركض السريع.'
          : 'Top five from tracking available so far. Top speed is not a sprint count.'}
      </p>
      {!rows.length ? (
        <p className="analysis-empty">
          {ar ? 'ننتظر بيانات التتبع.' : 'Waiting for tracking data.'}
        </p>
      ) : (
        <div className="table-scroll">
          <table>
            <caption className="sr-only">{ar ? 'ترتيب الفريق' : 'Team leaderboard'}</caption>
            <thead>
              <tr>
                <th>{ar ? 'الترتيب' : 'Rank'}</th>
                <th>{ar ? 'اللاعب' : 'Player'}</th>
                <th>{metric === 'distance_km' ? 'km' : 'km/h'}</th>
                <th>{ar ? 'التتبع' : 'Tracking'}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.player_id}
                  className={row.player_id === playerId ? 'selected-player-row' : undefined}
                >
                  <td>
                    <bdi>{row.rank}</bdi>
                  </td>
                  <th scope="row">
                    <button className="text-button" onClick={() => onPlayer(row.player_id)}>
                      {playerName(metadata, row.player_id, language)}
                    </button>
                  </th>
                  <td>
                    <bdi>{displayNumber(row.value, metric === 'distance_km' ? 2 : 1)}</bdi>
                  </td>
                  <td>
                    <SourceLink
                      language={language}
                      path={`/api/matches/${data.match_id}/players/${row.player_id}/tracking-samples?at_s=${row.tracking_until_s}&window_s=5400`}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Stamp data={data} language={language} />
    </section>
  );
}

export function ClubComparison({
  metadata,
  data,
  language,
  club,
  onJump,
}: Props & { club: string; onJump: (moment: Moment) => void }) {
  const ar = language === 'ar';
  const team = club === metadata.away.team_id ? metadata.away : metadata.home;
  const rival = team.team_id === metadata.home.team_id ? metadata.away : metadata.home;
  const own = data.teams[team.team_id];
  const metrics: [keyof FanStats['teams'][string]['summary'], string, string][] = [
    ['goals', 'Goals', 'الأهداف'],
    ['shots_match', 'Shots', 'التسديدات'],
    ['possession_pct_match', 'Possession %', 'الاستحواذ %'],
    ['pass_accuracy_pct_match', 'Pass accuracy %', 'دقة التمرير %'],
    ['ppda_match', 'PPDA', 'PPDA'],
  ];
  const labels: Record<string, string> = ar
    ? {
        goal: 'هدف',
        big_chance: 'فرصة كبيرة',
        momentum_shift: 'تحول الزخم',
        pressing_shift: 'تحول الضغط',
        control_to_chaos: 'تحول إلى الفوضى',
        rhythm_change: 'تغير الإيقاع',
        killer_pass: 'تمريرة صعبة',
        player_milestone: 'إنجاز لاعب',
        red_card: 'بطاقة حمراء',
      }
    : {
        goal: 'Goal',
        big_chance: 'Big chance',
        momentum_shift: 'Momentum shift',
        pressing_shift: 'Pressing shift',
        control_to_chaos: 'Control to chaos',
        rhythm_change: 'Rhythm change',
        killer_pass: 'Difficult pass',
        player_milestone: 'Player milestone',
        red_card: 'Red card',
      };
  return (
    <section className="club-dashboard extra-panel">
      <span className="eyebrow">{ar ? 'مباراة ناديك' : 'YOUR CLUB’S MATCHDAY'}</span>
      <h2>{localizedName(team, language)}</h2>
      <p>
        {ar
          ? 'ناديك أمام منافسه، حتى نفس التوقيت.'
          : 'Your club against its rival, measured at the same time.'}
      </p>
      <div className="table-scroll">
        <table className="club-comparison">
          <caption className="sr-only">
            {ar ? 'مقارنة مع المنافس' : 'Head to head with the rival'}
          </caption>
          <thead>
            <tr>
              <th>{ar ? 'المقياس' : 'Metric'}</th>
              <th>{localizedName(team, language)}</th>
              <th>{localizedName(rival, language)}</th>
            </tr>
          </thead>
          <tbody>
            {metrics.map(([key, en, arabic]) => (
              <tr key={key}>
                <th scope="row">{ar ? arabic : en}</th>
                <td>
                  <bdi>{displayNumber(own?.summary[key])}</bdi>
                </td>
                <td>
                  <bdi>{displayNumber(data.teams[rival.team_id]?.summary[key])}</bdi>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="plot-caption">
        {ar
          ? 'انخفاض PPDA يعني أفعالاً دفاعية أكثر بالنسبة لتمريرات الخصم. الشرطة تعني غياب مقام صالح.'
          : 'Lower PPDA means more defensive actions relative to opponent passes. A dash means no valid denominator.'}
      </p>
      <Stamp data={data} language={language} />
      <EventSources ids={data.evidence_event_ids} data={data} language={language} />
      <div className="club-key-moments">
        <h3>{ar ? 'أبرز لحظات ناديك' : 'Your club’s key moments'}</h3>
        <p className="plot-caption">
          {ar
            ? 'حتى ثلاث لحظات حسب أهمية الحدث المكتشف.'
            : 'Up to three, selected by the detector’s importance rating.'}
        </p>
        {!own?.key_moments.length ? (
          <p>{ar ? 'لم تُرصد لحظة لناديك بعد.' : 'No club moments detected yet.'}</p>
        ) : (
          own.key_moments.map((m) => (
            <article key={m.moment_id}>
              <button className="secondary-button" onClick={() => onJump(m)}>
                <bdi>{clockLabel(m.game_clock_s)}</bdi>
                {labels[m.type] || m.type}
                {m.player_id && <span>{playerName(metadata, m.player_id, language)}</span>}
              </button>
              <SourceLink
                language={language}
                path={`/api/matches/${data.match_id}/evidence/${m.moment_id}`}
              />
            </article>
          ))
        )}
      </div>
    </section>
  );
}
