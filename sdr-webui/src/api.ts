import type { Activity, Channel, RadioCapabilities, RadioState, RuntimeEvent, Scanner, Stream } from './types';

const runtimeConfig = window.__RUNTIME_CONFIG__ || {};
const apiBase = runtimeConfig.SDR_API_BASE_URL || import.meta.env.VITE_SDR_API_BASE_URL || '/runtime-api';
const apiToken = runtimeConfig.SDR_API_TOKEN || import.meta.env.VITE_SDR_API_TOKEN || '';

function headers(): HeadersInit {
  return apiToken ? { Authorization: `Bearer ${apiToken}` } : {};
}

function normalizeBase(base: string): string {
  return base.endsWith('/') ? base.slice(0, -1) : base;
}

function buildHttpUrl(path: string): string {
  const base = normalizeBase(apiBase);
  return `${base}${path}`;
}

function buildWebSocketUrl(path: string): string {
  const base = normalizeBase(apiBase);
  if (/^https?:\/\//.test(base)) {
    return `${base.replace(/^http/, 'ws')}${path}`;
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}${base}${path}`;
}

function parseJsonText<T>(text: string): T | null {
  const trimmed = text.trim();
  if (!trimmed) {
    return null;
  }
  if (!['{', '['].includes(trimmed[0])) {
    return null;
  }
  return JSON.parse(trimmed) as T;
}

async function readJsonResponse<T>(response: Response): Promise<T | null> {
  const text = await response.text();
  try {
    return parseJsonText<T>(text);
  } catch (error) {
    throw new Error(`Invalid JSON from runtime: ${error instanceof Error ? error.message : String(error)}`);
  }
}

async function requestAllowError<T>(path: string): Promise<{ ok: boolean; status: number; data: T | null }> {
  const response = await fetch(buildHttpUrl(path), { headers: { ...headers() } });
  const data = await readJsonResponse<T>(response);
  return { ok: response.ok, status: response.status, data };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(buildHttpUrl(path), {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...headers(),
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `HTTP ${response.status}`);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  const data = await readJsonResponse<T>(response);
  if (data === null) {
    throw new Error(`Runtime returned an empty or non-JSON response for ${path}`);
  }
  return data;
}

export const runtimeApi = {
  apiBase,
  fetchHealth: () => request<{ status: string; timestamp: string }>('/healthz'),
  fetchReady: () => requestAllowError<{ status: string; reason?: string }>('/readyz'),
  fetchCapabilities: () => request<RadioCapabilities>('/api/v1/radio/capabilities'),
  fetchRadioState: () => request<RadioState>('/api/v1/radio/state'),
  fetchChannels: () => request<Channel[]>('/api/v1/channels'),
  createChannel: (payload: Partial<Channel>) => request<Channel>('/api/v1/channels', { method: 'POST', body: JSON.stringify(payload) }),
  updateChannel: (id: string, payload: Record<string, unknown>) => request<Channel>(`/api/v1/channels/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteChannel: (id: string) => request<void>(`/api/v1/channels/${id}`, { method: 'DELETE' }),
  fetchScanners: () => request<Scanner[]>('/api/v1/scanners'),
  createScanner: (payload: Partial<Scanner>) => request<Scanner>('/api/v1/scanners', { method: 'POST', body: JSON.stringify(payload) }),
  updateScanner: (id: string, payload: Record<string, unknown>) => request<Scanner>(`/api/v1/scanners/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteScanner: (id: string) => request<void>(`/api/v1/scanners/${id}`, { method: 'DELETE' }),
  startScanner: (id: string) => request<Scanner>(`/api/v1/scanners/${id}/start`, { method: 'POST' }),
  stopScanner: (id: string) => request<Scanner>(`/api/v1/scanners/${id}/stop`, { method: 'POST' }),
  fetchActivities: () => request<Activity[]>('/api/v1/activities'),
  fetchStreams: () => request<Stream[]>('/api/v1/streams'),
  fetchEvents: () => request<RuntimeEvent[]>('/api/v1/events'),
};

export function openEventSocket(
  onEvent: (event: RuntimeEvent) => void,
  onStatus: (connected: boolean) => void,
  onProtocolError?: (message: string) => void,
) {
  const wsBase = buildWebSocketUrl('/api/v1/events/ws');
  const wsUrl = apiToken ? `${wsBase}?token=${encodeURIComponent(apiToken)}` : wsBase;
  const socket = new WebSocket(wsUrl, []);
  socket.onopen = () => onStatus(true);
  socket.onclose = () => onStatus(false);
  socket.onerror = () => onStatus(false);
  socket.onmessage = (message) => {
    try {
      const event = parseJsonText<RuntimeEvent>(String(message.data));
      if (!event) {
        onProtocolError?.(`Received non-JSON WebSocket payload: ${String(message.data).slice(0, 120)}`);
        return;
      }
      onEvent(event);
    } catch (error) {
      onProtocolError?.(`Invalid WebSocket JSON: ${error instanceof Error ? error.message : String(error)}`);
    }
  };
  return socket;
}
