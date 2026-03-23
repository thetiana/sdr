from __future__ import annotations

import asyncio
import base64
import logging
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status

from .config import Settings
from .metrics import active_channels, active_scanners, active_streams, activity_events, overruns
from .models import (
    Activity,
    ActivityAudio,
    Channel,
    ChannelCreate,
    ChannelPatch,
    ChannelValidationRequest,
    EventPayload,
    RadioCapabilities,
    RadioRetuneRequest,
    RadioState,
    RadioStatePatch,
    Scanner,
    ScannerCreate,
    ScannerPatch,
    Stream,
)

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self, history_limit: int) -> None:
        self._subscribers: set[asyncio.Queue[EventPayload]] = set()
        self._history: deque[EventPayload] = deque(maxlen=history_limit)
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue[EventPayload]:
        queue: asyncio.Queue[EventPayload] = asyncio.Queue(maxsize=100)
        async with self._lock:
            self._subscribers.add(queue)
            for item in self._history:
                await queue.put(item)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[EventPayload]) -> None:
        async with self._lock:
            self._subscribers.discard(queue)

    async def publish(self, payload: EventPayload) -> None:
        async with self._lock:
            self._history.append(payload)
            dead: list[asyncio.Queue[EventPayload]] = []
            for queue in self._subscribers:
                try:
                    queue.put_nowait(payload)
                except asyncio.QueueFull:
                    dead.append(queue)
            for queue in dead:
                self._subscribers.discard(queue)

    def history(self) -> list[EventPayload]:
        return list(self._history)


