import { useState } from 'react';
import { ArrowUpRight, Radio } from 'lucide-react';
import { apiUrl } from '../api';
import { clockLabel } from '../i18n';
import type { PlayByPlayEntry, Preferences } from '../types';

const labels: Record<string, [string, string]> = {
  pass: ['Pass', 'تمريرة'],
  carry: ['On the ball', 'بالكرة'],
  shot: ['Shot', 'تسديدة'],
  goal: ['Goal', 'هدف'],
  save: ['Save', 'تصدي'],
  corner: ['Corner', 'ركنية'],
  throw_in: ['Throw-in', 'رمية تماس'],
  goal_kick: ['Goal kick', 'ركلة مرمى'],
  free_kick: ['Free kick', 'ركلة حرة'],
  foul: ['Foul', 'مخالفة'],
  card: ['Card', 'بطاقة'],
  tackle: ['Tackle', 'تدخل'],
  duel: ['Duel', 'التحام'],
  pressure: ['Pressure', 'ضغط'],
  interception: ['Interception', 'اعتراض'],
  recovery: ['Recovery', 'استعادة'],
  possession_change: ['Possession', 'استحواذ'],
  substitution: ['Substitution', 'تبديل'],
  kickoff: ['Kick-off', 'بداية اللعب'],
  period_start: ['Whistle', 'صافرة'],
  period_end: ['Whistle', 'صافرة'],
};

export function PlayByPlay({
  entries,
  preference,
  matchId,
  active,
  speed,
  canControl,
  onMatchSpeed,
}: {
  entries: PlayByPlayEntry[];
  preference: Preferences;
  matchId: string;
  active: boolean;
  speed: number;
  canControl: boolean;
  onMatchSpeed: () => void;
}) {
  const [visible, setVisible] = useState(8);
  const ar = preference.language === 'ar';
  const latest = entries[0];
  const focused = (entry: PlayByPlayEntry) =>
    preference.persona === 'player'
      ? !!preference.player && [entry.player_id, entry.receiver_id].includes(preference.player)
      : preference.persona === 'club' && entry.team_id === preference.club;
  const meta = (entry: PlayByPlayEntry) => (
    <div className="play-meta">
      <time>
        <bdi>{clockLabel(entry.show_at_s)}</bdi>
      </time>
      <span>{labels[entry.type]?.[ar ? 1 : 0] || entry.type.replaceAll('_', ' ')}</span>
      {focused(entry) && <span className="play-focus">{ar ? 'متابعة' : 'Following'}</span>}
      <a
        href={apiUrl(`/api/matches/${matchId}/events/${entry.event_id}`)}
        target="_blank"
        rel="noreferrer"
        aria-label={`${ar ? 'مصدر الحدث' : 'Event source'} ${entry.event_id}`}
      >
        {ar ? 'المصدر' : 'Source'}
        <ArrowUpRight size={13} />
      </a>
    </div>
  );
  return (
    <section
      className="play-by-play"
      aria-label={ar ? 'تعليق المباراة' : 'Match commentary'}
      dir={ar ? 'rtl' : 'ltr'}
      lang={preference.language}
    >
      <div className="section-heading">
        <div>
          <span className="eyebrow">
            <Radio size={15} />
            {ar ? 'مع كل لعبة' : 'WITH EVERY PLAY'}
          </span>
          <h2>{ar ? 'تعليق المباراة' : 'Match commentary'}</h2>
        </div>
        {active && speed !== 1 && canControl && (
          <button className="text-button" onClick={onMatchSpeed}>
            {ar ? 'شاهد بسرعة المباراة' : 'Watch at match speed'}
          </button>
        )}
      </div>
      <p className="play-caption">
        {ar
          ? 'الأحداث المسجلة أولاً بأول، والأحدث في الأعلى.'
          : 'Every recorded action, with the newest play first.'}
      </p>
      {latest ? (
        <>
          <article
            className={`play-latest${focused(latest) ? ' play-followed' : ''}`}
            data-event-id={latest.event_id}
            data-event-type={latest.type}
          >
            {meta(latest)}
            <p role="status" aria-live="polite" aria-atomic="true">
              {latest.text[preference.language]}
            </p>
          </article>
          <ol className="play-history" aria-label={ar ? 'اللعبات الأخيرة' : 'Recent plays'}>
            {entries.slice(1, visible).map((entry) => (
              <li
                key={entry.event_id}
                className={focused(entry) ? 'play-followed' : undefined}
                data-event-id={entry.event_id}
                data-event-type={entry.type}
              >
                {meta(entry)}
                <p>{entry.text[preference.language]}</p>
              </li>
            ))}
          </ol>
          {entries.length > visible && (
            <button className="text-button play-more" onClick={() => setVisible((n) => n + 20)}>
              {ar ? 'اعرض اللعبات السابقة' : 'Show earlier plays'}
            </button>
          )}
        </>
      ) : (
        <div className="play-empty">
          <strong>{ar ? 'بانتظار اللعبة التالية' : 'Waiting for the next play'}</strong>
          <p>
            {active
              ? ar
                ? 'سيظهر التعليق مع أول حدث مسجل.'
                : 'Commentary follows the next recorded action.'
              : ar
                ? 'ابدأ العرض لمتابعة التمريرات والتسديدات وإعادة اللعب.'
                : 'Start playback to follow passes, shots and restarts.'}
          </p>
        </div>
      )}
    </section>
  );
}
