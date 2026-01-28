import json
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx
from httpx import AsyncClient, AsyncHTTPTransport
from opentelemetry import trace
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.trace import Status, StatusCode

from common.exception import CommonException
from omnibox_wizard.worker.config import WorkerConfig
from wizard_common.worker.entity import Task

tracer = trace.get_tracer(__name__)


class CallbackUtil:
    def __init__(self, config: WorkerConfig):
        self.config = config
        self.payload_size_threshold = config.callback.payload_size_threshold * 1024**2

    @asynccontextmanager
    async def backend_client(self) -> AsyncGenerator[AsyncClient, None]:
        async with httpx.AsyncClient(
            base_url=self.config.backend.base_url,
            transport=AsyncHTTPTransport(retries=3),
            timeout=30,
        ) as client:
            HTTPXClientInstrumentor.instrument_client(client)
            yield client

    @tracer.start_as_current_span("CallbackUtil.send_callback")
    async def send_callback(self, task: Task):
        span = trace.get_current_span()
        payload = task.model_dump(
            exclude_none=True,
            mode="json",
            include={"id", "exception", "output", "status"},
        )

        try:
            # Check if payload exceeds threshold
            if self._should_upload_to_s3(payload):
                try:
                    await self._send_s3_callback(payload, task.id)
                except Exception as e:
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.set_attribute("error.message", str(e))
                    span.set_attribute("error.type", type(e).__name__)
                    # Fallback to regular callback
                    await self._send_regular_callback(payload)
            else:
                await self._send_regular_callback(payload)
        except Exception as e:
            async with self.backend_client() as client:
                resp = await client.post(
                    "/internal/api/v1/wizard/callback",
                    json={
                        "id": payload["id"],
                        "exception": {
                            "message": CommonException.parse_exception(e),
                            "task": {
                                "has_exception": bool(payload.get("exception")),
                                "has_output": bool(payload.get("output")),
                            },
                        },
                    },
                )
                resp.raise_for_status()

    @tracer.start_as_current_span("CallbackUtil._send_regular_callback")
    async def _send_regular_callback(self, payload: dict):
        async with self.backend_client() as client:
            http_response: httpx.Response = await client.post(
                "/internal/api/v1/wizard/callback", json=payload
            )
            if http_response.status_code == 413:
                raise RuntimeError("Callback content too large")
            http_response.raise_for_status()

    def _should_upload_to_s3(self, payload: dict) -> bool:
        """Check if payload should be uploaded to S3 based on size threshold"""
        serialized = json.dumps(payload, ensure_ascii=False)
        return len(serialized.encode("utf-8")) > self.payload_size_threshold

    @tracer.start_as_current_span("CallbackUtil._request_presigned_url")
    async def _request_presigned_url(self, task_id: str) -> str:
        """
        Request pre-signed upload URL from backend

        Args:
            task_id: Task ID

        Returns:
            Pre-signed upload URL
        """
        async with self.backend_client() as client:
            http_response: httpx.Response = await client.post(
                f"/internal/api/v1/wizard/tasks/{task_id}/upload"
            )
            http_response.raise_for_status()

            result = http_response.json()
            upload_url = result["url"]

            return upload_url

    @tracer.start_as_current_span("CallbackUtil._upload_payload_to_s3")
    async def _upload_payload_to_s3(self, payload: dict, upload_url: str) -> None:
        """
        Upload payload to S3 using pre-signed URL

        Args:
            payload: The payload to upload
            upload_url: Pre-signed upload URL from backend
        """
        # Serialize payload to JSON
        json_data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        json_bytes = json_data.encode("utf-8")

        # Upload to S3 using pre-signed URL
        async with httpx.AsyncClient() as client:
            http_response: httpx.Response = await client.put(
                upload_url,
                content=json_bytes,
                headers={
                    "Content-Type": "application/json",
                },
            )

            http_response.raise_for_status()

    @tracer.start_as_current_span("CallbackUtil._send_s3_callback")
    async def _send_s3_callback(self, payload: dict, task_id: str):
        """Upload payload to S3 and send callback notification"""
        # Step 1: Request pre-signed upload URL from backend
        upload_url = await self._request_presigned_url(task_id)

        # Step 2: Upload payload to S3 using pre-signed URL
        await self._upload_payload_to_s3(payload, upload_url)

        # Step 3: Send callback notification (backend will retrieve payload from S3)
        async with self.backend_client() as client:
            http_response: httpx.Response = await client.post(
                f"/internal/api/v1/wizard/tasks/{task_id}/callback"
            )

            if http_response.status_code == 413:
                raise RuntimeError("Callback content too large")
            http_response.raise_for_status()
