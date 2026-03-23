import base64
import math
import time

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def _fm_iq_bytes(
    *,
    sample_rate_hz: int,
    duration_s: float,
    center_frequency_hz: int,
    channel_frequency_hz: int,
    tone_hz: float = 1000.0,
    deviation_hz: float = 2500.0,
    amplitude: float = 0.9,
) -> bytes:
    sample_count = int(sample_rate_hz * duration_s)
    phase = 0.0
    interleaved = bytearray(sample_count * 2)
    for index in range(sample_count):
        modulating_tone = math.sin(2 * math.pi * tone_hz * index / sample_rate_hz)
        instantaneous_frequency = channel_frequency_hz - center_frequency_hz + deviation_hz * modulating_tone
        phase += 2 * math.pi * instantaneous_frequency / sample_rate_hz
        i_value = int(max(0, min(255, math.cos(phase) * amplitude * 127.0 + 127.5)))
        q_value = int(max(0, min(255, math.sin(phase) * amplitude * 127.0 + 127.5)))
        interleaved[index * 2] = i_value
        interleaved[index * 2 + 1] = q_value
    return bytes(interleaved)


def _noise_iq_bytes(sample_count: int) -> bytes:
    interleaved = bytearray(sample_count * 2)
    for index in range(sample_count):
        i_value = 127 + ((index * 7) % 5) - 2
        q_value = 127 + ((index * 11) % 5) - 2
        interleaved[index * 2] = i_value
        interleaved[index * 2 + 1] = q_value
    return bytes(interleaved)


def test_radio_state_and_channel_lifecycle() -> None:
    state = client.get("/api/v1/radio/state")
    assert state.status_code == 200
    payload = state.json()
    assert payload["ready"] is True

    channel_req = {
        "label": "Weather",
        "frequency_hz": 162400000,
        "modulation": "NFM",
        "bandwidth_hz": 12500,
        "audio_rate_hz": 16000,
    }
    created = client.post("/api/v1/channels", json=channel_req)
    assert created.status_code == 201, created.text
    channel_id = created.json()["id"]

    activated = client.post(f"/api/v1/debug/channels/{channel_id}/activate")
    assert activated.status_code == 200
    activity_id = activated.json()["activity_id"]

    idle = client.post(f"/api/v1/debug/channels/{channel_id}/idle")
    assert idle.status_code == 200

    audio = client.get(f"/api/v1/activities/{activity_id}/audio")
    assert audio.status_code == 200
    assert audio.json()["activity_id"] == activity_id


def test_scanner_conflict_guard() -> None:
    channel_req = {
        "label": "Fire",
        "frequency_hz": 162450000,
        "modulation": "NFM",
        "bandwidth_hz": 12500,
        "audio_rate_hz": 16000,
    }
    created = client.post("/api/v1/channels", json=channel_req)
    assert created.status_code == 201
    scanner = client.post(
        "/api/v1/scanners",
        json={
            "name": "Metro Sweep",
            "frequencies_hz": [162450000, 162500000],
            "modulation": "NFM",
            "bandwidth_hz": 12500,
            "mode": "retune",
            "protect_fixed_channels": True,
        },
    )
    assert scanner.status_code == 409


def test_mock_sample_processing_emits_activity_and_audio() -> None:
    health = client.get("/healthz")
    assert health.status_code == 200
    runtime_state = app.state.runtime_state
    runtime_state.radio_state.sample_rate_hz = 960_000
    runtime_state.radio_state.center_frequency_hz = 162_400_000

    created = client.post(
        "/api/v1/channels",
        json={
            "label": "Live NFM",
            "frequency_hz": 162400000,
            "modulation": "NFM",
            "bandwidth_hz": 12500,
            "audio_rate_hz": 16000,
            "activity_attack_ms": 50,
            "activity_release_ms": 100,
            "pre_roll_ms": 100,
            "post_roll_ms": 100,
        },
    )
    assert created.status_code == 201, created.text
    channel_id = created.json()["id"]

    provider = app.state.radio_provider
    iq_bytes = _fm_iq_bytes(
        sample_rate_hz=runtime_state.radio_state.sample_rate_hz,
        duration_s=0.25,
        center_frequency_hz=runtime_state.radio_state.center_frequency_hz,
        channel_frequency_hz=162_400_000,
    )
    provider.push_samples(iq_bytes)
    time.sleep(0.25)

    channel = client.get(f"/api/v1/channels/{channel_id}")
    assert channel.status_code == 200
    assert channel.json()["status"] == "active"
    activity_id = channel.json()["current_activity_id"]
    assert activity_id

    provider.push_samples(_noise_iq_bytes(len(iq_bytes) // 2))
    time.sleep(0.30)

    history = client.get("/api/v1/events")
    assert history.status_code == 200
    event_types = [event["event_type"] for event in history.json() if event.get("channel_id") == channel_id]
    assert "channel_active" in event_types
    assert "channel_idle" in event_types

    activity = client.get(f"/api/v1/activities/{activity_id}")
    assert activity.status_code == 200
    assert activity.json()["audio_available"] is True

    audio = client.get(f"/api/v1/activities/{activity_id}/audio")
    assert audio.status_code == 200
    wav_bytes = base64.b64decode(audio.json()["base64_audio"])
    assert wav_bytes[:4] == b"RIFF"
