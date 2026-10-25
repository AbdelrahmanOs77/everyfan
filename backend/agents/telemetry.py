"""Optional, metadata-only tracing. No Azure initialization without a connection string."""

import json
import logging
import os
import threading
from contextlib import contextmanager
from contextvars import ContextVar

log = logging.getLogger(__name__)
_active = ContextVar("everyfan_telemetry", default=None)
_handles = ContextVar("everyfan_spans", default=())
_allowed = frozenset(("match_id moment_id persona lang model tokens charged_tokens usage_unknown "
                      "verdict reason_code attempts outcome entry_point approved fallback count "
                      "tool_name confidence error_type").split())


def attributes(values):
    return {f"everyfan.{key}": value[:256] if isinstance(value, str) else value
            for key, value in values.items()
            if key in _allowed and isinstance(value, (str, bool, int, float))}


class Span:
    def __init__(self, owner, span=None, values=None):
        self.owner, self.span, self.values = owner, span, values or {}
        self.tokens, self.charged_tokens, self.closed = 0, 0, False

    @property
    def trace_id(self):
        try:
            context = self.span.get_span_context() if self.span is not None else None
            return format(context.trace_id, "032x") if context and context.is_valid else None
        except Exception:
            return None

    def set(self, **values):
        if self.span is not None:
            try:
                self.span.set_attributes(attributes(values))
            except Exception:
                pass  # observability cannot interrupt a match

    def event(self, name, **values):
        if self.span is not None:
            try:
                self.span.add_event(name, attributes=attributes(values))
            except Exception:
                pass

    @contextmanager
    def activate(self):
        active = _active.set(self.owner)
        stack = _handles.get()
        if self.span is None:
            stack = ()
        elif not stack or stack[-1] is not self:
            stack = (*stack, self)
        handles = _handles.set(stack)
        try:
            if self.span is None:
                yield self
                return
            from opentelemetry.trace import use_span
            with use_span(self.span, end_on_exit=False, record_exception=False, set_status_on_exception=False):
                try:
                    yield self
                except BaseException as exc:
                    from opentelemetry.trace import Status, StatusCode
                    error_type = type(exc).__name__
                    self.set(error_type=error_type, outcome="cancelled" if error_type == "CancelledError" else "error")
                    try:
                        self.span.set_status(Status(StatusCode.ERROR, error_type))
                    except Exception:
                        pass
                    raise
        finally:
            _handles.reset(handles)
            _active.reset(active)

    def end(self):
        if self.span is not None and not self.closed:
            self.closed = True
            try:
                self.span.end()
            except Exception:
                pass


class Telemetry:
    def __init__(self, tracer=None):
        self.tracer = tracer

    def start(self, name, **values):
        inherited = _handles.get()[-1].values if _handles.get() else {}
        values = {**inherited, **values}
        if self.tracer is not None:
            try:
                return Span(self, self.tracer.start_span(name, attributes=attributes(values)), values)
            except Exception:
                pass
        return Span(self)

    @contextmanager
    def span(self, name, **values):
        span = self.start(name, **values)
        try:
            with span.activate():
                yield span
        finally:
            span.end()


_default = Telemetry()
_configured = False
_lock = threading.Lock()


def current():
    return _active.get() or _default


def record_usage(tokens, charged_tokens):
    # Context-local ancestry, never a delta from the shared daily budget.
    for handle in _handles.get():
        handle.tokens += tokens
        handle.charged_tokens += charged_tokens
        handle.set(tokens=handle.tokens, charged_tokens=handle.charged_tokens)


def event(name, **values):
    if _handles.get():
        _handles.get()[-1].event(name, **values)


def annotate(**values):
    if _handles.get():
        _handles.get()[-1].set(**values)


class TracedTools:
    """Trace only the five known evidence operations, without exporting arguments/results."""
    names = frozenset({"get_moment_evidence", "get_match_state", "get_recent_events",
                       "get_player_statistics", "compare_to_baseline"})

    def __init__(self, tools):
        self.tools = tools

    def __getattr__(self, name):
        if name not in self.names:
            raise AttributeError(name)

        async def call(*args, **kwargs):
            with current().span(f"tool.{name}", tool_name=name) as span:
                result = await getattr(self.tools, name)(*args, **kwargs)
                span.set(outcome="completed")
                return result
        return call


def _configure_exporter(connection):
    from azure.monitor.opentelemetry import configure_azure_monitor
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource

    # Trace-only defaults, preserving any explicit operator OTel configuration.
    os.environ.setdefault("OTEL_LOGS_EXPORTER", "none")
    os.environ.setdefault("OTEL_METRICS_EXPORTER", "none")
    configure_azure_monitor(connection_string=connection, disable_offline_storage=True,
                            enable_live_metrics=False, enable_performance_counters=False,
                            logger_name=__name__, resource=Resource.create({
                                "service.name": os.getenv("OTEL_SERVICE_NAME", "everyfan-owner-c")}),
                            instrumentation_options={name: {"enabled": False} for name in
                                ("azure_sdk", "django", "fastapi", "flask", "httpx", "httpx2",
                                 "psycopg2", "requests", "urllib", "urllib3")})
    try:
        from agent_framework.observability import enable_instrumentation
        enable_instrumentation(enable_sensitive_data=False, enable_message_events=False)
    except ImportError:
        log.info(json.dumps({"event": "agent_native_tracing_unavailable", "entry_point": "startup"}))
    return trace.get_tracer("everyfan.agents")


def configure():
    global _configured, _default
    connection = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()
    if not connection:
        return Telemetry()
    with _lock:
        if not _configured:
            _configured = True
            try:
                _default = Telemetry(_configure_exporter(connection))
            except Exception as exc:
                # Do not include the exception message: it can contain the connection string.
                log.warning(json.dumps({"event": "agent_tracing_disabled", "entry_point": "startup",
                                        "error_type": type(exc).__name__}))
    return _default
