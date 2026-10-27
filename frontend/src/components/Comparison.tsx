import { ShieldCheck } from 'lucide-react';
import { copy } from '../i18n';
import { activeOverlays } from '../stream';
import type { StreamState } from '../stream';
import type { Preferences, Overlay } from '../types';
import { OverlayCard } from './OverlayCard';
export function Comparison({
  stream,
  preference,
  onInspect,
}: {
  stream: StreamState;
  preference: Preferences;
  onInspect: (o: Overlay) => void;
}) {
  const t = copy[preference.language];
  return (
    <section className="comparison" aria-label={t.compare}>
      <div className="section-heading">
        <div>
          <span className="eyebrow">
            {preference.language === 'ar'
              ? 'اللحظة نفسها. أربع زوايا.'
              : 'SAME MOMENT. FOUR PERSPECTIVES.'}
          </span>
          <h2>{t.compare}</h2>
        </div>
        <ShieldCheck size={20} />
      </div>
      <div className="comparison-grid">
        {(
          [
            { persona: 'beginner', language: 'en' },
            { persona: 'tactical', language: 'en' },
            { persona: 'player', language: 'en' },
            { persona: 'beginner', language: 'ar' },
          ] as const
        ).map((p) => {
          const items = activeOverlays(stream, { ...preference, ...p });
          return (
            <section
              className="comparison-pane"
              key={`${p.persona}-${p.language}`}
              dir={p.language === 'ar' ? 'rtl' : 'ltr'}
              lang={p.language}
            >
              <h3>
                {copy[p.language][p.persona]} <span>{p.language.toUpperCase()}</span>
              </h3>
              {items.length ? (
                items.map((o) => (
                  <OverlayCard
                    key={o.overlay_id}
                    overlay={o}
                    language={p.language}
                    onInspect={onInspect}
                    compact
                  />
                ))
              ) : (
                <p className="comparison-empty">{copy[p.language].waiting}</p>
              )}
            </section>
          );
        })}
      </div>
    </section>
  );
}
