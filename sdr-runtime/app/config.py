from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    app_name: str = "sdr-runtime"
    app_version: str = "0.1.0"
    api_bind: str = Field(default="0.0.0.0", alias="API_BIND")
    api_port: int = Field(default=8081, alias="API_PORT")
    auth_token: str | None = Field(default=None, alias="AUTH_TOKEN")
    cors_origins: str = Field(default="*", alias="CORS_ORIGINS")
    metrics_enabled: bool = Field(default=True, alias="METRICS_ENABLED")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO", alias="LOG_LEVEL")

    sdr_serial: str | None = Field(default=None, alias="SDR_SERIAL")
    sdr_index: int | None = Field(default=None, alias="SDR_INDEX")
    sdr_label: str | None = Field(default=None, alias="SDR_LABEL")
    sdr_driver: str = Field(default="mock-soapysdr", alias="SDR_DRIVER")
    initial_center_frequency_hz: int = Field(default=162_400_000, alias="INITIAL_CENTER_FREQUENCY_HZ")
    initial_sample_rate_hz: int = Field(default=2_400_000, alias="INITIAL_SAMPLE_RATE_HZ")
    initial_bandwidth_hz: int = Field(default=2_000_000, alias="INITIAL_BANDWIDTH_HZ")
    initial_gain_mode: str = Field(default="manual", alias="INITIAL_GAIN_MODE")
    initial_gain_db: float = Field(default=25.0, alias="INITIAL_GAIN_DB")
    initial_ppm: float = Field(default=0.0, alias="INITIAL_PPM")
    initial_antenna: str = Field(default="RX", alias="INITIAL_ANTENNA")
    initial_bias_tee: bool = Field(default=False, alias="INITIAL_BIAS_TEE")
    strict_capability_check: bool = Field(default=True, alias="STRICT_CAPABILITY_CHECK")
    retune_policy: Literal["deny", "allow"] = Field(default="deny", alias="RETUNE_POLICY")

    max_channels: int = Field(default=32, alias="MAX_CHANNELS")
    max_scanners: int = Field(default=8, alias="MAX_SCANNERS")
    max_streams: int = Field(default=32, alias="MAX_STREAMS")
    event_history_limit: int = Field(default=200, alias="EVENT_HISTORY_LIMIT")
    pre_roll_ms_default: int = Field(default=1000, alias="PRE_ROLL_MS_DEFAULT")
    post_roll_ms_default: int = Field(default=1000, alias="POST_ROLL_MS_DEFAULT")
    activity_audio_ttl_seconds: int = Field(default=900, alias="ACTIVITY_AUDIO_TTL_SECONDS")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
