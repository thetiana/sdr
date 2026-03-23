from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, generate_latest

registry = CollectorRegistry()
active_channels = Gauge("sdr_active_channels", "Active channels", registry=registry)
active_scanners = Gauge("sdr_active_scanners", "Active scanners", registry=registry)
active_streams = Gauge("sdr_active_streams", "Active streams", registry=registry)
activity_events = Counter("sdr_activity_events_total", "Activity events", ["event_type"], registry=registry)
overruns = Counter("sdr_overruns_total", "Overrun events", registry=registry)


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(registry), CONTENT_TYPE_LATEST
