from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class Modulation(str, Enum):
    nfm = "NFM"
    am = "AM"
    wfm = "WFM"


class StreamTransport(str, Enum):
    websocket = "websocket"
    http_chunked = "http_chunked"


class StreamFormat(str, Enum):
    pcm16 = "pcm_s16le"
    wav = "wav"


class RadioCapabilityRange(BaseModel):
    min_hz: int
    max_hz: int


class GainControl(BaseModel):
    name: str
    min_db: float
    max_db: float
    step_db: float


class RadioCapabilities(BaseModel):
    device_name: str
    serial: str
    driver: str
    frequency_range: RadioCapabilityRange
    supported_sample_rates_hz: list[int]
    bandwidth_range_hz: RadioCapabilityRange
    bandwidth_options_hz: list[int]
    gain_controls: list[GainControl]
    agc_supported: bool
    antennas: list[str]
    dc_offset_supported: bool = False
    iq_balance_supported: bool = False
    supported_modulations: list[Modulation]
    recommended_runtime_limits: dict[str, int]


class RadioState(BaseModel):
    center_frequency_hz: int
    sample_rate_hz: int
    bandwidth_hz: int
    gain_mode: str
    gain_db: float
    ppm: float
    antenna: str
    bias_tee: bool = False
    ready: bool = False
    revision: int = 0
    last_error: str | None = None


class RadioStatePatch(BaseModel):
    sample_rate_hz: int | None = None
    bandwidth_hz: int | None = None
    gain_mode: str | None = None
    gain_db: float | None = None
    ppm: float | None = None
    antenna: str | None = None
    bias_tee: bool | None = None
    if_revision: int | None = None


class RadioRetuneRequest(BaseModel):
    center_frequency_hz: int
    force: bool = False


class StreamConfig(BaseModel):
    transport: StreamTransport = StreamTransport.websocket
    format: StreamFormat = StreamFormat.pcm16


class AudioFilterConfig(BaseModel):
    highpass_hz: int | None = None
    lowpass_hz: int | None = None


class ChannelBase(BaseModel):
    label: str | None = None
    frequency_hz: int
    modulation: Modulation
    bandwidth_hz: int
    audio_rate_hz: int = 16_000
    enabled: bool = True
    muted: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    priority: int = 100
    deemphasis: bool = False
    agc: bool = False
    audio_filters: AudioFilterConfig | None = None
    stream_config: StreamConfig = Field(default_factory=StreamConfig)
    squelch_threshold_db: float = -70.0
    squelch_hang_ms: int = 400
    audio_activity_threshold_dbfs: float = -35.0
    activity_attack_ms: int = 120
    activity_release_ms: int = 650
    minimum_active_ms: int = 500
    event_suppression_ms: int = 1000
    pre_roll_ms: int = 1000
    post_roll_ms: int = 1000

    @model_validator(mode="after")
    def validate_thresholds(self) -> "ChannelBase":
        if self.bandwidth_hz <= 0 or self.audio_rate_hz <= 0:
            raise ValueError("bandwidth_hz and audio_rate_hz must be positive")
        if self.pre_roll_ms < 0 or self.post_roll_ms < 0:
            raise ValueError("pre_roll_ms and post_roll_ms must be non-negative")
        return self


class ChannelCreate(ChannelBase):
    id: str | None = None


class ChannelPatch(BaseModel):
    label: str | None = None
    frequency_hz: int | None = None
    modulation: Modulation | None = None
    bandwidth_hz: int | None = None
    audio_rate_hz: int | None = None
    enabled: bool | None = None
    muted: bool | None = None
    metadata: dict[str, Any] | None = None
    tags: list[str] | None = None
    priority: int | None = None
    deemphasis: bool | None = None
    agc: bool | None = None
    audio_filters: AudioFilterConfig | None = None
    stream_config: StreamConfig | None = None
    squelch_threshold_db: float | None = None
    squelch_hang_ms: int | None = None
    audio_activity_threshold_dbfs: float | None = None
    activity_attack_ms: int | None = None
    activity_release_ms: int | None = None
    minimum_active_ms: int | None = None
    event_suppression_ms: int | None = None
    pre_roll_ms: int | None = None
    post_roll_ms: int | None = None
    if_revision: int | None = None


class Channel(ChannelBase):
    id: str = Field(default_factory=lambda: f"ch_{uuid4().hex[:10]}")
    revision: int = 0
    status: Literal["idle", "active", "disabled"] = "idle"
    stream_id: str | None = None
    last_active_at: datetime | None = None
    current_activity_id: str | None = None


class ChannelValidationRequest(ChannelBase):
    pass


class ScannerBase(BaseModel):
    name: str
    frequencies_hz: list[int]
    modulation: Modulation
    bandwidth_hz: int
    dwell_ms: int = 600
    hold_ms: int = 3000
    resume_delay_ms: int = 800
    priority_frequencies_hz: list[int] = Field(default_factory=list)
    enabled: bool = True
    mode: Literal["retune", "in_band"] = "retune"
    protect_fixed_channels: bool = True


class ScannerCreate(ScannerBase):
    id: str | None = None


class ScannerPatch(BaseModel):
    name: str | None = None
    frequencies_hz: list[int] | None = None
    modulation: Modulation | None = None
    bandwidth_hz: int | None = None
    dwell_ms: int | None = None
    hold_ms: int | None = None
    resume_delay_ms: int | None = None
    priority_frequencies_hz: list[int] | None = None
    enabled: bool | None = None
    mode: Literal["retune", "in_band"] | None = None
    protect_fixed_channels: bool | None = None
    if_revision: int | None = None


class Scanner(ScannerBase):
    id: str = Field(default_factory=lambda: f"sc_{uuid4().hex[:10]}")
    revision: int = 0
    running: bool = False
    last_hit_at: datetime | None = None
    last_frequency_hz: int | None = None


class Stream(BaseModel):
    id: str = Field(default_factory=lambda: f"st_{uuid4().hex[:10]}")
    channel_id: str
    transport: StreamTransport
    format: StreamFormat
    sample_rate_hz: int
    state: Literal["idle", "streaming", "buffered"] = "idle"
    url: str


class Activity(BaseModel):
    id: str = Field(default_factory=lambda: f"act_{uuid4().hex[:10]}")
    channel_id: str
    channel_label: str | None = None
    frequency_hz: int
    start_timestamp: datetime
    end_timestamp: datetime | None = None
    duration_ms: int | None = None
    peak_signal_db: float = -120.0
    peak_audio_dbfs: float = -120.0
    state: Literal["active", "completed"] = "active"
    audio_available: bool = False


class ActivityAudio(BaseModel):
    activity_id: str
    mime_type: str = "audio/wav"
    base64_audio: str
    expires_at: datetime


class EventPayload(BaseModel):
    event_type: Literal[
        "channel_active",
        "channel_idle",
        "scanner_hit",
        "radio_retuned",
        "error",
        "overrun",
    ]
    timestamp: datetime
    channel_id: str | None = None
    scanner_id: str | None = None
    activity_id: str | None = None
    message: str | None = None
    rf_level_db: float | None = None
    audio_level_dbfs: float | None = None
    frequency_hz: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    detail: str
