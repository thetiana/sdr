# Startup Flow and Error Handling

## Startup Sequence

1. Load environment variables.
2. Configure JSON logging.
3. Initialize SDR provider abstraction.
4. Validate startup defaults against capabilities.
5. Expose readiness as `ready` if initialization succeeds.
6. Start housekeeping loop to expire memory-only activity audio.
7. Accept API clients and WebSocket subscribers.

## Readiness Semantics

- `/healthz` reports process liveness.
- `/readyz` reports whether radio initialization completed successfully.
- if future SDR hardware disconnect handling marks the radio unavailable, `/readyz` should return `503` while `/healthz` can remain healthy.

## Error Handling Strategy

### Startup failures
- invalid startup antenna/sample rate/bandwidth with strict checks enabled cause process startup failure.
- missing or unsupported SDRs should map to explicit startup errors in a real provider.

### Request failures
- malformed payloads return FastAPI validation errors.
- unsupported settings return `422`.
- object revision conflicts return `409`.
- not-found objects return `404`.
- auth failures return `401`.

### Runtime event failures
- `error` events surface operator-visible issues.
- `overrun` events surface DSP pressure or sample loss conditions.

## Container Deployment Notes

- In Docker Compose, place both services on the same user-defined bridge network.
- For browser access, terminate API traffic at the web UI container and reverse-proxy to `sdr-runtime` over the internal network.
- For USB SDR access, mount `/dev/bus/usb` and allow USB character-device access (for example with device cgroup rules for major 189).
- Set `SDR_SERIAL` when multiple SDRs may be present so startup selects the expected device deterministically.
