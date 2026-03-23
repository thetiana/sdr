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
