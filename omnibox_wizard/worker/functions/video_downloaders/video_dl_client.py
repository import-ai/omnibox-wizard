from pathlib import Path
from typing import Dict, Any, Literal
import base64
import json
import httpx
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from pydantic import BaseModel, Field

class YtDlpDownloadResult(BaseModel):
    file_path: str = ""
    chapters: list[dict] = Field(default_factory=list)
    subtitles: dict = Field(default_factory=dict)  # format:{lang: subtitle_text}

class YtDlpClient:

    def __init__(self, base_url: str, timeout: float = 300.0):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout

    async def extract_info(self, url: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            HTTPXClientInstrumentor.instrument_client(client)
            response = await client.get("/api/v1/info", params={"url": url})
            response.raise_for_status()
            return response.json()

    async def common_download(self, url: str, output_path: Path, media_type: Literal["video", "audio", "subtitles"], cookies: str | None = None):
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            HTTPXClientInstrumentor.instrument_client(client)
            if media_type == "audio":
                response = await client.get(f"/api/v1/download/{media_type}", params={"url": url})
            else:
                response = await client.post(
                    f"/api/v1/download/{media_type}",
                    json={"url": url, "cookies": cookies})
            
            response.raise_for_status()

            # Get filename from Content-Disposition header or generate one
            content_disposition = response.headers.get('content-disposition', '')
            filename = content_disposition.split('filename=')[-1].strip('"')
            final_path = ""
            # Resolve output path with actual extension
            if response.content:
                ext = Path(filename).suffix.lstrip('.')
                final_path = Path(str(output_path).replace('%(ext)s', ext))
                # Save file
                final_path.parent.mkdir(parents=True, exist_ok=True)
                with open(final_path, 'wb') as f:
                    f.write(response.content)

            subtitles = {}
            chapters = []

            # Get subtitles
            subtitles_b64 = response.headers.get("Video-Subtitles")
            if subtitles_b64:
                subtitles_json = base64.b64decode(subtitles_b64).decode('utf-8')
                subtitles = json.loads(subtitles_json)

            # Get chapters
            chapters_b64 = response.headers.get("Video-Chapters")
            if chapters_b64:
                chapters_json = base64.b64decode(chapters_b64).decode('utf-8')
                chapters = json.loads(chapters_json)

            return YtDlpDownloadResult(
                    file_path = str(final_path),
                    subtitles = subtitles,
                    chapters = chapters
                )

    async def download_video(self, url: str, output_path: Path, cookies: str | None = None) -> YtDlpDownloadResult:
        return await self.common_download(url, output_path, "video", cookies)  

    async def download_audio(self, url: str, output_path: Path) -> YtDlpDownloadResult:
        return await self.common_download(url, output_path, "audio")

    async def download_subtitles(self, url: str, output_path: Path, cookies: str | None = None) -> YtDlpDownloadResult:
        return await self.common_download(url, output_path, "subtitles", cookies)  