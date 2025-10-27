import io
import os

import httpx
from opentelemetry import trace
from pydub import AudioSegment

from omnibox_wizard.common.trace_info import TraceInfo

tracer = trace.get_tracer(__name__)


class ASRClient(httpx.AsyncClient):

    def __init__(self, model: str, *args, **kwargs):
        self.model: str = model
        super().__init__(*args, **kwargs)

    @tracer.start_as_current_span("ASRClient.transcribe")
    async def transcribe(self, file_path: str, mimetype: str, retry_cnt: int = 3, trace_info: TraceInfo = None) -> str:
        with open(file_path, "rb") as f:
            bytes_content: bytes = f.read()
        actual_retry_cnt = 0
        span = trace.get_current_span()

        for _ in range(retry_cnt):
            try:
                actual_retry_cnt += 1
                span.set_attributes({
                    "actual_retry_cnt": actual_retry_cnt
                })
                response: httpx.Response = await self.post(
                    "/audio/transcriptions",
                    files={"file": (file_path, io.BytesIO(bytes_content), mimetype)},
                    data={"model": self.model},
                    timeout=600,
                )
                assert response.is_success, response.text
                return response.json()["text"]
            except Exception as e:
                span.set_attributes({
                    "error": f"ASR transcription failed: {str(e)}"
                })
                continue

        span.set_attributes({
            "error": f"ASR transcription failed after {retry_cnt} retries"
        })
        raise RuntimeError(f"ASR transcription failed after {retry_cnt} retries")


class M4AConvertor:
    @classmethod
    def convert(cls, m4a_filepath: str) -> str:
        mp3_filepath: str = os.path.splitext(m4a_filepath)[0] + '.mp3'
        audio = AudioSegment.from_file(m4a_filepath, format="m4a")
        audio.export(mp3_filepath, format="mp3")
        return mp3_filepath
