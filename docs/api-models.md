# API and Object Models

## API Base

- REST base: `/api/v1`
- Event WebSocket: `/api/v1/events/ws`
- OpenAPI JSON: `/openapi.json`
- Interactive docs: `/docs`

## Radio Model

`RadioState` includes:

- `center_frequency_hz`
- `sample_rate_hz`
- `bandwidth_hz`
- `gain_mode`
- `gain_db`
- `ppm`
- `antenna`
- `bias_tee`
- `ready`
- `revision`
- `last_error`

`RadioCapabilities` includes device identity plus ranges/options for frequency, rates, bandwidth, gain, antennas, AGC, and supported modulations.

## Channel Object Model

Each channel includes:

- `id`, `label`, `metadata`, `tags`, `priority`
- `frequency_hz`, `modulation`, `bandwidth_hz`, `audio_rate_hz`
- `enabled`, `muted`, `deemphasis`, `agc`
- squelch and audio activity thresholds/timers
- `stream_config`
- `status`, `stream_id`, `last_active_at`, `current_activity_id`
- `revision`

## Scanner Object Model

Each scanner includes:

- `id`, `name`
- `frequencies_hz`, `priority_frequencies_hz`
- `modulation`, `bandwidth_hz`
- `dwell_ms`, `hold_ms`, `resume_delay_ms`
- `mode` (`retune` or `in_band`)
- `protect_fixed_channels`, `enabled`, `running`
- `last_hit_at`, `last_frequency_hz`, `revision`

## Activity Object Model

Each activity includes:

- `id`
- `channel_id`, `channel_label`
- `frequency_hz`
- `start_timestamp`, `end_timestamp`
- `duration_ms`
- `peak_signal_db`
- `peak_audio_dbfs`
- `state`
- `audio_available`

## Stream Model

Each stream includes:

- `id`
- `channel_id`
- `transport`
- `format`
- `sample_rate_hz`
- `state`
- `url`

## Event Model

Events include:

- `event_type`
- `timestamp`
- `channel_id` when applicable
- `scanner_id` when applicable
- `activity_id` when applicable
- `message`
- `rf_level_db`
- `audio_level_dbfs`
- `frequency_hz`
- `metadata`

## Endpoint Summary

### Radio
- `GET /api/v1/radio/capabilities`
- `GET /api/v1/radio/state`
- `PATCH /api/v1/radio/state`
- `POST /api/v1/radio/retune`

### Channels
- `GET /api/v1/channels`
- `POST /api/v1/channels`
- `POST /api/v1/channels/validate`
- `GET /api/v1/channels/{id}`
- `PATCH /api/v1/channels/{id}`
- `DELETE /api/v1/channels/{id}`

### Scanners
- `GET /api/v1/scanners`
- `POST /api/v1/scanners`
- `GET /api/v1/scanners/{id}`
- `PATCH /api/v1/scanners/{id}`
- `DELETE /api/v1/scanners/{id}`
- `POST /api/v1/scanners/{id}/start`
- `POST /api/v1/scanners/{id}/stop`

### Activities
- `GET /api/v1/activities`
- `GET /api/v1/activities/{id}`
- `GET /api/v1/activities/{id}/audio`

### Streams
- `GET /api/v1/streams`
- `GET /api/v1/streams/{id}`
- `GET /api/v1/streams/{id}/http`

### System
- `GET /healthz`
- `GET /readyz`
- `GET /metrics`
