import os
from pathlib import Path
from typing import Dict, Any, Optional

import httpx


class YtdlpClient:
    """HTTP client for yt-dlp service"""

    def __init__(self, base_url: str, timeout: float = 300.0):
        """
        Initialize yt-dlp client

        Args:
            base_url: Base URL of yt-dlp service (e.g., http://localhost:8002)
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.proxy = os.getenv("OB_PROXY", None)

    async def extract_info(self, url: str) -> Dict[str, Any]:
        """
        Extract video information without downloading

        Args:
            url: Video URL

        Returns:
            Dictionary with video metadata
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/extract-info",
                json={"url": url, "proxy": self.proxy}
            )
            response.raise_for_status()
            return response.json()

    async def download_video(
        self,
        url: str,
        output_path: Path,
        format: str = "best[height<=720]/bestvideo[height<=720]+bestaudio/best"
    ) -> str:
        """
        Download video

        Args:
            url: Video URL
            output_path: Path to save video file (including filename pattern)
            format: Video format specification

        Returns:
            Path to downloaded video file
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/download-video",
                json={"url": url, "format": format, "proxy": self.proxy}
            )
            response.raise_for_status()

            # Get filename from Content-Disposition header or generate one
            content_disposition = response.headers.get('content-disposition', '')
            if 'filename=' in content_disposition:
                filename = content_disposition.split('filename=')[-1].strip('"')
            else:
                # Extract extension from content-type or default to mp4
                content_type = response.headers.get('content-type', 'video/mp4')
                ext = content_type.split('/')[-1] if '/' in content_type else 'mp4'
                filename = f"video.{ext}"

            # Resolve output path with actual extension
            if '%(ext)s' in str(output_path):
                ext = Path(filename).suffix.lstrip('.')
                final_path = Path(str(output_path).replace('%(ext)s', ext))
            else:
                final_path = output_path.parent / filename

            # Save file
            final_path.parent.mkdir(parents=True, exist_ok=True)
            with open(final_path, 'wb') as f:
                f.write(response.content)

            return str(final_path)

    async def download_audio(
        self,
        url: str,
        output_path: Path,
        audio_format: str = "mp3",
        audio_quality: str = "0"
    ) -> str:
        """
        Download audio

        Args:
            url: Video URL
            output_path: Path to save audio file (including filename pattern)
            audio_format: Audio format (mp3, m4a, wav, etc.)
            audio_quality: Audio quality (0 is highest)

        Returns:
            Path to downloaded audio file
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/download-audio",
                json={
                    "url": url,
                    "audio_format": audio_format,
                    "audio_quality": audio_quality,
                    "proxy": self.proxy
                }
            )
            response.raise_for_status()

            # Get filename from Content-Disposition header or generate one
            content_disposition = response.headers.get('content-disposition', '')
            if 'filename=' in content_disposition:
                filename = content_disposition.split('filename=')[-1].strip('"')
            else:
                filename = f"audio.{audio_format}"

            # Resolve output path with actual extension
            if '%(ext)s' in str(output_path):
                ext = Path(filename).suffix.lstrip('.')
                final_path = Path(str(output_path).replace('%(ext)s', ext))
            else:
                final_path = output_path.parent / filename

            # Save file
            final_path.parent.mkdir(parents=True, exist_ok=True)
            with open(final_path, 'wb') as f:
                f.write(response.content)

            return str(final_path)