class RuntimeState:
    def __init__(self, settings: Settings, capabilities: RadioCapabilities, radio_state: RadioState) -> None:
        self.settings = settings
        self.capabilities = capabilities
        self.radio_state = radio_state
        self.channels: dict[str, Channel] = {}
        self.scanners: dict[str, Scanner] = {}
        self.streams: dict[str, Stream] = {}
        self.activities: dict[str, Activity] = {}
        self.activity_audio: dict[str, ActivityAudio] = {}
        self.lock = asyncio.Lock()
        self.event_bus = EventBus(settings.event_history_limit)
        self.ready = radio_state.ready

    def _window_bounds(self) -> tuple[int, int]:
        half = self.radio_state.sample_rate_hz // 2
        return self.radio_state.center_frequency_hz - half, self.radio_state.center_frequency_hz + half

    def ensure_channel_inside_window(self, frequency_hz: int, bandwidth_hz: int) -> None:
        low, high = self._window_bounds()
        margin = bandwidth_hz // 2
        if frequency_hz - margin < low or frequency_hz + margin > high:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"channel frequency {frequency_hz} with bandwidth {bandwidth_hz} is outside current capture window [{low}, {high}]",
            )

    def _validate_modulation(self, modulation: str) -> None:
        if modulation not in {m.value for m in self.capabilities.supported_modulations}:
            raise HTTPException(status_code=422, detail=f"unsupported modulation: {modulation}")

    def _validate_limits(self) -> None:
        if len(self.channels) > self.settings.max_channels:
            raise HTTPException(status_code=409, detail="channel limit exceeded")
        if len(self.scanners) > self.settings.max_scanners:
            raise HTTPException(status_code=409, detail="scanner limit exceeded")
        if len(self.streams) > self.settings.max_streams:
            raise HTTPException(status_code=409, detail="stream limit exceeded")

    async def patch_radio_state(self, patch: RadioStatePatch) -> RadioState:
        async with self.lock:
            if patch.if_revision is not None and patch.if_revision != self.radio_state.revision:
                raise HTTPException(status_code=409, detail="stale radio state revision")
            data = self.radio_state.model_dump()
            for key, value in patch.model_dump(exclude_none=True, exclude={"if_revision"}).items():
                data[key] = value
            data["revision"] = self.radio_state.revision + 1
            updated = RadioState(**data)
            self._validate_radio_state(updated)
            self.radio_state = updated
            self.ready = updated.ready
            return self.radio_state

    async def retune(self, req: RadioRetuneRequest) -> RadioState:
        async with self.lock:
            if self.settings.retune_policy == "deny" and not req.force and self.channels:
                for channel in self.channels.values():
                    if channel.enabled:
                        raise HTTPException(status_code=409, detail="retune denied while enabled channels exist; set force=true if allowed")
            self.radio_state.center_frequency_hz = req.center_frequency_hz
            self.radio_state.revision += 1
            await self.event_bus.publish(
                EventPayload(
                    event_type="radio_retuned",
                    timestamp=datetime.now(UTC),
                    frequency_hz=req.center_frequency_hz,
                    metadata={"forced": req.force},
                )
            )
            return self.radio_state

    def _validate_radio_state(self, state: RadioState) -> None:
        caps = self.capabilities
        if state.antenna not in caps.antennas:
            raise HTTPException(status_code=422, detail=f"unsupported antenna: {state.antenna}")
        if state.sample_rate_hz not in caps.supported_sample_rates_hz:
            raise HTTPException(status_code=422, detail=f"unsupported sample rate: {state.sample_rate_hz}")
        if state.bandwidth_hz not in caps.bandwidth_options_hz:
            raise HTTPException(status_code=422, detail=f"unsupported bandwidth: {state.bandwidth_hz}")

    async def validate_channel(self, req: ChannelValidationRequest) -> dict[str, Any]:
        async with self.lock:
            self._validate_modulation(req.modulation.value)
            self.ensure_channel_inside_window(req.frequency_hz, req.bandwidth_hz)
            return {"valid": True, "window": self._window_bounds(), "retune_policy": self.settings.retune_policy}

    async def create_channel(self, req: ChannelCreate) -> Channel:
        async with self.lock:
            if len(self.channels) >= self.settings.max_channels:
                raise HTTPException(status_code=409, detail="channel limit exceeded")
            self._validate_modulation(req.modulation.value)
            self.ensure_channel_inside_window(req.frequency_hz, req.bandwidth_hz)
            channel = Channel(**req.model_dump(exclude_none=True))
            if not channel.enabled:
                channel.status = "disabled"
            stream = Stream(
                channel_id=channel.id,
                transport=channel.stream_config.transport,
                format=channel.stream_config.format,
                sample_rate_hz=channel.audio_rate_hz,
                state="idle",
                url="",
            )
            stream.url = f"/api/v1/streams/{stream.id}"
            channel.stream_id = stream.id
            self.channels[channel.id] = channel
            self.streams[stream.id] = stream
            self._refresh_metrics()
            return channel

    async def patch_channel(self, channel_id: str, patch: ChannelPatch) -> Channel:
        async with self.lock:
            channel = self.get_channel(channel_id)
            if patch.if_revision is not None and patch.if_revision != channel.revision:
                raise HTTPException(status_code=409, detail="stale channel revision")
            data = channel.model_dump()
            for key, value in patch.model_dump(exclude_none=True, exclude={"if_revision"}).items():
                data[key] = value
            data["revision"] = channel.revision + 1
            updated = Channel(**data)
            self.ensure_channel_inside_window(updated.frequency_hz, updated.bandwidth_hz)
            if not updated.enabled:
                updated.status = "disabled"
            elif updated.status == "disabled":
                updated.status = "idle"
            if updated.stream_id and updated.stream_id in self.streams:
                stream = self.streams[updated.stream_id]
                stream.transport = updated.stream_config.transport
                stream.format = updated.stream_config.format
                stream.sample_rate_hz = updated.audio_rate_hz
                if not updated.enabled:
                    stream.state = "idle"
            self.channels[channel_id] = updated
            self._refresh_metrics()
            return updated

    async def delete_channel(self, channel_id: str) -> None:
        async with self.lock:
            channel = self.get_channel(channel_id)
            if channel.stream_id:
                self.streams = {k: v for k, v in self.streams.items() if v.id != channel.stream_id}
            self.channels.pop(channel_id)
            self._refresh_metrics()

    def get_channel(self, channel_id: str) -> Channel:
        channel = self.channels.get(channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="channel not found")
        return channel

    async def create_scanner(self, req: ScannerCreate) -> Scanner:
        async with self.lock:
            if len(self.scanners) >= self.settings.max_scanners:
                raise HTTPException(status_code=409, detail="scanner limit exceeded")
            if req.mode == "retune" and req.protect_fixed_channels and any(ch.enabled for ch in self.channels.values()):
                raise HTTPException(status_code=409, detail="retune scanner conflicts with enabled channels; disable protect_fixed_channels to override")
            scanner = Scanner(**req.model_dump(exclude_none=True))
            self.scanners[scanner.id] = scanner
            self._refresh_metrics()
            return scanner

    async def patch_scanner(self, scanner_id: str, patch: ScannerPatch) -> Scanner:
        async with self.lock:
            scanner = self.get_scanner(scanner_id)
            if patch.if_revision is not None and patch.if_revision != scanner.revision:
                raise HTTPException(status_code=409, detail="stale scanner revision")
            data = scanner.model_dump()
            for key, value in patch.model_dump(exclude_none=True, exclude={"if_revision"}).items():
                data[key] = value
            data["revision"] = scanner.revision + 1
            updated = Scanner(**data)
            self.scanners[scanner_id] = updated
            self._refresh_metrics()
            return updated

    async def delete_scanner(self, scanner_id: str) -> None:
        async with self.lock:
            self.get_scanner(scanner_id)
            self.scanners.pop(scanner_id)
            self._refresh_metrics()

    def get_scanner(self, scanner_id: str) -> Scanner:
        scanner = self.scanners.get(scanner_id)
        if not scanner:
            raise HTTPException(status_code=404, detail="scanner not found")
        return scanner

    async def set_scanner_running(self, scanner_id: str, running: bool) -> Scanner:
        async with self.lock:
            scanner = self.get_scanner(scanner_id)
            scanner.running = running
            scanner.revision += 1
            if running and scanner.frequencies_hz:
                scanner.last_hit_at = datetime.now(UTC)
                scanner.last_frequency_hz = scanner.priority_frequencies_hz[0] if scanner.priority_frequencies_hz else scanner.frequencies_hz[0]
                await self.event_bus.publish(
                    EventPayload(
                        event_type="scanner_hit",
                        timestamp=scanner.last_hit_at,
                        scanner_id=scanner.id,
                        frequency_hz=scanner.last_frequency_hz,
                        metadata={"mode": scanner.mode},
                    )
                )
                activity_events.labels(event_type="scanner_hit").inc()
            self._refresh_metrics()
            return scanner

    async def simulate_activity(self, channel_id: str, active: bool, *, scanner_id: str | None = None) -> EventPayload:
        async with self.lock:
            channel = self.get_channel(channel_id)
            now = datetime.now(UTC)
            if active:
                activity = Activity(
                    channel_id=channel.id,
                    channel_label=channel.label,
                    frequency_hz=channel.frequency_hz,
                    start_timestamp=now,
                    peak_signal_db=channel.squelch_threshold_db + 8,
                    peak_audio_dbfs=channel.audio_activity_threshold_dbfs + 6,
                )
                self.activities[activity.id] = activity
                channel.status = "active"
                channel.last_active_at = now
                channel.current_activity_id = activity.id
                if channel.stream_id:
                    stream = self.streams.get(channel.stream_id)
                    if stream:
                        stream.state = "streaming"
                payload = EventPayload(
                    event_type="channel_active",
                    timestamp=now,
                    channel_id=channel.id,
                    activity_id=activity.id,
                    scanner_id=scanner_id,
                    rf_level_db=activity.peak_signal_db,
                    audio_level_dbfs=activity.peak_audio_dbfs,
                    frequency_hz=channel.frequency_hz,
                )
                activity_events.labels(event_type="channel_active").inc()
            else:
                activity_id = channel.current_activity_id
                if not activity_id or activity_id not in self.activities:
                    raise HTTPException(status_code=409, detail="channel has no active activity")
                activity = self.activities[activity_id]
                activity.end_timestamp = now
                activity.duration_ms = max(1, int((now - activity.start_timestamp).total_seconds() * 1000))
                activity.state = "completed"
                activity.audio_available = True
                expires_at = now + timedelta(seconds=self.settings.activity_audio_ttl_seconds)
                fake_wav = base64.b64encode(f"activity {activity.id}".encode()).decode()
                self.activity_audio[activity.id] = ActivityAudio(activity_id=activity.id, base64_audio=fake_wav, expires_at=expires_at)
                channel.status = "idle" if channel.enabled else "disabled"
                channel.current_activity_id = None
                if channel.stream_id:
                    stream = self.streams.get(channel.stream_id)
                    if stream:
                        stream.state = "buffered"
                payload = EventPayload(
                    event_type="channel_idle",
                    timestamp=now,
                    channel_id=channel.id,
                    activity_id=activity.id,
                    scanner_id=scanner_id,
                    rf_level_db=activity.peak_signal_db,
                    audio_level_dbfs=activity.peak_audio_dbfs,
                    frequency_hz=channel.frequency_hz,
                )
                activity_events.labels(event_type="channel_idle").inc()
            await self.event_bus.publish(payload)
            self._refresh_metrics()
            return payload

    async def emit_error(self, message: str) -> EventPayload:
        payload = EventPayload(event_type="error", timestamp=datetime.now(UTC), message=message)
        await self.event_bus.publish(payload)
        return payload

    async def emit_overrun(self, message: str) -> EventPayload:
        payload = EventPayload(event_type="overrun", timestamp=datetime.now(UTC), message=message)
        overruns.inc()
        await self.event_bus.publish(payload)
        return payload

    def cleanup_activity_audio(self) -> None:
        now = datetime.now(UTC)
        expired = [activity_id for activity_id, audio in self.activity_audio.items() if audio.expires_at <= now]
        for activity_id in expired:
            self.activity_audio.pop(activity_id, None)

    def _refresh_metrics(self) -> None:
        active_channels.set(sum(1 for ch in self.channels.values() if ch.status == "active"))
        active_scanners.set(sum(1 for sc in self.scanners.values() if sc.running))
        active_streams.set(sum(1 for st in self.streams.values() if st.state != "idle"))


class MockSdrProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def startup(self) -> tuple[RadioCapabilities, RadioState]:
        capabilities = RadioCapabilities(
            device_name="Mock RTL-SDR / Soapy-compatible",
            serial=self.settings.sdr_serial or "MOCK0001",
            driver=self.settings.sdr_driver,
            frequency_range={"min_hz": 24_000_000, "max_hz": 1_766_000_000},
            supported_sample_rates_hz=[960_000, 1_200_000, 1_800_000, 2_400_000],
            bandwidth_range_hz={"min_hz": 12_500, "max_hz": 2_400_000},
            bandwidth_options_hz=[12_500, 25_000, 200_000, 2_000_000],
            gain_controls=[{"name": "LNA", "min_db": 0, "max_db": 49.6, "step_db": 0.8}],
            agc_supported=True,
            antennas=["RX", "HI-Z"],
            dc_offset_supported=False,
            iq_balance_supported=False,
            supported_modulations=["NFM", "AM", "WFM"],
            recommended_runtime_limits={
                "max_channels": self.settings.max_channels,
                "max_scanners": self.settings.max_scanners,
                "max_streams": self.settings.max_streams,
            },
        )
        state = RadioState(
            center_frequency_hz=self.settings.initial_center_frequency_hz,
            sample_rate_hz=self.settings.initial_sample_rate_hz,
            bandwidth_hz=self.settings.initial_bandwidth_hz,
            gain_mode=self.settings.initial_gain_mode,
            gain_db=self.settings.initial_gain_db,
            ppm=self.settings.initial_ppm,
            antenna=self.settings.initial_antenna,
            bias_tee=self.settings.initial_bias_tee,
            ready=True,
        )
        if self.settings.strict_capability_check:
            if state.antenna not in capabilities.antennas:
                raise RuntimeError(f"Unsupported antenna configured: {state.antenna}")
            if state.sample_rate_hz not in capabilities.supported_sample_rates_hz:
                raise RuntimeError(f"Unsupported sample rate configured: {state.sample_rate_hz}")
            if state.bandwidth_hz not in capabilities.bandwidth_options_hz:
                raise RuntimeError(f"Unsupported bandwidth configured: {state.bandwidth_hz}")
        else:
            if state.antenna not in capabilities.antennas:
                logger.warning("Configured antenna unsupported; continuing with default RX")
                state.antenna = capabilities.antennas[0]
        return capabilities, state
