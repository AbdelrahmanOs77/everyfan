import { useEffect, useRef, useState } from 'react';
import { request } from './api';

export function useAdvancedResource<T extends { at_s: number }>(
  path: string,
  runId: string | null,
  clock: number,
  enabled: boolean,
) {
  const [state, setState] = useState<{ path: string; run: string | null; data: T } | null>(null);
  const [error, setError] = useState(false);
  const now = useRef(clock);
  now.current = clock;
  const refresh = useRef<() => void>(() => {});
  const last = useRef(0);
  useEffect(() => {
    setState(null);
    setError(false);
    if (!enabled) return;
    let alive = true,
      pending = false;
    let controller: AbortController | undefined;
    const poll = () => {
      if (pending) return;
      controller = new AbortController();
      const signal = controller.signal;
      const at = Math.floor(now.current);
      last.current = at;
      pending = true;
      request<T>(`${path}${path.includes('?') ? '&' : '?'}at_s=${at}`, { signal })
        .then((data) => {
          if (alive && !signal.aborted) {
            setState({ path, run: runId, data });
            setError(false);
          }
        })
        .catch(() => {
          if (alive && !signal.aborted) setError(true);
        })
        .finally(() => {
          pending = false;
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
  }, [path, runId, enabled]);
  useEffect(() => {
    if (enabled && (clock < last.current || clock - last.current >= 60)) refresh.current();
  }, [clock, enabled]);
  return {
    data:
      enabled && state?.path === path && state.run === runId && state.data.at_s <= clock
        ? state.data
        : null,
    error,
    refresh: () => refresh.current(),
  };
}
