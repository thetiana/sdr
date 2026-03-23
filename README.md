# SDR Monitoring Platform

A production-oriented foundation for a **two-container, stateless SDR monitoring platform**:

1. **`sdr-runtime`** — owns the SDR device abstraction, runtime radio state, dynamic channels, scanners, activity detection model, logical audio streams, metrics, and public API.
2. **`sdr-webui`** — provides an operator-friendly dashboard that talks to `sdr-runtime` **only through the documented public API**.

> This repository includes both a real RTL-SDR path and a mock provider. The runtime now continuously processes incoming IQ blocks, performs in-band carrier/activity detection for configured channels, and buffers demodulated mono WAV audio for completed activities.

## Project Overview

### Key goals implemented

- stateless runtime container with clean restart semantics;
- no database dependency for normal operation;
- dynamic channel and scanner creation/removal over API;
- structured activity/event model with memory-only audio buffering;
- Prometheus metrics, health, readiness, and JSON logs;
- operator-focused web UI with channel, scanner, and event management;
- Dockerfiles for both containers and a compose example.

## Architecture Overview

```mermaid
flowchart LR
    Browser --> WebUI[sdr-webui]
    WebUI -->|REST + WebSocket| Runtime[sdr-runtime]
    Runtime --> SDR[SDR provider abstraction]
    Runtime --> DSP[Wideband capture + channel workers]
    Runtime --> Events[Event bus]
    Runtime --> Buffers[Memory-only activity audio]
    Runtime --> Metrics[/metrics]
```

### How the containers interact

- `sdr-webui` reverse-proxies browser requests to `sdr-runtime` over the internal Docker network so the browser never has to resolve the Compose service name directly.
- `sdr-webui` subscribes to `sdr-runtime` WebSocket events through that same reverse-proxied path for live status updates.
- no shared filesystem, database, or internal implementation coupling exists between the containers.

## Repository Structure

```text
.
├── docker-compose.yml
├── docs/
│   ├── api-models.md
│   ├── design-decisions.md
│   ├── runtime-architecture.md
│   ├── startup-flow.md
│   └── ui-architecture.md
├── examples/
│   ├── runtime-channel-create.json
│   └── runtime-scanner-create.json
├── sdr-runtime/
│   ├── app/
│   ├── tests/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example
└── sdr-webui/
    ├── public/
    ├── src/
    ├── Dockerfile
    ├── nginx.conf.template
    ├── docker-entrypoint.sh
    ├── package.json
    └── .env.example
```

## Supported Features

### `sdr-runtime`

- SDR selection and startup defaults via environment variables.
- capability discovery endpoint.
- versioned API under `/api/v1`.
- dynamic channels with NFM, AM, and WFM validation.
- live in-band RTL-SDR activity detection for enabled channels inside the current capture window.
- scanner objects with conflict checks.
- structured activities with unique `activity_id` values driven either by live IQ processing or debug endpoints.
- memory-only buffered demodulated WAV audio with expiry.
- logical stream model without one Docker port per channel.
- WebSocket event delivery.
- JSON logs, health/readiness endpoints, and Prometheus metrics.
- thread-safe mutable state with revision support.

### `sdr-webui`

- runtime connectivity and readiness summary.
- SDR capability display.
- create/edit/delete/toggle/mute channel workflows.
- create/edit/delete/start/stop scanner workflows.
- live event feed and recent activities panel.
- responsive dashboard layout suitable for operator use.

## Environment Variables

### Runtime container (`sdr-runtime`)

