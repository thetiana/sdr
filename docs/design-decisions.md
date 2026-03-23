# Design Decisions and Known Limitations

## Why FastAPI

FastAPI provides:

- automatic OpenAPI generation;
- async-friendly request handling;
- easy ARM64 container builds;
- straightforward WebSocket support.

## Why React + Vite

React + Vite offers:

- a modern but lightweight dashboard foundation;
- quick iteration and static asset builds;
- a good fit for an operator-focused SPA.

## Why In-Memory State

The platform goal explicitly prefers a stateless runtime container. In-memory state keeps restart semantics simple and makes API control the single source of truth.

## Known Limitations

This repository is a working foundation, not a hardware-complete SDR stack yet.

- SDR I/O now includes an RTL-SDR startup path, but the wider receive/demod pipeline is still scaffold-oriented and not yet a full production DSP implementation.
- demodulation/audio output is simulated through logical stream objects and debug activity endpoints.
- WebSocket auth uses a query token fallback because browser APIs cannot set arbitrary headers during basic `WebSocket` creation.
- UI runtime config is injected at container startup, but changing those values still requires container restart.
- no persistence is included by design.

## Future Extension Points

- real SoapySDR or vendor backends;
- RTP output and transcoding;
- external event webhooks;
- speech-to-text and AI pipeline consumers;
- RBAC and richer multi-user session management.
