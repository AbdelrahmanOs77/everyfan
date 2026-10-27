import { useEffect, useRef, useState } from 'react';
import { request } from './api';
import type { PlayerStats, Stats } from './types';

export function useFacts(
  matchId: string,
  runId: string | null,
  clock: number,
  playerId: string,
  active: boolean,
) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [player, setPlayer] = useState<PlayerStats | null>(null);
  const [history, setHistory] = useState<Stats[]>([]);
  const [error, setError] = useState(false);
  const now = useRef(clock);
  now.current = clock;
  const lastRequested = useRef(0);
  const refresh = useRef<(() => void) | null>(null);
  useEffect(() => {
    setStats(null);
    setPlayer(null);
    setHistory([]);
    setError(false);
    if (!active) {
      refresh.current = null;
      return;
    }
    let controller: AbortController | null = null;
    let alive = true;
    const poll = () => {
      controller?.abort();
      controller = new AbortController();
      const signal = controller.signal;
      const at = Math.floor(now.current);
      lastRequested.current = at;
      request<Stats>(`/api/matches/${matchId}/stats?at_s=${at}`, { signal })
        .then((data) => {
          if (!alive || signal.aborted) return;
          setStats(data);
          setError(false);
          setHistory((previous) => [
            ...previous.filter((p) => p.game_clock_s < data.game_clock_s).slice(-39),
            data,
          ]);
        })
        .catch(() => {
          if (alive && !signal.aborted) setError(true);
        });
      if (playerId)
        request<PlayerStats>(`/api/matches/${matchId}/players/${playerId}/stats?at_s=${at}`, {
          signal,
        })
          .then((data) => {
            if (alive && !signal.aborted) setPlayer(data);
          })
          .catch(() => {
            if (alive && !signal.aborted) setPlayer(null);
          });
    };
    refresh.current = poll;
    poll();
    const interval = setInterval(poll, 5000);
    return () => {
      alive = false;
      controller?.abort();
      clearInterval(interval);
      refresh.current = null;
    };
  }, [matchId, runId, playerId, active]);
  useEffect(() => {
    if (active && Math.abs(clock - lastRequested.current) > 300) refresh.current?.();
  }, [clock, active]);
  return { stats, player, history, error };
}
