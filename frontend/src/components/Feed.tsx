import { useEffect, useState } from 'react';
import { ArrowUpRight, Braces, RefreshCw, Search } from 'lucide-react';
import { apiUrl, request } from '../api';
import { clockLabel, copy } from '../i18n';
import type { Language, Overlay, Persona } from '../types';
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
  const [persona, setPersona] = useState<Persona | ''>('');
  const [query, setQuery] = useState('');
  const [visible, setVisible] = useState(24);
  const t = copy[language];
  const path = `/api/matches/${matchId}/overlays?source=${mode}&limit=5000`;
  const filtered = items.filter(
    (o) =>
      o.language === language &&
      (!persona || o.persona === persona) &&
      `${o.headline} ${o.body}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()),
  );
  useEffect(() => setVisible(24), [matchId, language, persona, query]);
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
      <div className="feed-filters">
        <label className="feed-search">
          <Search size={18} />
          <span className="sr-only">
            {language === 'ar' ? 'ابحث في التعليقات' : 'Search commentary'}
          </span>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={language === 'ar' ? 'ابحث في التعليقات…' : 'Search commentary…'}
          />
        </label>
        <label>
          <span className="sr-only">
            {language === 'ar' ? 'تصفية حسب المنظور' : 'Filter by perspective'}
          </span>
          <select value={persona} onChange={(e) => setPersona(e.target.value as Persona | '')}>
            <option value="">{language === 'ar' ? 'كل المنظورات' : 'All perspectives'}</option>
            {(['beginner', 'tactical', 'player', 'club'] as const).map((p) => (
              <option key={p} value={p}>
                {t[p]}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error && (
        <p role="alert" className="error-banner">
          {error}
        </p>
      )}
      {loading && <p role="status">{t.loading}</p>}
      {!loading && !filtered.length && !error && (
        <p className="empty-commentary">
          {language === 'ar'
            ? 'لا توجد تعليقات مطابقة. جرّب بحثًا آخر أو منظورًا مختلفًا.'
            : 'No matching commentary. Try another search or perspective.'}
        </p>
      )}
      <div className="feed-grid">
        {filtered.slice(0, visible).map((o) => (
          <div key={o.overlay_id}>
            <div className="feed-label">
              <bdi>{clockLabel(o.show_at_s)}</bdi>
              <span>{t[o.persona]}</span>
            </div>
            <OverlayCard overlay={o} language={language} onInspect={onInspect} compact />
          </div>
        ))}
      </div>
      {filtered.length > visible && (
        <div className="feed-more">
          <button className="secondary-button" onClick={() => setVisible((n) => n + 24)}>
            {language === 'ar' ? 'عرض المزيد من التعليقات' : 'Show more commentary'}
          </button>
        </div>
      )}
    </section>
  );
}
