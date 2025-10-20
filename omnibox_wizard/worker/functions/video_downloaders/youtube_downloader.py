import asyncio
import os
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from opentelemetry import trace

from .base_downloader import VideoInfo
from .bilibili_downloader import BilibiliDownloader, YtDlpDownloadResult

tracer = trace.get_tracer('YouTubeDownloader')


class YouTubeDownloader(BilibiliDownloader):
    """YouTube downloader, using yt-dlp service"""

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
    async def _download_video(self, url: str, video_id: str, output_dir: Path, *args, **kargs) -> YtDlpDownloadResult:
        """Download video"""
        output_path = output_dir / f"{video_id}_video.%(ext)s"
        download_result = await self.video_dl_client.download_video(url=url, output_path=output_path)
        return download_result
