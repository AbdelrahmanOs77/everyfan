import { apiUrl } from '../api';
import { clockLabel, displayNumber, localizedName } from '../i18n';
import type { FrameRange, Language, Metadata, TrackingStats } from '../types';

function Frames({ range, language }: { range: FrameRange | null; language: Language }) {
  const ar = language === 'ar';
  return range ? (
    <p className="data-stamp">
      {ar ? 'الإطارات' : 'Frames'}{' '}
      <bdi>
        {range.first_frame}–{range.last_frame}
      </bdi>{' '}
      ·{' '}
      <bdi>
        {clockLabel(range.from_s)}–{clockLabel(range.to_s)}
      </bdi>{' '}
      · {ar ? 'العينات' : 'Samples'} <bdi>{range.sample_count}</bdi>
    </p>
  ) : null;
}

function WindowStamp({ data, language }: { data: TrackingStats; language: Language }) {
  return (
    <p className="data-stamp">
      {language === 'ar' ? 'فترة القياس' : 'Measured window'}{' '}
      <bdi>
        {clockLabel(data.window_start_s)}–{clockLabel(data.at_s)}
      </bdi>
    </p>
  );
}

export function TeamShapeCard({
  data,
  metadata,
  teamId,
  language,
}: {
  data: TrackingStats;
  metadata: Metadata;
  teamId: string;
  language: Language;
}) {
  const ar = language === 'ar';
  const team = teamId === metadata.away.team_id ? metadata.away : metadata.home;
  const shape = data.teams[team.team_id];
  return (
    <section className="team-shape extra-panel" aria-label={ar ? 'شكل الفريق' : 'Team shape'}>
      <div className="section-heading">
        <h3>{ar ? 'شكل الفريق' : 'Team shape'}</h3>
        <span>{localizedName(team, language)}</span>
      </div>
      <p>
        {ar
          ? 'متوسط تباعد لاعبي الملعب. ارتفاع خط الدفاع يقاس من مرمى الفريق.'
          : 'Average outfield-player spread. Defensive line height is measured from the team’s own goal.'}
      </p>
      <WindowStamp data={data} language={language} />
      <dl className="tracking-metric-grid">
        {(
          [
            ['mean_width_m', 'Mean width', 'متوسط العرض'],
            ['mean_length_m', 'Mean length', 'متوسط الطول'],
            ['defensive_line_height_m', 'Defensive line height', 'ارتفاع خط الدفاع'],
          ] as const
        ).map(([key, en, arabic]) => (
          <div key={key}>
            <dt>{ar ? arabic : en}</dt>
            <dd data-tracking-metric={key}>
              <bdi>{displayNumber(shape?.[key], 2)}</bdi> <small>m</small>
            </dd>
          </div>
        ))}
      </dl>
      {!shape?.evidence && (
        <p>
          {ar
            ? 'لا توجد بيانات تتبع للفريق في هذه الفترة.'
            : 'No team tracking samples in this window.'}
        </p>
      )}
      <details className="extra-evidence">
        <summary>{ar ? 'الأدلة وطريقة الحساب' : 'Frame evidence & method'}</summary>
        <p>
          {ar
            ? 'العرض والطول من فروق الإحداثيات بكل إطار، دون حراس المرمى. خط الدفاع هو متوسط عمق أعمق اللاعبين المحددين أدناه، ثم المتوسط عبر الإطارات.'
            : 'Width and length are the coordinate spreads in each frame, excluding goalkeepers. The defensive line averages the deepest outfield players per frame, then averages those frame values.'}
        </p>
        <p>
          {ar ? 'حجم خط الدفاع' : 'Defensive line players'}:{' '}
          <bdi>{data.defensive_line_players}</bdi> ·{' '}
          {ar ? 'عينات خط الدفاع الصالحة' : 'Valid line samples'}:{' '}
          <bdi>{shape?.defensive_line_sample_count ?? '—'}</bdi>
        </p>
        <Frames range={shape?.evidence ?? null} language={language} />
        <a
          className="event-link"
          href={apiUrl(
            `/api/matches/${metadata.match_id}/advanced-stats?at_s=${data.at_s}&window_s=${data.window_s}`,
          )}
          target="_blank"
          rel="noreferrer"
        >
          {ar ? 'افتح القياسات والأدلة' : 'Open measurements & evidence'}
        </a>
        <div className="source-list">
          {team.players
            .filter((p) => p.position !== 'GK')
            .map((p) => (
              <a
                className="event-link"
                key={p.player_id}
                href={apiUrl(
                  `/api/matches/${metadata.match_id}/players/${p.player_id}/tracking-samples?at_s=${data.at_s}&window_s=${data.window_s}`,
                )}
                target="_blank"
                rel="noreferrer"
              >
                {localizedName(p, language)}
              </a>
            ))}
        </div>
      </details>
    </section>
  );
}