| Variable | Description | Default |
|---|---|---|
| `API_BIND` | Bind address for the API server. | `0.0.0.0` |
| `API_PORT` | API listening port. | `8081` |
| `AUTH_TOKEN` | Bearer token for REST and WebSocket auth. | `sdr-dev-token` |
| `CORS_ORIGINS` | Comma-separated allowed UI origins. | `http://localhost:3001` |
| `METRICS_ENABLED` | Enable `/metrics`. | `true` |
| `LOG_LEVEL` | JSON log level. | `INFO` |
| `SDR_SERIAL` | Preferred device serial. Set this for stable device selection in multi-SDR hosts. | unset |
| `SDR_DRIVER` | SDR backend identifier. Docker Compose defaults to `rtl-sdr`; use `mock-soapysdr` for synthetic/debug runs without hardware. | `mock-soapysdr` |
| `INITIAL_CENTER_FREQUENCY_HZ` | Startup center frequency. | `162400000` |
| `INITIAL_SAMPLE_RATE_HZ` | Startup sample rate. | `2400000` |
| `INITIAL_BANDWIDTH_HZ` | Startup bandwidth. | `2000000` |
| `INITIAL_GAIN_MODE` | Startup gain mode. | `manual` |
| `INITIAL_GAIN_DB` | Startup gain in dB. | `25` |
| `INITIAL_PPM` | Frequency correction. | `0` |
| `INITIAL_ANTENNA` | Startup antenna. | `RX` |
| `INITIAL_BIAS_TEE` | Bias tee toggle. | `false` |
| `SDR_FALLBACK_TO_MOCK_ON_ERROR` | When `true`, startup falls back to the mock provider if the RTL-SDR backend cannot open hardware, while preserving the original startup error in runtime state/events. | `true` |
| `STRICT_CAPABILITY_CHECK` | Fail startup on unsupported defaults. | `true` |
| `RETUNE_POLICY` | `deny` or `allow` retune policy. | `deny` |
| `MAX_CHANNELS` | Maximum in-memory channels. | `32` |
| `MAX_SCANNERS` | Maximum scanners. | `8` |
| `MAX_STREAMS` | Maximum logical streams. | `32` |
| `EVENT_HISTORY_LIMIT` | Event history length. | `200` |
| `PRE_ROLL_MS_DEFAULT` | Default activity pre-roll. | `1000` |
| `POST_ROLL_MS_DEFAULT` | Default activity post-roll. | `1000` |
| `ACTIVITY_AUDIO_TTL_SECONDS` | Expiration for memory-only activity audio. | `900` |

### Web UI container (`sdr-webui`)

| Variable | Description | Default |
|---|---|---|
| `SDR_API_BASE_URL` | Browser-facing runtime base URL. Use `/runtime-api` when the UI reverse-proxies the runtime. | `/runtime-api` |
| `SDR_API_TOKEN` | Bearer token used by the browser client. | `sdr-dev-token` |
| `SDR_RUNTIME_UPSTREAM` | Internal upstream host:port that NGINX proxies to from the UI container. | `sdr-runtime:8081` |
| `UI_BIND` | Documented for deployment metadata/config rendering. | `0.0.0.0` |
| `UI_PORT` | Internal NGINX listen port inside the container. Docker Compose maps host port `3001` to this container port. | `80` |

See `sdr-runtime/.env.example` and `sdr-webui/.env.example` for templates.

## Build Instructions

### Build both images

```bash
docker compose build
```

### Build runtime only

```bash
docker build -t sdr-runtime ./sdr-runtime
```

### Build web UI only

```bash
docker build -t sdr-webui ./sdr-webui
```

## Run Instructions

### Docker Compose

```bash
docker compose up --build
```

- Runtime API: `http://localhost:8081`
- Runtime docs: `http://localhost:8081/docs`
- Web UI: `http://localhost:3001`

### Standalone runtime

```bash
cd sdr-runtime
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8081
```

### Standalone UI

```bash
cd sdr-webui
npm install
cp .env.example .env
npm run dev
```

## API Overview

### Required endpoint groups implemented

- **Radio**: capabilities, state, patch, retune
- **Channels**: list/create/get/patch/delete plus validation
- **Scanners**: list/create/get/patch/delete/start/stop
- **Activities**: list/get/get audio
- **Streams**: list/get plus HTTP chunked example endpoint
- **System**: health, readiness, metrics
- **Events**: WebSocket stream and history endpoint

### Example usage

Create a channel:

```bash
curl -X POST http://localhost:8081/api/v1/channels \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer sdr-dev-token' \
  -d @examples/runtime-channel-create.json
```

Create a scanner:

```bash
curl -X POST http://localhost:8081/api/v1/scanners \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer sdr-dev-token' \
  -d @examples/runtime-scanner-create.json
```

Trigger a simulated activity window for demo/testing:

```bash
curl -X POST http://localhost:8081/api/v1/debug/channels/<channel-id>/activate \
  -H 'Authorization: Bearer sdr-dev-token'
```

