import asyncio
import json
import json as jsonlib
import re
from pathlib import Path
from typing import Optional

from opentelemetry import trace

from omnibox_wizard.worker.functions.video_utils import VideoProcessor, exec_cmd
from .base_downloader import BaseDownloader, DownloadResult, VideoInfo
from .video_dl_client import YtdlpClient

tracer = trace.get_tracer('BilibiliDownloader')


class BilibiliDownloader(BaseDownloader):
    """Bilibili downloader, using yt-dlp service"""
    platform = "bilibili"

    def __init__(self, video_dl_base_url: Optional[str] = None):
        """
        Initialize Bilibili downloader

        Args:
            video_dl_base_url: Base URL for yt-dlp service. If None, falls back to local yt-dlp
        """
        self.video_dl_base_url = video_dl_base_url
        if video_dl_base_url:
            self.video_dl_client = YtdlpClient(video_dl_base_url)
        else:
            self.video_dl_client = None
            # Fallback to local yt-dlp if no service URL provided
            import subprocess
            try:
                subprocess.run(["yt-dlp", "--version"], capture_output=True, check=True)
            except (subprocess.CalledProcessError, FileNotFoundError):
                raise RuntimeError("yt-dlp service URL not configured and local yt-dlp not installed")

    @classmethod
    async def none_func(cls) -> None:
        return None

    @tracer.start_as_current_span("get_video_and_audio_path")
    async def get_video_and_audio_path(
            self, url: str, output_dir: str, video_id: str, download_video: bool = True,
            force_download_audio: bool = False
    ) -> tuple[str | None, str]:
        output_path = Path(output_dir)
        if download_video:
            video_path_task = asyncio.create_task(self._download_video(url, video_id, output_path))
            if force_download_audio:
                audio_path = await self._download_audio(url, video_id, output_path)
            else:
                video_processor = VideoProcessor(output_dir)
                audio_path = await video_processor.extract_audio(await video_path_task, output_format="wav")
            return await video_path_task, audio_path
        else:
            audio_path = await self._download_audio(url, video_id, output_path)
            return None, audio_path

    @tracer.start_as_current_span("download")
    async def download(
            self, url: str, output_dir: str, download_video: bool = True,
            force_download_audio: bool = False
    ) -> DownloadResult:
        span = trace.get_current_span()
        video_id: str = self.extract_video_id(url)
        video_info, (video_path, audio_path) = await asyncio.gather(
            self.get_video_info(url, video_id),
            self.get_video_and_audio_path(
                url, output_dir, video_id, download_video, force_download_audio)
        )
        span.set_attributes({
            "video_info": jsonlib.dumps(
                video_info.model_dump(exclude_none=True), ensure_ascii=False, separators=(",", ":")),
            "video_path": video_path,
            "audio_path": audio_path,
        })

        return DownloadResult(video_info=video_info, video_path=video_path, audio_path=audio_path)

    @classmethod
    def cmd_wrapper(cls, cmd: list[str]) -> list[str]:
        return cmd

    @classmethod
    async def get_real_url(cls, url: str) -> str:
        """Get real url"""
        cmd = ["curl", "-ILs", "-o", "/dev/null", "-w", "%{url_effective}", url]
        _, stdout, _ = await exec_cmd(cls.cmd_wrapper(cmd))
        return stdout.strip()

    @tracer.start_as_current_span("_get_video_info_base")
    async def _get_video_info_base(self, url):
        if self.video_dl_client:
            # Use yt-dlp service
            data = await self.video_dl_client.extract_info(url)
            return data
        else:
            # Fallback to local yt-dlp
            cmd = [
                "yt-dlp",
                "--no-playlist",
                "--dump-json",
                "--no-download",
                url
            ]

            _, stdout, stderr = await exec_cmd(self.cmd_wrapper(cmd))

            # yt-dlp may return multiple JSON lines, we only need the first line
            first_line = stdout.strip().split('\n')[0]
            data = json.loads(first_line)
            return data

    @tracer.start_as_current_span("get_video_info")
    async def get_video_info(self, url: str, video_id: str) -> VideoInfo:
        data, real_url = await asyncio.gather(
            self._get_video_info_base(url),
            self.get_real_url(url)
        )
        return VideoInfo(
            title=data.get("title", "Unknown Title"),
            duration=float(data.get("duration", 0)),
            video_id=video_id,
            platform="bilibili",
            url=url,
            description=data.get("description", ""),
            uploader=data.get("uploader", ""),
            upload_date=data.get("upload_date", ""),
            thumbnail_url=data.get("thumbnail", ""),
            real_url=real_url,
        )

    @classmethod
    @tracer.start_as_current_span("_extract_video_id")
    def extract_video_id(cls, url: str) -> str:
        bv_match = re.search(r'BV[a-zA-Z0-9]+', url)
        if bv_match:
            return bv_match.group(0)
        av_match = re.search(r'av(\d+)', url)
        if av_match:
            return f"av{av_match.group(1)}"
        return str(hash(url))

    @tracer.start_as_current_span("_download_audio")
    async def _download_audio(self, url: str, video_id: str, output_dir: Path) -> str:
        """Download audio"""
        output_path = output_dir / f"{video_id}.%(ext)s"

        if self.video_dl_client:
            # Use yt-dlp service
            audio_path = await self.video_dl_client.download_audio(
                url=url,
                output_path=output_path,
                audio_format="mp3",
                audio_quality="0"
            )
            return audio_path
        else:
            # Fallback to local yt-dlp
            cmd = [
                "yt-dlp",
                "-x",  # Only extract audio
                "--audio-format", "mp3",
                "--audio-quality", "0",  # Highest quality
                "-o", str(output_path),
                url
            ]

            await exec_cmd(self.cmd_wrapper(cmd))

            # Find generated audio files
            audio_files = list(output_dir.glob(f"{video_id}.*"))
            audio_files = [f for f in audio_files if f.suffix in ['.mp3', '.m4a', '.wav']]

            if not audio_files:
                raise RuntimeError("Audio file not found")

            return str(audio_files[0])

    @tracer.start_as_current_span("_execute_video_download")
    async def _execute_video_download(self, cmd: list[str], video_id: str, output_dir: Path):
        await exec_cmd(self.cmd_wrapper(cmd))

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

        if self.video_dl_client:
            # Use yt-dlp service with default format
            video_path = await self.video_dl_client.download_video(
                url=url,
                output_path=output_path,
                format="best"
            )
            return video_path
        else:
            # Fallback to local yt-dlp
            # Simplify command, don't specify format to let yt-dlp auto-select
            cmd = [
                "yt-dlp",
                "-o", str(output_path),
                url
            ]

            return await self._execute_video_download(cmd, video_id, output_dir)
