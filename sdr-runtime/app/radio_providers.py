from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import POINTER, byref, c_char_p, c_int, c_uint32, c_uint8, c_void_p, create_string_buffer
from typing import Protocol

from .config import Settings
from .models import GainControl, Modulation, RadioCapabilities, RadioCapabilityRange, RadioState
from .state import MockSdrProvider

logger = logging.getLogger(__name__)


class RadioProvider(Protocol):
    def startup(self) -> tuple[RadioCapabilities, RadioState]: ...

    def shutdown(self) -> None: ...


class RtlSdrProvider:
    LIBRARY_CANDIDATES = ("librtlsdr.so.0", "librtlsdr.so")

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.library = self._load_library()
        self.device_handle = c_void_p()
        self.device_index: int | None = None
        self.device_serial: str | None = None
        self.stop_event = threading.Event()
        self.reader_thread: threading.Thread | None = None
        self.last_samples_read: int = 0

    def _load_library(self) -> ctypes.CDLL:
        errors: list[str] = []
        for candidate in self.LIBRARY_CANDIDATES:
            try:
                lib = ctypes.CDLL(candidate)
                self._configure_signatures(lib)
                return lib
            except OSError as exc:
                errors.append(f"{candidate}: {exc}")
        raise RuntimeError(f"Unable to load librtlsdr: {'; '.join(errors)}")

    def _configure_signatures(self, lib: ctypes.CDLL) -> None:
        lib.rtlsdr_get_device_count.restype = c_uint32
        lib.rtlsdr_get_device_usb_strings.argtypes = [c_uint32, c_char_p, c_char_p, c_char_p]
        lib.rtlsdr_get_device_usb_strings.restype = c_int
        lib.rtlsdr_get_index_by_serial.argtypes = [c_char_p]
        lib.rtlsdr_get_index_by_serial.restype = c_int
        lib.rtlsdr_open.argtypes = [POINTER(c_void_p), c_uint32]
        lib.rtlsdr_open.restype = c_int
        lib.rtlsdr_close.argtypes = [c_void_p]
        lib.rtlsdr_close.restype = c_int
        lib.rtlsdr_set_center_freq.argtypes = [c_void_p, c_uint32]
        lib.rtlsdr_set_center_freq.restype = c_int
        lib.rtlsdr_set_sample_rate.argtypes = [c_void_p, c_uint32]
        lib.rtlsdr_set_sample_rate.restype = c_int
        lib.rtlsdr_set_freq_correction.argtypes = [c_void_p, c_int]
        lib.rtlsdr_set_freq_correction.restype = c_int
        lib.rtlsdr_set_tuner_gain_mode.argtypes = [c_void_p, c_int]
        lib.rtlsdr_set_tuner_gain_mode.restype = c_int
        lib.rtlsdr_set_tuner_gain.argtypes = [c_void_p, c_int]
        lib.rtlsdr_set_tuner_gain.restype = c_int
        lib.rtlsdr_get_tuner_gains.argtypes = [c_void_p, POINTER(c_int)]
        lib.rtlsdr_get_tuner_gains.restype = c_int
        if hasattr(lib, "rtlsdr_set_bias_tee"):
            lib.rtlsdr_set_bias_tee.argtypes = [c_void_p, c_int]
            lib.rtlsdr_set_bias_tee.restype = c_int
        lib.rtlsdr_reset_buffer.argtypes = [c_void_p]
        lib.rtlsdr_reset_buffer.restype = c_int
        lib.rtlsdr_read_sync.argtypes = [c_void_p, POINTER(c_uint8), c_int, POINTER(c_int)]
        lib.rtlsdr_read_sync.restype = c_int

    def startup(self) -> tuple[RadioCapabilities, RadioState]:
        self.device_index, manufacturer, product, serial = self._select_device()
        self._open_device(self.device_index)
        self.device_serial = serial
        self._configure_device()
        self._activate_streaming()
        capabilities = self._build_capabilities(product or "RTL-SDR", serial)
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
        return capabilities, state

    def shutdown(self) -> None:
        self.stop_event.set()
        if self.reader_thread and self.reader_thread.is_alive():
            self.reader_thread.join(timeout=1.0)
        if self.device_handle:
            try:
                self.library.rtlsdr_close(self.device_handle)
            except Exception as exc:  # pragma: no cover - best effort cleanup
                logger.warning("Failed to close rtl-sdr device cleanly: %s", exc)
            finally:
                self.device_handle = c_void_p()

    def _select_device(self) -> tuple[int, str, str, str]:
        count = int(self.library.rtlsdr_get_device_count())
        if count <= 0:
            raise RuntimeError("No RTL-SDR devices detected")
        if self.settings.sdr_serial:
            index = int(self.library.rtlsdr_get_index_by_serial(self.settings.sdr_serial.encode()))
            if index < 0:
                raise RuntimeError(f"RTL-SDR with serial {self.settings.sdr_serial} not found")
        elif self.settings.sdr_index is not None:
            index = self.settings.sdr_index
        else:
            index = 0
        if index < 0 or index >= count:
            raise RuntimeError(f"RTL-SDR index {index} out of range; detected {count} devices")
        manufacturer, product, serial = self._device_usb_strings(index)
        return index, manufacturer, product, serial

    def _device_usb_strings(self, index: int) -> tuple[str, str, str]:
        manufacturer = create_string_buffer(256)
        product = create_string_buffer(256)
        serial = create_string_buffer(256)
        rc = self.library.rtlsdr_get_device_usb_strings(index, manufacturer, product, serial)
        if rc != 0:
            raise RuntimeError(f"Unable to read RTL-SDR USB strings for index {index}: rc={rc}")
        return manufacturer.value.decode(errors="ignore"), product.value.decode(errors="ignore"), serial.value.decode(errors="ignore")

    def _open_device(self, index: int) -> None:
        rc = self.library.rtlsdr_open(byref(self.device_handle), index)
        if rc != 0:
            raise RuntimeError(f"Unable to open RTL-SDR device index {index}: rc={rc}")

    def _configure_device(self) -> None:
        self._require_supported_antenna()
        self._set_center_frequency(self.settings.initial_center_frequency_hz)
        self._set_sample_rate(self.settings.initial_sample_rate_hz)
        self._set_freq_correction(self.settings.initial_ppm)
        self._set_gain(self.settings.initial_gain_mode, self.settings.initial_gain_db)
        self._set_bias_tee(self.settings.initial_bias_tee)

    def _require_supported_antenna(self) -> None:
        if self.settings.initial_antenna != "RX":
            if self.settings.strict_capability_check:
                raise RuntimeError(f"RTL-SDR only exposes antenna 'RX'; got {self.settings.initial_antenna}")
            logger.warning("Ignoring unsupported RTL-SDR antenna %s; using RX", self.settings.initial_antenna)

    def _set_center_frequency(self, frequency_hz: int) -> None:
        rc = self.library.rtlsdr_set_center_freq(self.device_handle, c_uint32(frequency_hz))
        if rc != 0:
            raise RuntimeError(f"Unable to set RTL-SDR center frequency to {frequency_hz}: rc={rc}")

    def _set_sample_rate(self, sample_rate_hz: int) -> None:
        rc = self.library.rtlsdr_set_sample_rate(self.device_handle, c_uint32(sample_rate_hz))
        if rc != 0:
            raise RuntimeError(f"Unable to set RTL-SDR sample rate to {sample_rate_hz}: rc={rc}")

    def _set_freq_correction(self, ppm: float) -> None:
        rc = self.library.rtlsdr_set_freq_correction(self.device_handle, int(ppm))
        if rc != 0:
            raise RuntimeError(f"Unable to set RTL-SDR PPM correction to {ppm}: rc={rc}")

    def _set_gain(self, gain_mode: str, gain_db: float) -> None:
        auto_gain = gain_mode.lower() in {"auto", "agc"}
        rc = self.library.rtlsdr_set_tuner_gain_mode(self.device_handle, 0 if auto_gain else 1)
        if rc != 0:
            raise RuntimeError(f"Unable to set RTL-SDR gain mode {gain_mode}: rc={rc}")
        if not auto_gain:
            gain_tenths = int(round(gain_db * 10))
            rc = self.library.rtlsdr_set_tuner_gain(self.device_handle, gain_tenths)
            if rc != 0:
                raise RuntimeError(f"Unable to set RTL-SDR gain {gain_db} dB: rc={rc}")

    def _set_bias_tee(self, enabled: bool) -> None:
        if not hasattr(self.library, "rtlsdr_set_bias_tee"):
            if enabled and self.settings.strict_capability_check:
                raise RuntimeError("Bias tee requested but this librtlsdr build does not support rtlsdr_set_bias_tee")
            return
        rc = self.library.rtlsdr_set_bias_tee(self.device_handle, 1 if enabled else 0)
        if rc != 0:
            raise RuntimeError(f"Unable to set RTL-SDR bias tee to {enabled}: rc={rc}")

    def _activate_streaming(self) -> None:
        rc = self.library.rtlsdr_reset_buffer(self.device_handle)
        if rc != 0:
            raise RuntimeError(f"Unable to reset RTL-SDR buffer before streaming: rc={rc}")
        self._probe_read()
        self.reader_thread = threading.Thread(target=self._stream_loop, name="rtl-sdr-reader", daemon=True)
        self.reader_thread.start()

    def _probe_read(self) -> None:
        buffer_length = 16 * 1024
        buffer = (c_uint8 * buffer_length)()
        bytes_read = c_int()
        rc = self.library.rtlsdr_read_sync(self.device_handle, buffer, buffer_length, byref(bytes_read))
        if rc != 0 or bytes_read.value <= 0:
            raise RuntimeError(f"RTL-SDR opened but sample read failed: rc={rc}, bytes_read={bytes_read.value}")
        self.last_samples_read = bytes_read.value

    def _stream_loop(self) -> None:
        buffer_length = 16 * 1024
        while not self.stop_event.is_set():
            buffer = (c_uint8 * buffer_length)()
            bytes_read = c_int()
            rc = self.library.rtlsdr_read_sync(self.device_handle, buffer, buffer_length, byref(bytes_read))
            if self.stop_event.is_set():
                return
            if rc != 0:
                logger.error("RTL-SDR streaming read failed: rc=%s", rc)
                return
            self.last_samples_read = bytes_read.value

    def _gain_controls(self) -> list[GainControl]:
        count = int(self.library.rtlsdr_get_tuner_gains(self.device_handle, None))
        if count <= 0:
            return [GainControl(name="TUNER", min_db=0.0, max_db=49.6, step_db=0.1)]
        gains = (c_int * count)()
        rc = int(self.library.rtlsdr_get_tuner_gains(self.device_handle, gains))
        if rc <= 0:
            return [GainControl(name="TUNER", min_db=0.0, max_db=49.6, step_db=0.1)]
        gain_values = [g / 10.0 for g in gains[:rc]]
        min_gain = min(gain_values)
        max_gain = max(gain_values)
        step = round(gain_values[1] - gain_values[0], 1) if len(gain_values) > 1 else 0.1
        return [GainControl(name="TUNER", min_db=min_gain, max_db=max_gain, step_db=step)]

    def _build_capabilities(self, product_name: str, serial: str) -> RadioCapabilities:
        return RadioCapabilities(
            device_name=product_name or "RTL-SDR",
            serial=serial or self.settings.sdr_serial or "UNKNOWN",
            driver="rtl-sdr",
            frequency_range=RadioCapabilityRange(min_hz=24_000_000, max_hz=1_766_000_000),
            supported_sample_rates_hz=[1_024_000, 1_800_000, 2_048_000, 2_400_000],
            bandwidth_range_hz=RadioCapabilityRange(min_hz=200_000, max_hz=3_200_000),
            bandwidth_options_hz=[200_000, 300_000, 600_000, 1_536_000, 2_048_000, 2_400_000],
            gain_controls=self._gain_controls(),
            agc_supported=True,
            antennas=["RX"],
            dc_offset_supported=False,
            iq_balance_supported=False,
            supported_modulations=[Modulation.nfm, Modulation.am, Modulation.wfm],
            recommended_runtime_limits={
                "max_channels": self.settings.max_channels,
                "max_scanners": self.settings.max_scanners,
                "max_streams": self.settings.max_streams,
            },
        )


class ManagedMockSdrProvider(MockSdrProvider):
    def shutdown(self) -> None:
        return None


def create_radio_provider(settings: Settings) -> RadioProvider:
    driver = settings.sdr_driver.lower().strip()
    if driver in {"rtl-sdr", "rtlsdr", "rtl_sdr"}:
        return RtlSdrProvider(settings)
    if driver in {"mock", "mock-soapysdr", "mock_soapysdr"}:
        return ManagedMockSdrProvider(settings)
    raise RuntimeError(f"Unsupported SDR_DRIVER {settings.sdr_driver!r}; expected rtl-sdr or mock-soapysdr")
