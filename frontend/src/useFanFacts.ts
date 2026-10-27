import { useEffect, useRef, useState } from 'react';
import { request } from './api';
import type { FanStats } from './types';

export function useFanFacts(
  matchId: string,
  runId: string | null,
  clock: number,
  window: number,
  enabled: boolean,
) {
  const [data, setData] = useState<FanStats | null>(null);
  const [error, setError] = useState(false);
  const now = useRef(clock);
  now.current = clock;
  const last = useRef(0);
  const refresh = useRef<() => void>(() => {});
  useEffect(() => {
    setData(null);
    setError(false);
    if (!enabled) return;
    let alive = true;
    let controller: AbortController | undefined;
    const poll = () => {
      controller?.abort();
      controller = new AbortController();
      const signal = controller.signal;
      last.current = Math.floor(now.current);
      request<FanStats>(
        `/api/matches/${matchId}/fan-stats?at_s=${last.current}&window_s=${window}`,
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
        });
    };
    refresh.current = poll;
    poll();
    const timer = setInterval(poll, 5000);
    return () => {
      alive = false;
      controller?.abort();
      clearInterval(timer);
      refresh.current = () => {};
    };
  }, [matchId, runId, window, enabled]);
  useEffect(() => {
    if (enabled && (clock < last.current || clock - last.current >= 60)) refresh.current();
  }, [clock, enabled]);
  return {
    data:
      enabled && data?.match_id === matchId && data.at_s <= clock && data.window_s === window
        ? data
        : null,
    error,
    refresh: () => refresh.current(),
  };
}
