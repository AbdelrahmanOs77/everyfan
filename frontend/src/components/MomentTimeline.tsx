import { ChevronRight, CircleDot } from 'lucide-react';
import { copy, clockLabel } from '../i18n';
import type { Language, Moment } from '../types';
export function MomentTimeline({
  highlights,
  language,
  disabled,
  onJump,
}: {
  highlights: Moment[];
  language: Language;
  disabled: boolean;
  onJump: (m: Moment) => void;
}) {
  const t = copy[language];
  return (
    <aside className="moments-panel">
      <div className="section-heading">
        <h2>{t.timeline}</h2>
        <CircleDot size={18} />
      </div>
      <p className="muted panel-caption">
        {language === 'ar'
          ? 'انتقل إلى لحظة بارزة في المباراة المسجلة.'
          : 'Jump to a turning point in the recorded match.'}
      </p>
      <div className="highlight-list">
        {highlights.map((m) => (
          <button
            key={m.moment_id}
            disabled={disabled}
            onClick={() => onJump(m)}
            aria-label={`${t.jump} ${clockLabel(m.game_clock_s)}`}
          >
            <bdi>{clockLabel(m.game_clock_s)}</bdi>
            <span>
              {language === 'ar'
                ? m.type === 'goal'
                  ? 'هدف'
                  : 'بطاقة حمراء'
                : m.type.replaceAll('_', ' ')}
            </span>
            <ChevronRight size={16} />
          </button>
        ))}
      </div>
    </aside>
  );
}
