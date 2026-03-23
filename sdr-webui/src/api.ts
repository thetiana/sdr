import type { Activity, Channel, RadioCapabilities, RadioState, RuntimeEvent, Scanner, Stream } from './types';

const runtimeConfig = window.__RUNTIME_CONFIG__ || {};
const apiBase = runtimeConfig.SDR_API_BASE_URL || import.meta.env.VITE_SDR_API_BASE_URL || 'http://localhost:8080';
const apiToken = runtimeConfig.SDR_API_TOKEN || import.meta.env.VITE_SDR_API_TOKEN || '';

function headers(): HeadersInit {
  return apiToken ? { Authorization: `Bearer ${apiToken}` } : {};
}

async function requestAllowError<T>(path: string): Promise<{ ok: boolean; status: number; data: T | null }> {
  const response = await fetch(`${apiBase}${path}`, { headers: { ...headers() } });
  let data: T | null = null;
  try {
    data = (await response.json()) as T;
  } catch {
    data = null;
  }
  return { ok: response.ok, status: response.status, data };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
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
  return response.json() as Promise<T>;
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

export function openEventSocket(onEvent: (event: RuntimeEvent) => void, onStatus: (connected: boolean) => void) {
  const wsBase = apiBase.replace(/^http/, 'ws') + '/api/v1/events/ws';
  const wsUrl = apiToken ? `${wsBase}?token=${encodeURIComponent(apiToken)}` : wsBase;
  const socket = new WebSocket(wsUrl, []);
  socket.onopen = () => onStatus(true);
  socket.onclose = () => onStatus(false);
  socket.onerror = () => onStatus(false);
  socket.onmessage = (message) => onEvent(JSON.parse(message.data) as RuntimeEvent);
  return socket;
}
