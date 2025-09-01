import asyncio
import json
import logging
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from .base_downloader import BaseDownloader, DownloadResult, VideoInfo

logger = logging.getLogger(__name__)


class BilibiliDownloader(BaseDownloader):
    """Bilibili downloader, using yt-dlp"""
    
    def __init__(self):
        self._check_yt_dlp()
    
    def _check_yt_dlp(self):
        """Check if yt-dlp is installed"""
        try:
            subprocess.run(["yt-dlp", "--version"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise RuntimeError("yt-dlp is not installed. Please run: pip install yt-dlp")
    
    async def download(self, url: str, output_dir: str, download_video: bool = False) -> DownloadResult:
        """Download Bilibili video/audio"""
        logger.info(f"Start to download Bilibili content: {url}")
        
        # Get video information
        video_info = self.get_video_info(url)
        output_path = Path(output_dir)
        
        # Download audio
        audio_path = await self._download_audio(url, video_info.video_id, output_path)
        
        # If needed, download video
        video_path = None
        if download_video:
            video_path = await self._download_video(url, video_info.video_id, output_path)
        
        return DownloadResult(
            audio_path=audio_path,
            video_path=video_path,
            video_info=video_info
        )
    
    def get_video_info(self, url: str) -> VideoInfo:
        """Get Bilibili video information"""
        try:
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
            
        except Exception as e:
            logger.error(f"Fail to get Bilibili video information: {e}")
            raise
    
    def _extract_video_id(self, url: str) -> str:
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
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                error_msg = stderr.decode()
                logger.error(f"yt-dlp audio download failed: {error_msg}")
                raise RuntimeError(f"yt-dlp audio download failed: {error_msg}")
            
            # Find generated audio files
            audio_files = list(output_dir.glob(f"{video_id}.*"))
            audio_files = [f for f in audio_files if f.suffix in ['.mp3', '.m4a', '.wav']]
            
            if not audio_files:
                raise RuntimeError("Audio file not found")
            
            return str(audio_files[0])
            
        except Exception as e:
            logger.error(f"Bilibili audio download failed: {e}")
            raise
    
    async def _download_video(self, url: str, video_id: str, output_dir: Path) -> str:
        """Download video"""
        output_path = output_dir / f"{video_id}_video.%(ext)s"
        
        # Simplify command, don't specify format to let yt-dlp auto-select
        cmd = [
            "yt-dlp",
            "-o", str(output_path),
            url
        ]
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                error_msg = stderr.decode()
                logger.error(f"yt-dlp video download failed: {error_msg}")
                raise RuntimeError(f"yt-dlp video download failed: {error_msg}")
            
            # Find generated video files
            video_files = list(output_dir.glob(f"{video_id}_video.*"))
            video_files = [f for f in video_files if f.suffix in ['.mp4', '.mkv', '.webm', '.flv']]
            
            if not video_files:
                raise RuntimeError("Video file not found")
            
            return str(video_files[0])
            
        except Exception as e:
            logger.error(f"Bilibili video download failed: {e}")
            raise