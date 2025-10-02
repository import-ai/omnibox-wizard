import asyncio
import json as jsonlib
import re
from pathlib import Path

from opentelemetry import trace

from omnibox_wizard.worker.functions.video_utils import VideoProcessor, exec_cmd
from .base_downloader import BaseDownloader, DownloadResult, VideoInfo
from .video_dl_client import YtDlpClient

tracer = trace.get_tracer('BilibiliDownloader')


class BilibiliDownloader(BaseDownloader):
    platform = "bilibili"

    def __init__(self, video_dl_base_url: str):
        self.video_dl_base_url = video_dl_base_url
        self.video_dl_client = YtDlpClient(video_dl_base_url)

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
        data = await self.video_dl_client.extract_info(url)
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

        audio_path = await self.video_dl_client.download_audio(
            url=url,
            output_path=output_path,
        )
        return audio_path

    @tracer.start_as_current_span("_download_video")
    async def _download_video(self, url: str, video_id: str, output_dir: Path) -> str:
        output_path = output_dir / f"{video_id}_video.%(ext)s"

        video_path = await self.video_dl_client.download_video(
            url=url,
            output_path=output_path,
        )
        return video_path
