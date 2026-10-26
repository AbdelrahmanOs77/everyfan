import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, request, socketUrl } from './api';
import { initialStream, parseMessage, reduceStream } from './stream';
import type { StreamMessage } from './types';

export function useMatch() {
  const [stream, setStream] = useState(initialStream);
  const [connection, setConnection] = useState<
    'idle' | 'connecting' | 'connected' | 'closed' | 'error'
  >('idle');
  const [mode, setMode] = useState<'demo' | 'live'>('demo');
  const [error, setError] = useState('');
  const [canControl, setCanControl] = useState(true);
  const socket = useRef<WebSocket | null>(null);
  const current = useRef(initialStream());
  const raf = useRef<number | null>(null);
  const generation = useRef(0);
  const token = useRef<string | null>(null);
  const match = useRef('match_001');
  const publish = useCallback((message: StreamMessage) => {
    current.current = reduceStream(current.current, message);
    if (raf.current === null)
      raf.current = requestAnimationFrame(() => {
        setStream(current.current);
        raf.current = null;
      });
  }, []);
  const disconnect = useCallback(() => {
    generation.current++;
    socket.current?.close();
    socket.current = null;
    if (raf.current !== null) cancelAnimationFrame(raf.current);
    raf.current = null;
    token.current = null;
    current.current = initialStream();
    setStream(current.current);
    setConnection('idle');
    setError('');
  }, []);
  const connect = useCallback(
    async (nextMode: 'demo' | 'live', matchId: string, fromMinute = 0) => {
      disconnect();
      const epoch = generation.current;
      match.current = matchId;
      setMode(nextMode);
      setConnection('connecting');
      setCanControl(nextMode === 'demo');
      try {
        if (nextMode === 'live') {
          try {
            const result = await request<{ control_token: string }>(
              `/api/matches/${matchId}/start?speed=5&from_minute=${fromMinute}`,
              { method: 'POST' },
            );
            if (generation.current !== epoch) return;
            token.current = result.control_token;
            setCanControl(true);
          } catch (cause) {
            if (!(cause instanceof ApiError && cause.status === 409)) throw cause;
            if (generation.current !== epoch) return;
            setCanControl(false);
          }
        }
        if (generation.current !== epoch) return;
        const ws = new WebSocket(
          socketUrl(
            nextMode === 'demo'
              ? `/ws/demo/${matchId}?speed=20&from_minute=${fromMinute}&tracking_hz=2`
              : `/ws/matches/${matchId}?tracking_hz=2`,
          ),
        );
        socket.current = ws;
        ws.onopen = () => {
          if (generation.current === epoch) setConnection('connected');
        };
        ws.onmessage = (event) => {
          if (generation.current !== epoch) return;
          try {
            const message = parseMessage(String(event.data));
            if (message) publish(message);
          } catch {
            setError('The stream sent an unreadable message. Reconnect to continue.');
          }
        };
        ws.onerror = () => {
          if (generation.current === epoch) {
            setConnection('error');
            setError('Could not connect to the match. Check the API connection and try again.');
          }
        };
        ws.onclose = (event) => {
          if (generation.current !== epoch) return;
          setConnection('closed');
          if (event.code !== 1000 && event.code !== 1005)
            setError(`Connection closed (${event.code}). Reconnect to continue.`);
        };
      } catch (cause) {
        if (generation.current !== epoch) return;
        setConnection('error');
        setError(cause instanceof Error ? cause.message : 'Could not start the match.');
      }
    },
    [disconnect, publish],
  );
  const control = useCallback(
    async (action: string, value?: number) => {
      setError('');
      try {
        if (mode === 'demo') {
          if (socket.current?.readyState !== WebSocket.OPEN)
            throw new Error('Connect to the demo first.');
          socket.current.send(
            JSON.stringify({ action, ...(value === undefined ? {} : { value }) }),
          );
        } else {
          if (!token.current) throw new Error('This broadcast is controlled by its host.');
          const parameter =
            value === undefined ? '' : `?${action === 'seek' ? 'minute' : 'value'}=${value}`;
          await request(`/api/matches/${match.current}/${action}${parameter}`, {
            method: 'POST',
            headers: { 'X-Control-Token': token.current },
          });
        }
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : 'Playback control failed.');
      }
    },
    [mode],
  );
  useEffect(
    () => () => {
      generation.current++;
      socket.current?.close();
      if (raf.current !== null) cancelAnimationFrame(raf.current);
    },
    [],
  );
  return { stream, connection, mode, error, canControl, connect, disconnect, control };
}
