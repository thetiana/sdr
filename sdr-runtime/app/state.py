from __future__ import annotations

import asyncio
import base64
import cmath
import io
import logging
import math
import threading
import wave
from array import array
from collections import deque
from dataclasses import dataclass, field
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


@dataclass
class ChannelSignalState:
    previous_baseband_sample: complex = 1 + 0j
    rolling_audio: deque[array] = field(default_factory=deque)
    rolling_audio_samples: int = 0
    captured_audio: list[array] = field(default_factory=list)
    active_ms: float = 0.0
    inactive_ms: float = 0.0


@dataclass
class ChannelSignalMetrics:
    rf_level_db: float
    audio_level_dbfs: float
    audio_pcm: array
    block_duration_ms: float
    carrier_detected: bool


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
        self.channel_signal_state: dict[str, ChannelSignalState] = {}
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
            self.channel_signal_state[channel.id] = ChannelSignalState()
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
                    self.channel_signal_state.pop(channel_id, None)
            self.channels[channel_id] = updated
            self._refresh_metrics()
            return updated

    async def delete_channel(self, channel_id: str) -> None:
        async with self.lock:
            channel = self.get_channel(channel_id)
            if channel.stream_id:
                self.streams = {k: v for k, v in self.streams.items() if v.id != channel.stream_id}
            self.channels.pop(channel_id)
            self.channel_signal_state.pop(channel_id, None)
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

    async def process_iq_samples(self, iq_bytes: bytes) -> None:
        iq = self._decode_iq_bytes(iq_bytes)
        if len(iq) < 2048:
            return

        async with self.lock:
            center_frequency_hz = self.radio_state.center_frequency_hz
            sample_rate_hz = self.radio_state.sample_rate_hz
            channels = [channel for channel in self.channels.values() if channel.enabled]

        events: list[EventPayload] = []
        for channel in channels:
            if not self._channel_fits_sample_window(channel.frequency_hz, channel.bandwidth_hz, center_frequency_hz, sample_rate_hz):
                continue
            metrics = self._analyze_channel_samples(iq, channel, center_frequency_hz, sample_rate_hz)
            event = await self._apply_channel_signal_update(channel.id, metrics)
            if event is not None:
                events.append(event)

        for event in events:
            await self.event_bus.publish(event)
        if events:
            self._refresh_metrics()

    def _decode_iq_bytes(self, iq_bytes: bytes) -> list[complex]:
        if len(iq_bytes) < 2:
            return []
        usable = len(iq_bytes) - (len(iq_bytes) % 2)
        decoded: list[complex] = []
        for index in range(0, usable, 2):
            i_value = (iq_bytes[index] - 127.5) / 128.0
            q_value = (iq_bytes[index + 1] - 127.5) / 128.0
            decoded.append(complex(i_value, q_value))
        return decoded

    def _channel_fits_sample_window(self, frequency_hz: int, bandwidth_hz: int, center_frequency_hz: int, sample_rate_hz: int) -> bool:
        half_window = sample_rate_hz / 2
        return abs(frequency_hz - center_frequency_hz) + (bandwidth_hz / 2) <= half_window

    def _signal_threshold_db(self, channel: Channel) -> float:
        metadata_threshold = channel.metadata.get("rf_excess_threshold_db")
        if isinstance(metadata_threshold, (int, float)):
            return float(metadata_threshold)
        if channel.squelch_threshold_db > 0:
            return channel.squelch_threshold_db
        return 10.0

    def _get_channel_signal_state(self, channel_id: str) -> ChannelSignalState:
        if channel_id not in self.channel_signal_state:
            self.channel_signal_state[channel_id] = ChannelSignalState()
        return self.channel_signal_state[channel_id]

    def _analyze_channel_samples(
        self,
        iq: list[complex],
        channel: Channel,
        center_frequency_hz: int,
        sample_rate_hz: int,
    ) -> ChannelSignalMetrics:
        frequency_offset_hz = channel.frequency_hz - center_frequency_hz
        shifted = self._mix_to_baseband(iq, frequency_offset_hz, sample_rate_hz)
        filtered = self._moving_average_complex(shifted, max(3, min(101, int(sample_rate_hz / max(channel.bandwidth_hz, 1)))))
        rf_level_db = self._estimate_rf_excess_db(shifted, filtered)
        audio_pcm = self._demodulate_audio(filtered, channel, sample_rate_hz)
        audio_level_dbfs = self._pcm_dbfs(audio_pcm)
        block_duration_ms = (len(iq) / sample_rate_hz) * 1000.0
        return ChannelSignalMetrics(
            rf_level_db=rf_level_db,
            audio_level_dbfs=audio_level_dbfs,
            audio_pcm=audio_pcm,
            block_duration_ms=block_duration_ms,
            carrier_detected=rf_level_db >= self._signal_threshold_db(channel),
        )

    def _mix_to_baseband(self, iq: list[complex], frequency_offset_hz: int, sample_rate_hz: int) -> list[complex]:
        if frequency_offset_hz == 0:
            return list(iq)
        mixed: list[complex] = []
        phase_step = -2.0 * math.pi * frequency_offset_hz / sample_rate_hz
        for index, sample in enumerate(iq):
            mixed.append(sample * cmath.exp(1j * phase_step * index))
        return mixed

    def _moving_average_complex(self, samples: list[complex], window_size: int) -> list[complex]:
        if not samples:
            return []
        window_size = max(1, min(window_size, len(samples)))
        averaged: list[complex] = []
        real_acc = 0.0
        imag_acc = 0.0
        real_window = deque()
        imag_window = deque()
        for sample in samples:
            real_window.append(sample.real)
            imag_window.append(sample.imag)
            real_acc += sample.real
            imag_acc += sample.imag
            if len(real_window) > window_size:
                real_acc -= real_window.popleft()
                imag_acc -= imag_window.popleft()
            averaged.append(complex(real_acc / len(real_window), imag_acc / len(imag_window)))
        return averaged

    def _estimate_rf_excess_db(self, shifted: list[complex], filtered: list[complex]) -> float:
        if not shifted or not filtered:
            return -120.0
        band_power = sum((sample.real * sample.real) + (sample.imag * sample.imag) for sample in filtered) / len(filtered)
        residual_power = sum(
            ((raw.real - filt.real) ** 2) + ((raw.imag - filt.imag) ** 2)
            for raw, filt in zip(shifted, filtered, strict=False)
        ) / max(1, len(filtered))
        band_power = max(band_power, 1e-12)
        residual_power = max(residual_power, 1e-12)
        return 10.0 * math.log10(band_power / residual_power)

    def _demodulate_audio(self, baseband: list[complex], channel: Channel, sample_rate_hz: int) -> array:
        state = self._get_channel_signal_state(channel.id)
        if len(baseband) < 8:
            return array('h')

        audio: list[float] = []
        previous = state.previous_baseband_sample
        if channel.modulation.value in {"NFM", "WFM"}:
            for sample in baseband:
                phase_delta = cmath.phase(sample * previous.conjugate())
                audio.append(max(-1.0, min(1.0, phase_delta / math.pi)))
                previous = sample
        elif channel.modulation.value == "AM":
            magnitudes = [abs(sample) for sample in baseband]
            average = sum(magnitudes) / len(magnitudes)
            peak = max(max(abs(magnitude - average) for magnitude in magnitudes), 1e-6)
            audio = [max(-1.0, min(1.0, (magnitude - average) / peak)) for magnitude in magnitudes]
            previous = baseband[-1]
        else:
            return array('h')
        state.previous_baseband_sample = previous

        if channel.deemphasis and len(audio) > 1:
            alpha = 0.15
            deemphasized = [audio[0]]
            for sample in audio[1:]:
                deemphasized.append(deemphasized[-1] + alpha * (sample - deemphasized[-1]))
            audio = deemphasized

        decimation = max(1, int(sample_rate_hz / max(channel.audio_rate_hz * 2, 1)))
        decimated = self._moving_average_real(audio, max(1, decimation))[::decimation]
        if not decimated:
            return array('h')
        audio_rate = sample_rate_hz / decimation
        resampled = self._resample_real(decimated, audio_rate, channel.audio_rate_hz)
        mean_value = sum(resampled) / len(resampled)
        centered = [sample - mean_value for sample in resampled]
        peak = max(max(abs(sample) for sample in centered), 1e-6)
        pcm = array('h')
        for sample in centered:
            pcm.append(int(max(-32767, min(32767, sample / peak * 27852))))
        return pcm

    def _moving_average_real(self, samples: list[float], window_size: int) -> list[float]:
        if not samples:
            return []
        window_size = max(1, min(window_size, len(samples)))
        averaged: list[float] = []
        acc = 0.0
        window = deque()
        for sample in samples:
            window.append(sample)
            acc += sample
            if len(window) > window_size:
                acc -= window.popleft()
            averaged.append(acc / len(window))
        return averaged

    def _resample_real(self, samples: list[float], input_rate_hz: float, output_rate_hz: int) -> list[float]:
        if not samples:
            return []
        target_count = max(1, int(round(len(samples) * output_rate_hz / input_rate_hz)))
        if len(samples) == 1 or target_count == 1:
            return [samples[0]] * target_count
        result: list[float] = []
        scale = (len(samples) - 1) / max(1, target_count - 1)
        for index in range(target_count):
            position = index * scale
            left_index = int(position)
            right_index = min(left_index + 1, len(samples) - 1)
            fraction = position - left_index
            value = samples[left_index] * (1.0 - fraction) + samples[right_index] * fraction
            result.append(value)
        return result

    def _pcm_dbfs(self, pcm: array) -> float:
        if len(pcm) == 0:
            return -120.0
        rms = math.sqrt(sum((sample / 32768.0) ** 2 for sample in pcm) / len(pcm))
        return 20.0 * math.log10(max(rms, 1e-12))

    async def _apply_channel_signal_update(self, channel_id: str, metrics: ChannelSignalMetrics) -> EventPayload | None:
        async with self.lock:
            channel = self.channels.get(channel_id)
            if channel is None or not channel.enabled:
                self.channel_signal_state.pop(channel_id, None)
                return None

            state = self._get_channel_signal_state(channel_id)
            self._append_rolling_audio(state, metrics.audio_pcm, channel.audio_rate_hz, channel.pre_roll_ms)
            should_be_active = metrics.carrier_detected or metrics.audio_level_dbfs >= channel.audio_activity_threshold_dbfs
            activity = self.activities.get(channel.current_activity_id) if channel.current_activity_id else None

            if should_be_active:
                state.active_ms += metrics.block_duration_ms
                state.inactive_ms = 0.0
            else:
                state.inactive_ms += metrics.block_duration_ms
                state.active_ms = 0.0

            if channel.status != "active" and should_be_active and state.active_ms >= channel.activity_attack_ms:
                now = datetime.now(UTC)
                activity = Activity(
                    channel_id=channel.id,
                    channel_label=channel.label,
                    frequency_hz=channel.frequency_hz,
                    start_timestamp=now,
                    peak_signal_db=metrics.rf_level_db,
                    peak_audio_dbfs=metrics.audio_level_dbfs,
                )
                self.activities[activity.id] = activity
                channel.status = "active"
                channel.last_active_at = now
                channel.current_activity_id = activity.id
                state.captured_audio = list(state.rolling_audio)
                if len(metrics.audio_pcm):
                    state.captured_audio.append(array('h', metrics.audio_pcm))
                if channel.stream_id and channel.stream_id in self.streams:
                    self.streams[channel.stream_id].state = "streaming"
                activity_events.labels(event_type="channel_active").inc()
                return EventPayload(
                    event_type="channel_active",
                    timestamp=now,
                    channel_id=channel.id,
                    activity_id=activity.id,
                    rf_level_db=metrics.rf_level_db,
                    audio_level_dbfs=metrics.audio_level_dbfs,
                    frequency_hz=channel.frequency_hz,
                )

            if channel.status == "active" and activity is not None:
                activity.peak_signal_db = max(activity.peak_signal_db, metrics.rf_level_db)
                activity.peak_audio_dbfs = max(activity.peak_audio_dbfs, metrics.audio_level_dbfs)
                if len(metrics.audio_pcm):
                    state.captured_audio.append(array('h', metrics.audio_pcm))
                if not should_be_active and state.inactive_ms >= channel.activity_release_ms:
                    now = datetime.now(UTC)
                    activity.end_timestamp = now
                    activity.duration_ms = max(1, int((now - activity.start_timestamp).total_seconds() * 1000))
                    activity.state = "completed"
                    activity.audio_available = bool(state.captured_audio)
                    if state.captured_audio:
                        expires_at = now + timedelta(seconds=self.settings.activity_audio_ttl_seconds)
                        wav_bytes = self._encode_wav_bytes(state.captured_audio, channel.audio_rate_hz)
                        self.activity_audio[activity.id] = ActivityAudio(
                            activity_id=activity.id,
                            base64_audio=base64.b64encode(wav_bytes).decode(),
                            expires_at=expires_at,
                        )
                    channel.status = "idle"
                    channel.current_activity_id = None
                    if channel.stream_id and channel.stream_id in self.streams:
                        self.streams[channel.stream_id].state = "buffered"
                    state.captured_audio = []
                    state.active_ms = 0.0
                    state.inactive_ms = 0.0
                    activity_events.labels(event_type="channel_idle").inc()
                    return EventPayload(
                        event_type="channel_idle",
                        timestamp=now,
                        channel_id=channel.id,
                        activity_id=activity.id,
                        rf_level_db=activity.peak_signal_db,
                        audio_level_dbfs=activity.peak_audio_dbfs,
                        frequency_hz=channel.frequency_hz,
                    )

            if channel.stream_id and channel.stream_id in self.streams and channel.status != "active":
                self.streams[channel.stream_id].state = "idle"
            return None

    def _append_rolling_audio(self, state: ChannelSignalState, audio_pcm: array, audio_rate_hz: int, pre_roll_ms: int) -> None:
        if len(audio_pcm) == 0:
            return
        state.rolling_audio.append(array('h', audio_pcm))
        state.rolling_audio_samples += len(audio_pcm)
        max_samples = int(audio_rate_hz * pre_roll_ms / 1000)
        while state.rolling_audio and state.rolling_audio_samples > max_samples:
            dropped = state.rolling_audio.popleft()
            state.rolling_audio_samples -= len(dropped)

    def _encode_wav_bytes(self, chunks: list[array], sample_rate_hz: int) -> bytes:
        pcm = array('h')
        for chunk in chunks:
            pcm.extend(chunk)
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate_hz)
            wav_file.writeframes(pcm.tobytes())
        return buffer.getvalue()


class MockSdrProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._sample_lock = threading.Lock()
        self._sample_sequence = 0
        self._latest_samples: bytes | None = None

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

    def push_samples(self, iq_bytes: bytes) -> None:
        with self._sample_lock:
            self._latest_samples = iq_bytes
            self._sample_sequence += 1

    def get_latest_samples(self) -> tuple[int, bytes] | None:
        with self._sample_lock:
            if self._latest_samples is None:
                return None
            return self._sample_sequence, self._latest_samples
