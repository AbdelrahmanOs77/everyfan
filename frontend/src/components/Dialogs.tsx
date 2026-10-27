import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Check, Copy, ShieldAlert, ShieldCheck, X } from 'lucide-react';
import { apiUrl, request } from '../api';
import { clockLabel, copy } from '../i18n';
import type { BreakResult, Evidence, Language, Overlay, Preferences, Recap } from '../types';

export function Dialog({
  title,
  language,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  language: Language;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className={wide ? 'wide-dialog' : ''}
      dir={language === 'ar' ? 'rtl' : 'ltr'}
      aria-label={title}
      onCancel={onClose}
    >
      <header className="dialog-header">
        <h2>{title}</h2>
        <button className="icon-button" aria-label={copy[language].close} onClick={onClose}>
          <X size={21} />
        </button>
      </header>
      {children}
    </dialog>
  );
}

export function EvidenceDialog({
  overlay,
  language,
  onClose,
}: {
  overlay: Overlay;
  language: Language;
  onClose: () => void;
}) {
  const [data, setData] = useState<Evidence | null>(null);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);
  const t = copy[language];
  useEffect(() => {
    const controller = new AbortController();
    request<Evidence>(`/api/matches/${overlay.match_id}/evidence/${overlay.moment_id}`, {
      signal: controller.signal,
    })
      .then(setData)
      .catch((cause) => {
        if (!controller.signal.aborted) setError(String(cause));
      });
    return () => controller.abort();
  }, [overlay.match_id, overlay.moment_id]);
  return (
    <Dialog title={t.evidence} language={language} onClose={onClose}>
      <div className="dialog-body">
        <div className="evidence-intro" dir={overlay.dir}>
          <ShieldCheck size={25} />
          <div>
            <h3>{overlay.headline}</h3>
            <p>{overlay.body}</p>
          </div>
        </div>
        {error && (
          <p className="error-banner" role="alert">
            {error}
          </p>
        )}
        {!data && !error && <p role="status">{t.loading}</p>}
        {data && (
          <>
            <h3>{t.rule}</h3>
            <p>{data.rule.description}</p>
            <code>{data.rule.rule_id}</code>
            <h3>{t.facts}</h3>
            <dl className="facts-grid">
              {Object.entries(data.facts).map(([key, value]) => (
                <div key={key}>
                  <dt>{key.replaceAll('_', ' ')}</dt>
                  <dd>
                    <bdi>{String(value)}</bdi>
                  </dd>
                </div>
              ))}
            </dl>
            <h3>{t.events}</h3>
            <div className="evidence-events">
              {data.evidence_events.map((event) => (
                <a
                  href={apiUrl(`/api/matches/${overlay.match_id}/events/${event.event_id}`)}
                  target="_blank"
                  rel="noreferrer"
                  key={event.event_id}
                >
                  <code>{event.event_id}</code>
                  <span>{event.type}</span>
                  <bdi>{clockLabel(event.game_time_s)}</bdi>
                </a>
              ))}
            </div>
            <span className="verification-note">
              <Check size={14} />
              {data.all_evidence_resolved
                ? language === 'ar'
                  ? 'جميع أحداث الدليل متاحة'
                  : 'All evidence events resolved'
                : language === 'ar'
                  ? 'بعض أحداث الدليل غير متاحة'
                  : 'Some evidence events are unavailable'}
            </span>
          </>
        )}
        <h3>{t.trace}</h3>
        {overlay.trace_id ? (
          <div className="trace-row">
            <code dir="ltr">{overlay.trace_id}</code>
            <button
              className="text-button"
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(overlay.trace_id!);
                  setCopied(true);
                } catch {
                  setError(
                    language === 'ar'
                      ? 'تعذّر النسخ. يمكنك تحديد المعرّف ونسخه.'
                      : 'Copy unavailable. Select and copy the ID instead.',
                  );
                }
              }}
            >
              <Copy size={14} />
              {copied ? t.copied : t.copy}
            </button>
          </div>
        ) : (
          <p className="muted">
            {language === 'ar'
              ? 'لم يُرفق معرّف مسار بهذا التعليق.'
              : 'No workflow trace ID is attached to this overlay.'}
          </p>
        )}
      </div>
    </Dialog>
  );
}

