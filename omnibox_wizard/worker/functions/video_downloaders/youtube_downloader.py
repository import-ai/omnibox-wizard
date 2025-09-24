import json
import subprocess
from pathlib import Path

from opentelemetry import trace

from .base_downloader import VideoInfo
from .bilibili_downloader import BilibiliDownloader

tracer = trace.get_tracer('YouTubeDownloader')


class YouTubeDownloader(BilibiliDownloader):
    """YouTube downloader, using yt-dlp"""

    @tracer.start_as_current_span("get_video_info")
    def get_video_info(self, url: str) -> VideoInfo:
        """Get YouTube video information"""
        cmd = [
            "yt-dlp",
            "--dump-json",
            "--no-download",
            url
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        # yt-dlp may return multiple JSON lines, we only need the first line
        first_line = result.stdout.strip().split('\n')[0]
        data = json.loads(first_line)

        return VideoInfo(
            title=data.get("title", "Unknown Title"),
            duration=float(data.get("duration", 0)),
            video_id=data.get("id", ""),
            platform="youtube",
            url=url,
            description=data.get("description", ""),
            uploader=data.get("uploader", ""),
            upload_date=data.get("upload_date", ""),
            thumbnail_url=data.get("thumbnail", "")
        )

    @tracer.start_as_current_span("_download_video")
    async def _download_video(self, url: str, video_id: str, output_dir: Path) -> str:
        """Download video"""
        output_path = output_dir / f"{video_id}_video.%(ext)s"

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

        return await self._execute_video_download(cmd, video_id, output_path)
