from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


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
