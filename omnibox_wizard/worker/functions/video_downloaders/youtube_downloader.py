import asyncio
import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs

from opentelemetry import trace

from .base_downloader import VideoInfo
from .bilibili_downloader import BilibiliDownloader

tracer = trace.get_tracer('YouTubeDownloader')


class YouTubeDownloader(BilibiliDownloader):
    """YouTube downloader, using yt-dlp service"""

    def __init__(self, video_dl_base_url: Optional[str] = None):
        """
        Initialize YouTube downloader

        Args:
            video_dl_base_url: Base URL for yt-dlp service. If None, falls back to local yt-dlp
        """
        super().__init__(video_dl_base_url)

    @classmethod
    def cmd_wrapper(cls, cmd: list[str]) -> list[str]:
        if proxy := os.getenv("OB_PROXY", None):
            return cmd[:1] + ["--proxy", proxy] + cmd[1:]
        return cmd

    @classmethod
    @tracer.start_as_current_span("_extract_video_id")
    def extract_video_id(cls, url: str) -> str:
        parsed_url = urlparse(url)
        qs = parse_qs(parsed_url.query)
        if parsed_url.netloc == 'www.youtube.com':
            return qs["v"][0]
        if parsed_url.netloc == 'youtu.be':
            return parsed_url.path.lstrip('/')
        return str(hash(url))

    @tracer.start_as_current_span("get_video_info")
    async def get_video_info(self, url: str, video_id: str) -> VideoInfo:
        data, real_url = await asyncio.gather(self._get_video_info_base(url), self.get_real_url(url))

        return VideoInfo(
            title=data.get("title", "Unknown Title"),
            duration=float(data.get("duration", 0)),
            video_id=data.get("id", ""),
            platform="youtube",
            url=url,
            description=data.get("description", ""),
            uploader=data.get("uploader", ""),
            upload_date=data.get("upload_date", ""),
            thumbnail_url=data.get("thumbnail", ""),
            real_url=real_url,
        )

    @tracer.start_as_current_span("_download_video")
    async def _download_video(self, url: str, video_id: str, output_dir: Path) -> str:
        """Download video"""
        output_path = output_dir / f"{video_id}_video.%(ext)s"

        if self.video_dl_client:
            # Use yt-dlp service with YouTube-specific format
            video_path = await self.video_dl_client.download_video(
                url=url,
                output_path=output_path,
                format="best[height<=720]/bestvideo[height<=720]+bestaudio/best"
            )
            return video_path
        else:
            # Fallback to local yt-dlp
            # Use more robust format selection, including fallback options
            cmd = [
                "yt-dlp",
                "-f", "best[height<=720]/bestvideo[height<=720]+bestaudio/best",
                "--no-playlist",  # Don't download playlist
                "--retries", "3",  # Retry 3 times
                "--fragment-retries", "3",  # Retry 3 times for fragments
                "-o", str(output_path),
                url
            ]

            return await self._execute_video_download(cmd, video_id, output_dir)
