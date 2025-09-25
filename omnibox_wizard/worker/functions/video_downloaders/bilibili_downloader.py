import asyncio
import json
import json as jsonlib
import re
import subprocess
from pathlib import Path

from opentelemetry import trace

from omnibox_wizard.worker.functions.video_utils import VideoProcessor
from .base_downloader import BaseDownloader, DownloadResult, VideoInfo

tracer = trace.get_tracer('BilibiliDownloader')


class BilibiliDownloader(BaseDownloader):
    """Bilibili downloader, using yt-dlp"""

    def __init__(self):
        self._check_yt_dlp()

    @classmethod
    def _check_yt_dlp(cls):
        """Check if yt-dlp is installed"""
        try:
            subprocess.run(["yt-dlp", "--version"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise RuntimeError("yt-dlp is not installed. Please run: pip install yt-dlp")

    @tracer.start_as_current_span("download")
    async def download(
            self, url: str, output_dir: str, download_video: bool = True,
            download_audio: bool = False
    ) -> DownloadResult:
        span = trace.get_current_span()
        video_info = self.get_video_info(url)
        span.set_attribute("video_info", jsonlib.dumps(
            video_info.model_dump(exclude_none=True), ensure_ascii=False, separators=(",", ":")))
        output_path = Path(output_dir)

        video_path = await self._download_video(url, video_info.video_id, output_path) if download_video else None

        if download_audio or not download_video:
            audio_path = await self._download_audio(url, video_info.video_id, output_path)
        else:
            video_processor = VideoProcessor(output_dir)
            audio_path = video_processor.extract_audio(video_path, output_format="wav")

        return DownloadResult(
            audio_path=audio_path,
            video_path=video_path,
            video_info=video_info
        )

    @tracer.start_as_current_span("get_video_info")
    def get_video_info(self, url: str) -> VideoInfo:
        """Get Bilibili video information"""
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

        # Extract BV number or av number as video_id
        video_id = self._extract_video_id(url)

        return VideoInfo(
            title=data.get("title", "Unknown Title"),
            duration=float(data.get("duration", 0)),
            video_id=video_id,
            platform="bilibili",
            url=url,
            description=data.get("description", ""),
            uploader=data.get("uploader", ""),
            upload_date=data.get("upload_date", ""),
            thumbnail_url=data.get("thumbnail", "")
        )

    @classmethod
    @tracer.start_as_current_span("_extract_video_id")
    def _extract_video_id(cls, url: str) -> str:
        """Extract Bilibili video ID from URL"""
        # Match BV number
        bv_match = re.search(r'BV[a-zA-Z0-9]+', url)
        if bv_match:
            return bv_match.group(0)

        # Match av number
        av_match = re.search(r'av(\d+)', url)
        if av_match:
            return f"av{av_match.group(1)}"

        # If none matches, use URL hash
        return str(hash(url))

    @tracer.start_as_current_span("_download_audio")
    async def _download_audio(self, url: str, video_id: str, output_dir: Path) -> str:
        """Download audio"""
        output_path = output_dir / f"{video_id}.%(ext)s"

        cmd = [
            "yt-dlp",
            "-x",  # Only extract audio
            "--audio-format", "mp3",
            "--audio-quality", "0",  # Highest quality
            "-o", str(output_path),
            url
        ]

        await self._exec(cmd)

        # Find generated audio files
        audio_files = list(output_dir.glob(f"{video_id}.*"))
        audio_files = [f for f in audio_files if f.suffix in ['.mp3', '.m4a', '.wav']]

        if not audio_files:
            raise RuntimeError("Audio file not found")

        return str(audio_files[0])

    @classmethod
    @tracer.start_as_current_span("_exec")
    async def _exec(cls, cmd: list[str]):
        span = trace.get_current_span()
        span.set_attribute("command", " ".join(cmd))

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode()
            span.set_attributes({"error": error_msg, "return_code": process.returncode, "stdout": stdout.decode()})
            raise RuntimeError(f"yt-dlp download failed: {error_msg}")

    @tracer.start_as_current_span("_execute_video_download")
    async def _execute_video_download(self, cmd: list[str], video_id: str, output_dir: Path):
        await self._exec(cmd)

        # Find generated video files
        video_files = list(output_dir.glob(f"{video_id}_video.*"))
        video_files = [f for f in video_files if f.suffix in ['.mp4', '.mkv', '.webm', '.flv']]

        if not video_files:
            raise RuntimeError("Video file not found")

        return str(video_files[0])

    @tracer.start_as_current_span("_download_video")
    async def _download_video(self, url: str, video_id: str, output_dir: Path) -> str:
        """Download video"""
        output_path = output_dir / f"{video_id}_video.%(ext)s"

        # Simplify command, don't specify format to let yt-dlp auto-select
        cmd = [
            "yt-dlp",
            "-o", str(output_path),
            url
        ]

        return await self._execute_video_download(cmd, video_id, output_dir)
