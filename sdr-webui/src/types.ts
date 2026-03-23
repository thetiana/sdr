export type Modulation = 'NFM' | 'AM' | 'WFM';

export interface RadioState {
  center_frequency_hz: number;
  sample_rate_hz: number;
  bandwidth_hz: number;
  gain_mode: string;
  gain_db: number;
  ppm: number;
  antenna: string;
  bias_tee: boolean;
  ready: boolean;
  revision: number;
  last_error?: string | null;
}

export interface RadioCapabilities {
  device_name: string;
  serial: string;
  driver: string;
  frequency_range: { min_hz: number; max_hz: number };
  supported_sample_rates_hz: number[];
  bandwidth_range_hz: { min_hz: number; max_hz: number };
  bandwidth_options_hz: number[];
  gain_controls: { name: string; min_db: number; max_db: number; step_db: number }[];
  agc_supported: boolean;
  antennas: string[];
  dc_offset_supported: boolean;
  iq_balance_supported: boolean;
  supported_modulations: Modulation[];
  recommended_runtime_limits: Record<string, number>;
}

export interface Channel {
  id: string;
  label?: string | null;
  frequency_hz: number;
  modulation: Modulation;
  bandwidth_hz: number;
  audio_rate_hz: number;
  enabled: boolean;
  muted: boolean;
  priority: number;
  squelch_threshold_db: number;
  squelch_hang_ms: number;
  audio_activity_threshold_dbfs: number;
  activity_attack_ms: number;
  activity_release_ms: number;
  minimum_active_ms: number;
  status: 'idle' | 'active' | 'disabled';
  stream_id?: string | null;
  last_active_at?: string | null;
  revision: number;
}

export interface Scanner {
  id: string;
  name: string;
  frequencies_hz: number[];
  modulation: Modulation;
  bandwidth_hz: number;
  dwell_ms: number;
  hold_ms: number;
  resume_delay_ms: number;
  priority_frequencies_hz: number[];
  enabled: boolean;
  mode: 'retune' | 'in_band';
  protect_fixed_channels: boolean;
  running: boolean;
  revision: number;
  last_hit_at?: string | null;
  last_frequency_hz?: number | null;
}

export interface Activity {
  id: string;
  channel_id: string;
  channel_label?: string | null;
  frequency_hz: number;
  start_timestamp: string;
  end_timestamp?: string | null;
  duration_ms?: number | null;
  peak_signal_db: number;
  peak_audio_dbfs: number;
  state: 'active' | 'completed';
  audio_available: boolean;
}

export interface Stream {
  id: string;
  channel_id: string;
  transport: 'websocket' | 'http_chunked';
  format: 'pcm_s16le' | 'wav';
  sample_rate_hz: number;
  state: 'idle' | 'streaming' | 'buffered';
  url: string;
}

export interface RuntimeEvent {
  event_type: 'channel_active' | 'channel_idle' | 'scanner_hit' | 'radio_retuned' | 'error' | 'overrun';
  timestamp: string;
  channel_id?: string | null;
  scanner_id?: string | null;
  activity_id?: string | null;
  message?: string | null;
  rf_level_db?: number | null;
  audio_level_dbfs?: number | null;
  frequency_hz?: number | null;
  metadata: Record<string, unknown>;
}