Fetch memory-only buffered audio metadata:

```bash
curl http://localhost:8081/api/v1/activities/<activity-id>/audio \
  -H 'Authorization: Bearer sdr-dev-token'
```

## UI Overview

The web UI shows:

- connection and readiness badges;
- SDR identity and current operating state;
- capability summaries;
- channel form plus channel inventory table;
- scanner form plus scanner control cards;
- live event feed and activity list.

## Example Workflows

### 1. Bring up the stack

1. Run `docker compose up --build`.
2. Open `http://localhost:3001`.
3. The stack starts with the built-in development token `sdr-dev-token` unless you override `SDR_API_TOKEN`, and Docker maps browser port `3001` to NGINX port `80` inside the container.
4. Confirm the dashboard reports **Connected** and **Ready**.

### 2. Create an in-band channel

1. Choose a frequency inside the current RF window.
2. Submit the channel form.
3. Observe the new logical stream record and channel row.

### 3. Start a scanner

1. Add a scanner frequency list.
2. Use `retune` or `in_band` mode depending operational intent.
3. Start the scanner and watch the live event feed for `scanner_hit` events.

### 4. Simulate activity in the foundation build

1. Create a channel.
2. Call the debug activation endpoint.
3. Watch the UI event feed show `channel_active`.
4. Call the debug idle endpoint.
5. Fetch `/api/v1/activities/{id}/audio` for the buffered clip metadata.

## Troubleshooting

### Runtime will not start

- verify startup antenna, sample rate, and bandwidth match capability output;
- if using strict mode, unsupported defaults intentionally fail startup;
- set `SDR_SERIAL` when you want deterministic hardware selection;
- confirm `/dev/bus/usb` is mounted into the runtime container and that the container has access to the USB device node;
- inspect JSON logs from `sdr-runtime`.

### UI shows disconnected or the browser reports `NetworkError when attempting to fetch resource`

- when running with Docker Compose, keep `SDR_API_BASE_URL=/runtime-api` so the browser uses the web UI container as a reverse proxy;
- open the UI on `http://localhost:3001` and the direct runtime API on `http://localhost:8081`;
- do **not** point the browser at `http://sdr-runtime:8081`, because that hostname only resolves inside the Docker network, not in the user browser;
- confirm `SDR_RUNTIME_UPSTREAM=sdr-runtime:8081` and that both services are attached to the `sdr-net` Compose network;
- confirm `SDR_API_TOKEN` matches `AUTH_TOKEN` (default: `sdr-dev-token`).

### Channel creation fails

- check whether the channel frequency falls outside the current capture window;
- confirm the requested modulation is one of `NFM`, `AM`, or `WFM`;
- verify runtime limits are not exceeded.

### Scanner creation fails

- retune scanners can be blocked when fixed channels are protected;
- reduce conflicts or disable `protect_fixed_channels` intentionally.

### `/readyz` fails but `/healthz` passes

- the API process is alive, but the radio subsystem is not ready for service;
- check startup config and future SDR provider error details.

## Limitations

- this foundation now supports RTL-SDR hardware initialization, but the wider DSP/audio pipeline is still mostly scaffolded and mock-friendly;
- audio transport is represented logically and via demo HTTP chunking rather than real demodulated PCM;
- activity audio payloads are demo placeholders to validate the API shape;
- runtime state is intentionally non-persistent.

## Future Extension Points

- real SDR drivers and DSP workers;
- RTP streaming and transcoding;
- external webhook/event sinks;
- speech-to-text and AI analysis consumers;
- richer authN/authZ and auditing;
- persistent optional configuration service if later desired.

## Detailed Technical Documentation

- [`docs/runtime-architecture.md`](docs/runtime-architecture.md)
- [`docs/ui-architecture.md`](docs/ui-architecture.md)
- [`docs/api-models.md`](docs/api-models.md)
- [`docs/startup-flow.md`](docs/startup-flow.md)
- [`docs/design-decisions.md`](docs/design-decisions.md)

## Screenshot / Mockup Note

A browser screenshot artifact was not generated in this environment because the required browser screenshot tool was not available. The UI source and styling are included in full so the dashboard can be built locally or with Docker.
