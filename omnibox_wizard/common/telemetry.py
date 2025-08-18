import os
from contextlib import contextmanager
from enum import Enum
from typing import Optional

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentation
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentation
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased, AlwaysOff, AlwaysOn
from opentelemetry.semconv.resource import ResourceAttributes


class Environment(Enum):
    LOCAL = "local"
    TEST = "test"
    DEV = "dev"
    PUBLISH = "publish"


class TelemetryConfig:
    def __init__(self):
        self.env = os.getenv("ENV", "local")
        self.enabled = self._get_enabled()
        self.sampling_rate = self._get_sampling_rate()
        self.service_name = f"omnibox-wizard-{self.env}"
        self.otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")

    def _get_enabled(self) -> bool:
        if self.env == "local":
            return os.getenv("OTEL_TRACES_ENABLED", "false").lower() == "true"
        return os.getenv("OTEL_TRACES_ENABLED", "true").lower() == "true"

    def _get_sampling_rate(self) -> float:
        default_rates = {
            "local": 1.0,
            "test": 1.0,
            "dev": 0.1,
            "publish": 0.01
        }
        env_rate = os.getenv("OTEL_TRACES_SAMPLING_RATIO")
        if env_rate:
            return float(env_rate)
        return default_rates.get(self.env, 1.0)


class TelemetryService:
    def __init__(self):
        self.config = TelemetryConfig()
        self._tracer = None
        self._initialized = False

    def init_telemetry(self):
        """Initialize OpenTelemetry tracing"""
        if not self.config.enabled or self._initialized:
            return

        try:
            # Create resource
            resource = Resource.create({
                ResourceAttributes.SERVICE_NAME: self.config.service_name,
                ResourceAttributes.SERVICE_VERSION: "0.1.2",
                ResourceAttributes.DEPLOYMENT_ENVIRONMENT: self.config.env,
            })

            # Create tracer provider
            if self.config.sampling_rate <= 0:
                sampler = AlwaysOff()
            elif self.config.sampling_rate >= 1:
                sampler = AlwaysOn()
            else:
                sampler = TraceIdRatioBased(self.config.sampling_rate)

            tracer_provider = TracerProvider(
                resource=resource,
                sampler=sampler,
            )

            # Create OTLP exporter
            otlp_exporter = OTLPSpanExporter(
                endpoint=f"{self.config.otlp_endpoint}/v1/traces",
            )

            # Add span processor
            span_processor = BatchSpanProcessor(otlp_exporter)
            tracer_provider.add_span_processor(span_processor)

            # Set the global tracer provider
            trace.set_tracer_provider(tracer_provider)

            # Get tracer
            self._tracer = trace.get_tracer("omnibox-wizard")

            # Auto-instrument FastAPI and HTTPX
            FastAPIInstrumentation().instrument()
            HTTPXClientInstrumentation().instrument()

            self._initialized = True
            print(
                f"OpenTelemetry initialized: service={self.config.service_name}, endpoint={self.config.otlp_endpoint}")

        except Exception as e:
            print(f"Failed to initialize OpenTelemetry: {e}")

    def get_tracer(self):
        """Get the OpenTelemetry tracer"""
        return self._tracer

    def is_enabled(self) -> bool:
        """Check if telemetry is enabled"""
        return self.config.enabled and self._initialized

    @contextmanager
    def start_span(self, name: str, attributes: Optional[dict] = None):
        """Context manager to create and manage spans"""
        if not self.is_enabled() or not self._tracer:
            yield None
            return

        span = self._tracer.start_span(name)

        if attributes:
            span.set_attributes(attributes)

        try:
            yield span
        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            raise
        finally:
            span.end()


# Global telemetry service instance
telemetry_service = TelemetryService()


def init_telemetry():
    """Initialize the global telemetry service"""
    telemetry_service.init_telemetry()


def get_telemetry_service() -> TelemetryService:
    """Get the global telemetry service instance"""
    return telemetry_service


def get_tracer():
    """Get the OpenTelemetry tracer"""
    return telemetry_service.get_tracer()


__all__ = [
    "TelemetryConfig",
    "TelemetryService",
    "init_telemetry",
    "get_telemetry_service",
    "get_tracer",
    "telemetry_service"
]
