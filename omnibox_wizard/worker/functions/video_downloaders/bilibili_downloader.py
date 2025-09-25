import asyncio
import json
import json as jsonlib
import re
import subprocess
from pathlib import Path

from opentelemetry import trace

from omnibox_wizard.worker.functions.video_utils import VideoProcessor, exec_cmd
from .base_downloader import BaseDownloader, DownloadResult, VideoInfo

tracer = trace.get_tracer('BilibiliDownloader')


class BilibiliDownloader(BaseDownloader):
    """Bilibili downloader, using yt-dlp"""
    platform = "bilibili"

    def __init__(self):
        self._check_yt_dlp()

    @classmethod
    def _check_yt_dlp(cls):
        """Check if yt-dlp is installed"""
        try:
            subprocess.run(["yt-dlp", "--version"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise RuntimeError("yt-dlp is not installed. Please run: pip install yt-dlp")

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

    @tracer.start_as_current_span("_get_video_info_base")
    async def _get_video_info_base(self, url):
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
        data = await self._get_video_info_base(url)
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

        # Simplify command, don't specify format to let yt-dlp auto-select
        cmd = [
            "yt-dlp",
            "-o", str(output_path),
            url
        ]

        return await self._execute_video_download(cmd, video_id, output_dir)
