import tempfile
from pathlib import Path

import pytest

from omnibox_wizard.worker.functions.video_downloaders.base_downloader import VideoInfo, DownloadResult
from omnibox_wizard.worker.functions.video_downloaders.bilibili_downloader import BilibiliDownloader


@pytest.mark.integration
class TestBilibiliDownloaderIntegration:
    BILIBILI_URL = "https://www.bilibili.com/video/BV1uT4y1P7CX/"

    def test_extract_video_id_real_url(self):
        downloader = BilibiliDownloader()

        video_id = downloader.extract_video_id(self.BILIBILI_URL)
        assert video_id == "BV1uT4y1P7CX"

        other_formats = [
            "https://www.bilibili.com/video/BV1uT4y1P7CX",
            "https://bilibili.com/video/BV1uT4y1P7CX/?share_source=copy",
            "BV1uT4y1P7CX"
        ]

        for url in other_formats:
            assert downloader.extract_video_id(url) == "BV1uT4y1P7CX"

    async def test_get_video_info_real_url(self):
        downloader = BilibiliDownloader()

        video_info = await downloader.get_video_info(self.BILIBILI_URL, downloader.extract_video_id(self.BILIBILI_URL))

        assert isinstance(video_info, VideoInfo)
        assert video_info.platform == "bilibili"
        assert video_info.url == self.BILIBILI_URL
        assert video_info.video_id == "BV1uT4y1P7CX"

        assert video_info.title != ""
        assert video_info.title != "Unknown Title"
        assert video_info.duration > 0
        assert video_info.uploader != ""

        print(f"Video title: {video_info.title}")
        print(f"Duration: {video_info.duration} seconds")
        print(f"UP主: {video_info.uploader}")
        print(f"Description length: {len(video_info.description)} characters")
        print(f"Upload date: {video_info.upload_date}")

    @pytest.mark.asyncio
    async def test_download_audio_only_real_url(self):
        downloader = BilibiliDownloader()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await downloader.download(self.BILIBILI_URL, temp_dir, download_video=False)

            assert isinstance(result, DownloadResult)
            assert result.audio_path is not None
            assert result.video_path is None
            assert result.video_info.platform == "bilibili"
            assert result.video_info.video_id == "BV1uT4y1P7CX"

            audio_file = Path(result.audio_path)
            assert audio_file.exists()
            assert audio_file.stat().st_size > 0

            assert audio_file.suffix in ['.mp3', '.m4a', '.wav']

            print(f"Audio file: {result.audio_path}")
            print(f"File size: {audio_file.stat().st_size / 1024 / 1024:.2f} MB")

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_download_with_video_real_url(self):
        downloader = BilibiliDownloader()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await downloader.download(self.BILIBILI_URL, temp_dir, download_video=True)

            assert isinstance(result, DownloadResult)
            assert result.audio_path is not None
            assert result.video_path is not None
            assert result.video_info.platform == "bilibili"
            assert result.video_info.video_id == "BV1uT4y1P7CX"

            audio_file = Path(result.audio_path)
            video_file = Path(result.video_path)

            assert audio_file.exists()
            assert video_file.exists()
            assert audio_file.stat().st_size > 0
            assert video_file.stat().st_size > 0

            assert audio_file.suffix in ['.mp3', '.m4a', '.wav']
            assert video_file.suffix in ['.mp4', '.mkv', '.webm', '.flv']

            print(f"Audio file: {result.audio_path}")
            print(f"Video file: {result.video_path}")
            print(f"Audio size: {audio_file.stat().st_size / 1024 / 1024:.2f} MB")
            print(f"Video size: {video_file.stat().st_size / 1024 / 1024:.2f} MB")

    @pytest.mark.asyncio
    async def test_download_error_handling(self):
        downloader = BilibiliDownloader()

        with tempfile.TemporaryDirectory() as temp_dir:
            invalid_url = "https://www.bilibili.com/video/BV1invalidvideo/"

            with pytest.raises(Exception):
                await downloader.download(invalid_url, temp_dir)

    def test_temp_directory_cleanup(self):
        """Test that temporary directory is properly cleaned up"""
        downloader = BilibiliDownloader()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create a test file
            test_file = temp_path / "BV1uT4y1P7CX.mp3"
            test_file.touch()
            assert test_file.exists()

            # Directory should exist during the context
            assert temp_path.exists()

        # Directory should be cleaned up after the context
        assert not temp_path.exists()

    def test_video_id_extraction_edge_cases(self):
        downloader = BilibiliDownloader()

        test_cases = [
            ("https://www.bilibili.com/video/BV1xx411c7mD?p=1", "BV1xx411c7mD"),
            ("https://bilibili.com/video/BV1Ab4y1x7Gw?from=search", "BV1Ab4y1x7Gw"),
            ("BV1234567890", "BV1234567890"),
            ("https://www.bilibili.com/video/av170001", "av170001"),
            ("https://bilibili.com/video/av999999?from=search", "av999999"),
            ("av123456", "av123456"),
            ("https://www.bilibili.com/video/BV1uT4y1P7CX?p=2", "BV1uT4y1P7CX"),
        ]

        for url, expected_id in test_cases:
            actual_id = downloader.extract_video_id(url)
            assert actual_id == expected_id, f"URL: {url}, Expected: {expected_id}, Actual: {actual_id}"

    def test_fallback_video_id(self):
        downloader = BilibiliDownloader()

        bangumi_url = "https://www.bilibili.com/bangumi/play/ep123456"
        video_id = downloader.extract_video_id(bangumi_url)

        expected_hash = str(hash(bangumi_url))
        assert video_id == expected_hash
