from __future__ import annotations

import json
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

_TRACER: Any = None
_TELEMETRY_ACTIVE = False
_TELEMETRY_INIT_ATTEMPTED = False


def _normalize_attr(value: Any) -> Any:
    if isinstance(value, (bool, int, float, str)):
        return value
    try:
        dumped = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        dumped = str(value)
    return dumped[:2048]


def telemetry_enabled() -> bool:
    return bool(_TELEMETRY_ACTIVE and _TRACER is not None)


def configure_telemetry(
    *,
    service_name: str,
    enabled: bool,
    otlp_endpoint: str = "",
    sample_ratio: float = 1.0,
) -> bool:
    global _TRACER
    global _TELEMETRY_ACTIVE
    global _TELEMETRY_INIT_ATTEMPTED
    if not enabled:
        _TELEMETRY_ACTIVE = False
        return False
    if telemetry_enabled():
        return True
    if _TELEMETRY_INIT_ATTEMPTED and _TRACER is None:
        return False
    _TELEMETRY_INIT_ATTEMPTED = True
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
    except Exception:
        _TRACER = None
        _TELEMETRY_ACTIVE = False
        return False

    try:
        ratio = max(0.0, min(1.0, float(sample_ratio)))
    except Exception:
        ratio = 1.0
    try:
        provider = TracerProvider(
            resource=Resource.create(
                {
                    "service.name": (service_name or "").strip() or "pacienti-ai",
                }
            ),
            sampler=ParentBased(TraceIdRatioBased(ratio)),
        )
        endpoint = (otlp_endpoint or "").strip()
        if endpoint:
            exporter = OTLPSpanExporter(
                endpoint=endpoint,
                insecure=endpoint.startswith("http://"),
                timeout=10,
            )
        else:
            exporter = ConsoleSpanExporter()
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _TRACER = trace.get_tracer((service_name or "").strip() or "pacienti-ai")
        _TELEMETRY_ACTIVE = True
        return True
    except Exception:
        _TRACER = None
        _TELEMETRY_ACTIVE = False
        return False


@contextmanager
def traced_operation(name: str, attributes: Optional[Dict[str, Any]] = None) -> Iterator[Dict[str, Any]]:
    if not telemetry_enabled():
        start_perf = time.perf_counter()
        yield {"span": None, "start_perf": start_perf}
        return
    from opentelemetry.trace import Status, StatusCode

    start_perf = time.perf_counter()
    operation_name = (name or "").strip() or "operation"
    with _TRACER.start_as_current_span(operation_name) as span:  # type: ignore[union-attr]
        for key, value in (attributes or {}).items():
            k = (key or "").strip()
            if not k:
                continue
            try:
                span.set_attribute(k, _normalize_attr(value))
            except Exception:
                continue
        try:
            yield {"span": span, "start_perf": start_perf}
        except Exception as exc:
            try:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
            except Exception:
                pass
            raise


def elapsed_ms(start_perf: float) -> int:
    return max(0, int((time.perf_counter() - float(start_perf)) * 1000))
