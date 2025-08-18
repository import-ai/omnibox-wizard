from logging import Logger
from typing import Optional

import shortuuid
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from omnibox_wizard.common.logger import get_logger
from omnibox_wizard.common.telemetry import get_telemetry_service


class TraceInfo:
    def __init__(self, request_id: Optional[str] = None, logger: Optional[Logger] = None,
                 payload: Optional[dict] = None, span=None):
        self.request_id = request_id or shortuuid.uuid()
        self.logger = logger or get_logger("app")
        self._payload: dict = payload or {}

        # OpenTelemetry integration
        self.telemetry_service = get_telemetry_service()
        self.span = span or trace.get_current_span()

        # Set request ID as span attribute if span is recording
        if self.span and self.span.is_recording():
            self.span.set_attribute("request.id", self.request_id)

    @property
    def payload(self) -> dict:
        return self._payload | {"request_id": self.request_id}

    def get_child(self, name: str = None, addition_payload: Optional[dict] = None) -> "TraceInfo":
        return self.__class__(
            self.request_id,
            self.logger if name is None else self.logger.getChild(name),
            self.payload | (addition_payload or {}),
            self.span  # Pass the same span to child
        )

    def bind(self, **kwargs) -> "TraceInfo":
        new_trace_info = self.__class__(
            self.request_id,
            self.logger,
            self.payload | kwargs,
            self.span
        )

        # Add new attributes to span if available
        if self.span and self.span.is_recording():
            # Filter out non-string/numeric values for span attributes
            span_attributes = {
                k: v for k, v in kwargs.items()
                if isinstance(v, (str, int, float, bool))
            }
            if span_attributes:
                self.span.set_attributes(span_attributes)

        return new_trace_info

    def debug(self, payload: dict):
        # Keep existing logging
        self.logger.debug(self.payload | payload, stacklevel=2)

        # Add span event if available
        if self.span and self.span.is_recording():
            self._add_span_event("debug", payload)

    def info(self, payload: dict):
        # Keep existing logging
        self.logger.info(self.payload | payload, stacklevel=2)

        # Add span event if available
        if self.span and self.span.is_recording():
            self._add_span_event("info", payload)

    def warning(self, payload: dict):
        # Keep existing logging
        self.logger.warning(self.payload | payload, stacklevel=2)

        # Add span event if available
        if self.span and self.span.is_recording():
            self._add_span_event("warning", payload)

    def error(self, payload: dict):
        # Keep existing logging
        self.logger.error(self.payload | payload, stacklevel=2)

        # Add span event and set error status
        if self.span and self.span.is_recording():
            self._add_span_event("error", payload)
            self.span.set_status(Status(StatusCode.ERROR, payload.get("message", "Error occurred")))

    def exception(self, payload: dict):
        # Keep existing logging
        self.logger.exception(self.payload | payload, stacklevel=2)

        # Add span event and set error status
        if self.span and self.span.is_recording():
            self._add_span_event("exception", payload)
            self.span.set_status(Status(StatusCode.ERROR, payload.get("message", "Exception occurred")))

    def _add_span_event(self, level: str, payload: dict):
        """Helper method to add events to span with filtered attributes"""
        if not self.span or not self.span.is_recording():
            return

        # Filter payload for span attributes (only basic types)
        span_attributes = {}
        for k, v in payload.items():
            if isinstance(v, (str, int, float, bool)):
                span_attributes[k] = v
            elif v is None:
                span_attributes[k] = "null"
            else:
                # For complex objects, convert to string representation
                span_attributes[k] = str(v)[:200]  # Limit length

        span_attributes["level"] = level
        self.span.add_event(f"log.{level}", span_attributes)

    def start_span(self, name: str, attributes: Optional[dict] = None):
        """Start a new span as a child of the current span"""
        if not self.telemetry_service.is_enabled():
            return None

        tracer = self.telemetry_service.get_tracer()
        if not tracer:
            return None

        span = tracer.start_span(name)

        # Set basic attributes
        if span and span.is_recording():
            span.set_attribute("request.id", self.request_id)
            if attributes:
                # Filter attributes for span
                span_attributes = {
                    k: v for k, v in attributes.items()
                    if isinstance(v, (str, int, float, bool))
                }
                if span_attributes:
                    span.set_attributes(span_attributes)

        return span

    def with_span(self, name: str, attributes: Optional[dict] = None):
        """Context manager to create a new span"""
        return self.telemetry_service.start_span(name, attributes)

    def __setitem__(self, key, value):
        self._payload = self._payload | {key: value}

        # Also add to span if recording
        if self.span and self.span.is_recording() and isinstance(value, (str, int, float, bool)):
            self.span.set_attribute(key, value)