export function BreakExperiment({
  language,
  preference,
  matchId,
  momentId,
}: {
  language: Language;
  preference: Preferences;
  matchId: string;
  momentId: string;
}) {
  const [data, setData] = useState<BreakResult | null>(null);
  const [error, setError] = useState('');
  const t = copy[language];
  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({
      match_id: matchId,
      moment_id: momentId,
      persona: preference.persona,
      lang: language,
    });
    if (preference.persona === 'club') params.set('club', preference.club);
    request<BreakResult>(`/api/demo/break-it?${params}`, {
      method: 'POST',
      signal: controller.signal,
    })
      .then(setData)
      .catch((cause) => {
        if (!controller.signal.aborted) setError(String(cause));
      });
    return () => controller.abort();
  }, [matchId, momentId, preference.persona, preference.club, language]);
  return (
    <>
      <div className="dialog-body">
        <p className="dialog-lede">{t.breakIntro}</p>
        <small className="muted">{t.noModel}</small>
        {error && (
          <p role="alert" className="error-banner">
            {error}
          </p>
        )}
        {!data && !error && <p role="status">{t.loading}</p>}
        {data && (
          <>
            <div className="break-grid">
              <article className="rejected-panel" dir={data.draft.dir}>
                <span className="panel-label">
                  <ShieldAlert size={19} />
                  {t.rejected}
                </span>
                <h3>{data.draft.headline}</h3>
                <p>{data.draft.body}</p>
                <code>{data.verdict.reason_code}</code>
              </article>
              <article className="approved-panel" dir={data.repaired_or_fallback_overlay.dir}>
                <span className="panel-label">
                  <ShieldCheck size={19} />
                  {t.replacement}
                </span>
                <h3>{data.repaired_or_fallback_overlay.headline}</h3>
                <p>{data.repaired_or_fallback_overlay.body}</p>
                <span>{data.repaired_or_fallback_overlay.verification_status}</span>
              </article>
            </div>
            <div className="verdict-detail">
              <strong>{data.verdict.reason_code}</strong>
              <p>{data.verdict.detail}</p>
            </div>
          </>
        )}
      </div>
    </>
  );
}

export function RecapDialog({
  language,
  preference,
  matchId,
  mode,
  until,
  onClose,
  onSeek,
}: {
  language: Language;
  preference: Preferences;
  matchId: string;
  mode: 'demo' | 'live';
  until: number;
  onClose: () => void;
  onSeek: (minute: number) => void;
}) {
  const snapshotTime = useRef(until).current;
  const [data, setData] = useState<Recap | null>(null);
  const [error, setError] = useState('');
  const t = copy[language];
  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({
      persona: preference.persona,
      lang: language,
      source: mode,
      until_s: String(snapshotTime),
    });
    if (preference.persona === 'club') params.set('club', preference.club);
    request<Recap>(`/api/matches/${matchId}/recap?${params}`, { signal: controller.signal })
      .then(setData)
      .catch((cause) => {
        if (!controller.signal.aborted) setError(String(cause));
      });
    return () => controller.abort();
  }, [matchId, mode, snapshotTime, preference.persona, preference.club, language]);
  return (
    <Dialog title={t.recap} language={language} onClose={onClose}>
      <div className="dialog-body">
        {error && (
          <p role="alert" className="error-banner">
            {error}
          </p>
        )}
        {!data && !error && <p role="status">{t.loading}</p>}
        {data && (
          <article dir={data.dir}>
            <span className="eyebrow">
              {data.final ? t.fulltime : t.sofar} ·{' '}
              {data.source === 'agent' ? t.verified : t.fallback}
            </span>
            <h3 className="recap-headline">{data.headline}</h3>
            <p className="recap-body">{data.body}</p>
            <div className="recap-moments">
              {data.key_moments.map((m) => (
                <button
                  key={m.moment_id}
                  onClick={() => {
                    onSeek(m.minute - 1);
                    onClose();
                  }}
                >
                  <bdi>{m.minute}′</bdi>
                  <span>{m.headline}</span>
                </button>
              ))}
            </div>
          </article>
        )}
      </div>
    </Dialog>
  );
}
