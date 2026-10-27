import { ArrowUpRight, Check, ShieldCheck, Wrench } from 'lucide-react';
import { copy, displayNumber } from '../i18n';
import type { Language, Overlay } from '../types';

export function OverlayCard({
  overlay,
  language,
  onInspect,
  compact = false,
}: {
  overlay: Overlay;
  language: Language;
  onInspect: (overlay: Overlay) => void;
  compact?: boolean;
}) {
  const t = copy[language];
  return (
    <article
      className={`overlay-card ${compact ? 'compact' : ''}`}
      dir={overlay.dir}
      lang={overlay.language}
      data-overlay-id={overlay.overlay_id}
    >
      <div className="overlay-meta">
        <span>
          <ShieldCheck size={14} />
          {overlay.source === 'agent' ? t.verified : t.fallback}
        </span>
        {overlay.fields.attempts === 2 && (
          <span title={String(overlay.fields.reason_codes || '')}>
            <Wrench size={13} />
            {t.repaired}
          </span>
        )}
        <span className="slot-label">{overlay.slot.replaceAll('_', ' ')}</span>
      </div>
      <h3>{overlay.headline}</h3>
      <p>{overlay.body}</p>
      <div className="overlay-footer">
        <span>
          <Check size={13} />
          {overlay.evidence_event_ids.length} {t.events}
        </span>
        <button className="text-button" onClick={() => onInspect(overlay)}>
          {t.inspect}
          <ArrowUpRight size={15} />
        </button>
      </div>
      {overlay.persona === 'tactical' && typeof overlay.fields.generated_ms === 'number' && (
        <div className="latency" dir="ltr">
          {displayNumber(overlay.fields.generated_ms / 1000, 2)}s /{' '}
          {typeof overlay.fields.budget_ms === 'number'
            ? `${displayNumber(overlay.fields.budget_ms / 1000, 2)}s`
            : '—'}{' '}
          · {language === 'ar' ? 'زمن التوليد / المهلة' : 'generation / budget'}
        </div>
      )}
    </article>
  );
}
