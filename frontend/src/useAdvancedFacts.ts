import { useEffect, useRef, useState } from 'react';
import { request } from './api';
import type { AdvancedStats } from './types';

export function useAdvancedFacts(
  matchId: string,
  runId: string | null,
  clock: number,
  window: number,
  enabled: boolean,
) {
  const [data, setData] = useState<AdvancedStats | null>(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(false);
  const now = useRef(clock);
  now.current = clock;
  const refresh = useRef<() => void>(() => {});
  useEffect(() => {
    setData(null);
    setError(false);
    setLoading(false);
    if (!enabled) {
      refresh.current = () => {};
      return;
    }
    let controller: AbortController | undefined;
    let alive = true;
    const poll = () => {
      controller?.abort();
      controller = new AbortController();
      const signal = controller.signal;
      setLoading(true);
      request<AdvancedStats>(
        `/api/matches/${matchId}/advanced-stats?at_s=${Math.floor(now.current)}&window_s=${window}`,
        { signal },
      )
        .then((value) => {
          if (alive && !signal.aborted) {
            setData(value);
            setError(false);
          }
        })
        .catch(() => {
          if (alive && !signal.aborted) setError(true);
        })
        .finally(() => {
          if (alive && !signal.aborted) setLoading(false);
        });
    };
    refresh.current = poll;
    poll();
    const timer = setInterval(poll, 10000);
    return () => {
      alive = false;
      controller?.abort();
      clearInterval(timer);
      refresh.current = () => {};
    };
  }, [matchId, runId, window, enabled]);
  return { data, error, loading, refresh: () => refresh.current() };
}
