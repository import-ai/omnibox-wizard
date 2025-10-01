import os
import tempfile
from pathlib import Path

import pytest
from dotenv import load_dotenv

from omnibox_wizard.worker.functions.video_downloaders.base_downloader import VideoInfo, DownloadResult
from omnibox_wizard.worker.functions.video_downloaders.youtube_downloader import YouTubeDownloader

load_dotenv()


@pytest.mark.integration
class TestYouTubeDownloaderIntegration:
    YOUTUBE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    VIDEO_DL_BASE_URL = os.environ["OBW_TASK_VIDEO_DL_BASE_URL"]  # Default yt-dlp service URL

    async def test_get_video_info_real_url(self):
        downloader = YouTubeDownloader(self.VIDEO_DL_BASE_URL)

        video_info = await downloader.get_video_info(self.YOUTUBE_URL, downloader.extract_video_id(self.YOUTUBE_URL))

        assert isinstance(video_info, VideoInfo)
        assert video_info.platform == "youtube"
        assert video_info.url == self.YOUTUBE_URL
        assert video_info.video_id == "dQw4w9WgXcQ"

        assert video_info.title != ""
        assert video_info.title != "Unknown Title"
        assert video_info.duration > 0
        assert video_info.uploader != ""

        print(f"Video title: {video_info.title}")
        print(f"Duration: {video_info.duration} seconds")
        print(f"Uploader: {video_info.uploader}")
        print(f"Description length: {len(video_info.description)} characters")

    @pytest.mark.asyncio
    async def test_download_audio_only_real_url(self):
        downloader = YouTubeDownloader(self.VIDEO_DL_BASE_URL)

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await downloader.download(self.YOUTUBE_URL, temp_dir, download_video=False)

            assert isinstance(result, DownloadResult)
            assert result.audio_path is not None
            assert result.video_path is None
            assert result.video_info.platform == "youtube"

            audio_file = Path(result.audio_path)
            assert audio_file.exists()
            assert audio_file.stat().st_size > 0
            assert audio_file.suffix in ['.mp3', '.m4a', '.wav']

            print(f"Audio file: {result.audio_path}")
            print(f"File size: {audio_file.stat().st_size / 1024 / 1024:.2f} MB")

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_download_with_video_real_url(self):
        downloader = YouTubeDownloader(self.VIDEO_DL_BASE_URL)

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await downloader.download(self.YOUTUBE_URL, temp_dir, download_video=True)

            assert isinstance(result, DownloadResult)
            assert result.audio_path is not None
            assert result.video_path is not None
            assert result.video_info.platform == "youtube"

            audio_file = Path(result.audio_path)
            video_file = Path(result.video_path)

            assert audio_file.exists()
            assert video_file.exists()
            assert audio_file.stat().st_size > 0
            assert video_file.stat().st_size > 0

            assert audio_file.suffix in ['.mp3', '.m4a', '.wav']
            assert video_file.suffix in ['.mp4', '.mkv', '.webm']

            print(f"Audio file: {result.audio_path}")
            print(f"Video file: {result.video_path}")
            print(f"Audio size: {audio_file.stat().st_size / 1024 / 1024:.2f} MB")
            print(f"Video size: {video_file.stat().st_size / 1024 / 1024:.2f} MB")

    @pytest.mark.asyncio
    async def test_download_error_handling(self):
        downloader = YouTubeDownloader(self.VIDEO_DL_BASE_URL)

        with tempfile.TemporaryDirectory() as temp_dir:
            invalid_url = "https://www.youtube.com/watch?v=invalid_video_id"

            with pytest.raises(Exception):
                await downloader.download(invalid_url, temp_dir)

    def test_temp_directory_cleanup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create a test file
            test_file = temp_path / "test.mp3"
            test_file.touch()
            assert test_file.exists()

            # Directory should exist during the context
            assert temp_path.exists()

        # Directory should be cleaned up after the context
        assert not temp_path.exists()
