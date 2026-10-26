import { useEffect, useState } from 'react';
import { ArrowUpRight, Braces, RefreshCw } from 'lucide-react';
import { apiUrl, request } from '../api';
import { clockLabel, copy } from '../i18n';
import type { Language, Overlay } from '../types';
import { OverlayCard } from './OverlayCard';

export function Feed({
  matchId,
  language,
  mode,
  onInspect,
}: {
  matchId: string;
  language: Language;
  mode: 'demo' | 'live';
  onInspect: (o: Overlay) => void;
}) {
  const [items, setItems] = useState<Overlay[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const t = copy[language];
  const path = `/api/matches/${matchId}/overlays?source=${mode}&limit=5000`;
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    request<{ overlays: Overlay[] }>(path, { signal: controller.signal })
      .then((r) => setItems(r.overlays))
      .catch((cause) => {
        if (!controller.signal.aborted) setError(String(cause));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [path, refresh]);
  return (
    <section className="feed-view">
      <div className="section-heading">
        <div>
          <span className="eyebrow">{t.feedHint}</span>
          <h2>{t.feed}</h2>
        </div>
        <div className="button-row">
          <button className="secondary-button" onClick={() => setRefresh((n) => n + 1)}>
            <RefreshCw size={16} />
            {t.reconnect}
          </button>
          <a className="secondary-button" href={apiUrl(path)} target="_blank" rel="noreferrer">
            <Braces size={16} />
            JSON
            <ArrowUpRight size={14} />
          </a>
          <a
            className="text-button"
            href={apiUrl('/api/spec/overlay')}
            target="_blank"
            rel="noreferrer"
          >
            JSON Schema ↗
          </a>
        </div>
      </div>
      {error && (
        <p role="alert" className="error-banner">
          {error}
        </p>
      )}
      {loading && <p role="status">{t.loading}</p>}
      {!loading && !items.length && !error && <p className="empty-commentary">{t.noMoments}</p>}
      <div className="feed-grid">
        {items
          .filter((o) => o.language === language)
          .map((o) => (
            <div key={o.overlay_id}>
              <div className="feed-label">
                <bdi>{clockLabel(o.show_at_s)}</bdi>
                <span>{t[o.persona]}</span>
              </div>
              <OverlayCard overlay={o} language={language} onInspect={onInspect} compact />
            </div>
          ))}
      </div>
    </section>
  );
}
