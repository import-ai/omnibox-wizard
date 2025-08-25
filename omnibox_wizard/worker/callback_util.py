import asyncio
import base64
import json
from typing import Callable

import httpx
from opentelemetry import propagate, trace
from opentelemetry.trace import Status, StatusCode

from omnibox_wizard.common.exception import CommonException
from omnibox_wizard.common.trace_info import TraceInfo
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.entity import Task

tracer = trace.get_tracer(__name__)


class CallbackUtil:
    def __init__(self, config: WorkerConfig):
        self.config = config
        self.chunk_size = config.callback.chunk_size
        self.use_chunked_callback = config.callback.use_chunked

    @classmethod
    def inject_trace(cls, headers: dict | None) -> dict:
        headers = headers or {}
        propagate.inject(headers)
        return headers

    @tracer.start_as_current_span("CallbackUtil.send_callback")
    async def send_callback(self, task: Task, trace_info: TraceInfo):
        span = trace.get_current_span()
        payload = task.model_dump(
            exclude_none=True, mode="json",
            include={"id", "exception", "output"},
        )

        if self.use_chunked_callback and self._should_use_chunks(payload):
            try:
                await self._send_chunked_callback(payload, task.id, trace_info)
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.set_attribute("error.message", str(e))
                span.set_attribute("error.type", type(e).__name__)
                trace_info.error({
                    "message": "Chunked callback failed, sending regular callback with exception",
                    "error": CommonException.parse_exception(e),
                    "task_id": task.id
                })
                # Send regular callback with exception details
                await self._send_chunked_callback_failure(payload, task.id, trace_info, e)
        else:
            await self._send_regular_callback(payload, task.id, trace_info)

    async def _send_regular_callback(self, payload: dict, task_id: str, trace_info: TraceInfo):
        async with httpx.AsyncClient(base_url=self.config.backend.base_url) as client:
            http_response: httpx.Response = await client.post(
                f"/internal/api/v1/wizard/callback",
                json=payload,
                headers=self.inject_trace({"X-Request-Id": task_id}),
            )
            logging_func: Callable[[dict], None] = trace_info.debug if http_response.is_success else trace_info.error
            logging_func({"status_code": http_response.status_code, "response": http_response.json()})

        if not http_response.is_success:
            if http_response.status_code == 413:
                message = "Callback content too large"
            else:
                message = "Unknown error"
            async with httpx.AsyncClient(base_url=self.config.backend.base_url) as client:
                await client.post(
                    f"/internal/api/v1/wizard/callback",
                    json={"id": payload["id"], "exception": {
                        "message": message,
                        "task": {
                            "has_exception": bool(payload.get("exception")),
                            "has_output": bool(payload.get("output")),
                        },
                        "http_response": http_response.json()
                    }},
                    headers=self.inject_trace({"X-Request-Id": task_id}),
                )

    def _should_use_chunks(self, payload: dict) -> bool:
        serialized = json.dumps(payload, ensure_ascii=False)
        return len(serialized.encode('utf-8')) > self.chunk_size

    def _chunk_payload(self, payload: dict) -> list[str]:
        serialized = json.dumps(payload, ensure_ascii=False)
        data_bytes = serialized.encode('utf-8')

        chunks = []
        # Chunk the raw bytes first, then encode each chunk
        for i in range(0, len(data_bytes), self.chunk_size):
            chunk_bytes = data_bytes[i:i + self.chunk_size]
            encoded_chunk = base64.b64encode(chunk_bytes).decode('ascii')
            chunks.append(encoded_chunk)

        return chunks

    async def _send_chunked_callback(self, payload: dict, task_id: str, trace_info: TraceInfo):
        span = trace.get_current_span()
        chunks = self._chunk_payload(payload)
        trace_info.info({"message": f"Sending callback in {len(chunks)} chunks", "task_id": task_id})
        span.set_attributes({
            "callback.chunked": True,
            "callback.total_chunks": len(chunks),
        })

        for i, chunk_data in enumerate(chunks):
            is_final_chunk = i == len(chunks) - 1
            chunk_payload = {
                "id": task_id,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "data": chunk_data,
                "is_final_chunk": is_final_chunk
            }

            await self._send_chunk_with_retry(chunk_payload, trace_info, retry_count=3)

    async def _send_chunk_with_retry(self, chunk_payload: dict, trace_info: TraceInfo, retry_count: int = 3):
        for attempt in range(retry_count):
            try:
                async with httpx.AsyncClient(base_url=self.config.backend.base_url) as client:
                    http_response: httpx.Response = await client.post(
                        f"/internal/api/v1/wizard/callback/chunk",
                        json=chunk_payload,
                        headers=self.inject_trace({"X-Request-Id": chunk_payload["id"]}),
                    )

                    if http_response.is_success:
                        trace_info.debug({
                            "message": f"Chunk {chunk_payload['chunk_index'] + 1}/{chunk_payload['total_chunks']} sent successfully",
                            "status_code": http_response.status_code,
                            "response": http_response.json()
                        })
                        return
                    else:
                        trace_info.error({
                            "message": f"Chunk {chunk_payload['chunk_index'] + 1}/{chunk_payload['total_chunks']} failed",
                            "status_code": http_response.status_code,
                            "response": http_response.json(),
                            "attempt": attempt + 1
                        })

            except Exception as e:
                trace_info.error({
                    "message": f"Error sending chunk {chunk_payload['chunk_index'] + 1}/{chunk_payload['total_chunks']}",
                    "error": CommonException.parse_exception(e),
                    "attempt": attempt + 1
                })

            if attempt < retry_count - 1:
                await asyncio.sleep(1)

        raise Exception(
            f"Failed to send chunk {chunk_payload['chunk_index'] + 1}/{chunk_payload['total_chunks']} after {retry_count} attempts")

    async def _send_chunked_callback_failure(self, original_payload: dict, task_id: str, trace_info: TraceInfo,
                                             failure_exception: Exception):
        """Send a regular callback with exception details when chunked callback fails"""
        error_payload = {
            "id": task_id,
            "exception": {
                "message": "Chunked callback failed",
                "chunked_callback_error": CommonException.parse_exception(failure_exception),
                "task": {
                    "has_exception": bool(original_payload.get("exception")),
                    "has_output": bool(original_payload.get("output")),
                }
            }
        }

        async with httpx.AsyncClient(base_url=self.config.backend.base_url) as client:
            http_response: httpx.Response = await client.post(
                f"/internal/api/v1/wizard/callback",
                json=error_payload,
                headers=self.inject_trace({"X-Request-Id": task_id})
            )
            logging_func: Callable[[dict], None] = trace_info.debug if http_response.is_success else trace_info.error
            logging_func({
                "message": "Sent chunked callback failure notification",
                "status_code": http_response.status_code,
                "response": http_response.json()
            })
