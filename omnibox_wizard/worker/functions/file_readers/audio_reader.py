import io
import os

import httpcore
import httpx
from pydub import AudioSegment


class ASRClient(httpx.AsyncClient):

    def __init__(self, model: str, *args, **kwargs):
        self.model: str = model
        super().__init__(*args, **kwargs)

    async def transcribe(self, file_path: str, mimetype: str, retry_cnt: int = 3) -> str:
        with open(file_path, "rb") as f:
            bytes_content: bytes = f.read()

        for i in range(retry_cnt):
            try:
                response: httpx.Response = await self.post(
                    "/audio/transcriptions",
                    files={"file": (file_path, io.BytesIO(bytes_content), mimetype)},
                    data={"model": self.model}
                )
                assert response.is_success, response.text
                return response.json()["text"]
            except (TimeoutError, httpcore.ReadTimeout, httpx.ReadTimeout):
                continue
        raise RuntimeError("ASR transcription failed after retries")


def convert(m4a_filepath: str) -> str:
    if not m4a_filepath.lower().endswith('.m4a'):
        raise ValueError("Input file must be a .m4a file")
    mp3_filepath = os.path.splitext(m4a_filepath)[0] + '.mp3'
    audio = AudioSegment.from_file(m4a_filepath, format="m4a")
    audio.export(mp3_filepath, format="mp3")
    return mp3_filepath


class M4AConvertor:
    @classmethod
    def convert(cls, m4a_filepath: str) -> str:
        mp3_filepath: str = os.path.splitext(m4a_filepath)[0] + '.mp3'
        audio = AudioSegment.from_file(m4a_filepath, format="m4a")
        audio.export(mp3_filepath, format="mp3")
        return mp3_filepath