export function HighIntensityCard({
  data,
  metadata,
  playerId,
  language,
  window,
  onWindow,
}: {
  data: TrackingStats | null;
  metadata: Metadata;
  playerId: string;
  language: Language;
  window: number;
  onWindow: (value: number) => void;
}) {
  const ar = language === 'ar';
  const row = data?.players[playerId];
  const thresholds = data?.thresholds;
  return (
    <section
      className="high-intensity extra-panel"
      aria-label={ar ? 'الجهد عالي الشدة' : 'High-intensity performance'}
    >
      <div className="section-heading">
        <h2>{ar ? 'الجهد عالي الشدة' : 'High-intensity performance'}</h2>
        <label>
          {ar ? 'فترة الجهد عالي الشدة' : 'High-intensity window'}
          <select value={window} onChange={(e) => onWindow(Number(e.target.value))}>
            <option value={60}>{ar ? 'آخر دقيقة' : 'Last minute'}</option>
            <option value={300}>{ar ? 'آخر 5 دقائق' : 'Last 5 minutes'}</option>
            <option value={900}>{ar ? 'آخر 15 دقيقة' : 'Last 15 minutes'}</option>
            <option value={5400}>{ar ? 'المباراة حتى الآن' : 'Match so far'}</option>
          </select>
        </label>
      </div>
      <p>
        {ar
          ? 'قياسات من سرعات التتبع الملسّاة للاعب المحدد.'
          : 'Measured from the selected player’s smoothed tracking speeds.'}
      </p>
      {data && <WindowStamp data={data} language={language} />}
      <dl className="tracking-metric-grid">
        <div>
          <dt>
            {ar ? 'المسافة فوق' : 'Distance above'}{' '}
            <bdi>{displayNumber(thresholds?.distance_threshold_kmh)}</bdi> km/h
          </dt>
          <dd data-tracking-metric="distance_above_threshold_m">
            <bdi>{displayNumber(row?.distance_above_threshold_m, 2)}</bdi> <small>m</small>
          </dd>
        </div>
        <div>
          <dt>
            {ar ? 'مرات الركض السريع فوق' : 'Sprints above'}{' '}
            <bdi>{displayNumber(thresholds?.sprint_threshold_kmh)}</bdi> km/h
          </dt>
          <dd data-tracking-metric="sprints">
            <bdi>{displayNumber(row?.sprints, 0)}</bdi>
          </dd>
        </div>
      </dl>
      {thresholds && (
        <p>
          {ar
            ? 'تُحسب كل فترة ركض مرة واحدة عندما تتجاوز مدتها'
            : 'A continuous run counts once when its duration exceeds'}{' '}
          <bdi>{displayNumber(thresholds.sprint_min_duration_s)}</bdi>{' '}
          {ar
            ? 'ثانية. العدد يخص لحظة التأهل داخل الفترة المحددة.'
            : 's. Counts refer to qualification within the selected window.'}
        </p>
      )}
      {row?.distance_above_threshold_m == null && (
        <p>
          {ar
            ? 'لا تتوفر عينات سرعة مكتملة في هذه الفترة بعد.'
            : 'No fully smoothed speed samples in this window yet.'}
        </p>
      )}
      {row && data && (
        <details className="extra-evidence">
          <summary>{ar ? 'أدلة الجهد عالي الشدة' : 'High-intensity frame evidence'}</summary>
          <Frames range={row.window_evidence} language={language} />
          <p>
            {ar
              ? 'يشمل نطاق المصدر الإطارات السابقة اللازمة لتدقيق التلسية واستمرارية الركض.'
              : 'The source range also includes earlier frames needed to reproduce smoothing and sprint continuity.'}
          </p>
          <Frames range={row.evidence} language={language} />
          <div className="source-list">
            <a
              className="event-link"
              href={apiUrl(
                `/api/matches/${metadata.match_id}/fan-stats?at_s=${data.at_s}&window_s=${data.window_s}`,
              )}
              target="_blank"
              rel="noreferrer"
            >
              {ar ? 'افتح القياسات' : 'Open measurements'}
            </a>
            {row.evidence && (
              <a
                className="event-link"
                href={apiUrl(
                  `/api/matches/${metadata.match_id}/players/${playerId}/tracking-samples?at_s=${row.evidence.to_s}&window_s=5400`,
                )}
                target="_blank"
                rel="noreferrer"
              >
                {ar ? 'عينات التتبع الأصلية' : 'Original tracking samples'}
              </a>
            )}
          </div>
        </details>
      )}
    </section>
  );
}
