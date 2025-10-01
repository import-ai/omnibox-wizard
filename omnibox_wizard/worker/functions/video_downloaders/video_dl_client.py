from pathlib import Path
from typing import Dict, Any, Literal

import httpx
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor


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

    async def common_download(self, url: str, output_path: Path, media_type: Literal["video", "audio"]):
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            HTTPXClientInstrumentor.instrument_client(client)
            response = await client.get(f"/api/v1/download/{media_type}", params={"url": url})
            response.raise_for_status()

            # Get filename from Content-Disposition header or generate one
            content_disposition = response.headers.get('content-disposition', '')
            filename = content_disposition.split('filename=')[-1].strip('"')

            # Resolve output path with actual extension
            ext = Path(filename).suffix.lstrip('.')
            final_path = Path(str(output_path).replace('%(ext)s', ext))

            # Save file
            final_path.parent.mkdir(parents=True, exist_ok=True)
            with open(final_path, 'wb') as f:
                f.write(response.content)

            return str(final_path)

    async def download_video(self, url: str, output_path: Path) -> str:
        return await self.common_download(url, output_path, "video")

    async def download_audio(self, url: str, output_path: Path) -> str:
        return await self.common_download(url, output_path, "audio")
