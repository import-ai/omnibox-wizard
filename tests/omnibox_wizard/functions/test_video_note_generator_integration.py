import pytest
import os
from pathlib import Path

from omnibox_wizard.worker.entity import Task
from omnibox_wizard.worker.functions.video_note_generator import VideoNoteGenerator


@pytest.mark.integration
class TestVideoNoteGeneratorIntegration:
    YOUTUBE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    BILIBILI_URL = "https://www.bilibili.com/video/BV1uT4y1P7CX/"
    
    @pytest.mark.asyncio
    async def test_youtube_integration_audio_only(self, remote_worker_config, trace_info):
        video_note_generator = VideoNoteGenerator(remote_worker_config)
        
        task = Task(
            id="test-youtube-integration",
            priority=1,
            namespace_id="test_namespace",
            user_id="test_user",
            function="generate_video_note",
            input={
                "url": self.YOUTUBE_URL,
                "include_screenshots": False,
                "include_links": True,
                "language": "en"
            }
        )
        
        try:

            result = await video_note_generator.run(task, trace_info)
            
            assert "markdown" in result
            assert "transcript" in result
            assert "video_info" in result
            assert "screenshots" in result
            
            assert isinstance(result["screenshots"], list)
            for screenshot in result["screenshots"]:
                if screenshot:
                    assert "name" in screenshot
                    assert "link" in screenshot  
                    assert "data" in screenshot
                    assert "mimetype" in screenshot
            
            video_info = result["video_info"]
            assert video_info["platform"] == "youtube"
            assert video_info["video_id"] == "dQw4w9WgXcQ"
            assert video_info["url"] == self.YOUTUBE_URL
            assert video_info["title"] != ""
            assert video_info["duration"] > 0
            
            assert result["transcript"]["full_text"] != ""
            assert result["markdown"] != ""
            
            print(f"YouTube video title: {video_info['title']}")
            print(f"Video duration: {video_info['duration']} seconds")
            print(f"Transcript length: {len(result['transcript']['full_text'])} characters")
            print(f"Note length: {len(result['markdown'])} characters")
            
        finally:
            pass
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_bilibili_integration_with_screenshots(self, remote_worker_config, trace_info):
        video_note_generator = VideoNoteGenerator(remote_worker_config)
        
        task = Task(
            id="test-bilibili-integration",
            priority=1,
            namespace_id="test_namespace",
            user_id="test_user",
            function="generate_video_note", 
            input={
                "url": self.BILIBILI_URL,
                "style": "Concise Style",
                "include_screenshots": True,
                "include_links": False,
                "language": "English",
                "generate_thumbnail": True
            }
        )
        
        try:
            result = await video_note_generator.run(task, trace_info)
            video_info = result["video_info"]
            assert video_info["platform"] == "bilibili"
            assert video_info["video_id"] == "BV1uT4y1P7CX"
            assert video_info["url"] == self.BILIBILI_URL
            assert video_info["title"] != ""
            assert video_info["duration"] > 0
            
            assert result["transcript"]["full_text"] != ""
            assert result["markdown"] != ""
            
            print(f"Bilibili video title: {video_info['title']}")
            print(f"UP: {video_info['uploader']}")
            print(f"Video duration: {video_info['duration']} seconds")
            print(f"Transcript length: {len(result['transcript']['full_text'])} characters")
            print(f"Note length: {len(result['markdown'])} characters")
            print(f"Screenshot processing: {'Enabled' if task.input['include_screenshots'] else 'Disabled'}")
            
        finally:
            pass
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_youtube_integration_with_screenshots(self, remote_worker_config, trace_info):
        video_note_generator = VideoNoteGenerator(remote_worker_config)
        
        task = Task(
            id="test-youtube-screenshots-integration",
            priority=1,
            namespace_id="test_namespace",
            user_id="test_user",
            function="generate_video_note", 
            input={
                "url": self.YOUTUBE_URL,
                "style": "Concise Style",
                "include_screenshots": True,
                "include_links": False,
                "language": "en"
            }
        )
        
        try:
            result = await video_note_generator.run(task, trace_info)
            video_info = result["video_info"]
            assert video_info["platform"] == "youtube"
            assert video_info["video_id"] == "dQw4w9WgXcQ"
            assert video_info["url"] == self.YOUTUBE_URL
            assert video_info["title"] != ""
            assert video_info["duration"] > 0
            
            assert result["transcript"]["full_text"] != ""
            assert result["markdown"] != ""
            
            print(f"YouTube video title: {video_info['title']}")
            print(f"Uploader: {video_info.get('uploader', 'Unknown')}")
            print(f"Video duration: {video_info['duration']} seconds")
            print(f"Transcript length: {len(result['transcript']['full_text'])} characters")
            print(f"Note length: {len(result['markdown'])} characters")
            print(f"Screenshot processing: {'Enabled' if task.input['include_screenshots'] else 'Disabled'}")
            
        finally:
            pass
    
    @pytest.mark.asyncio
    async def test_different_styles_integration(self, remote_worker_config, trace_info):
        styles = ["Academic Style", "Concise Style", "Detailed Style", "Simple Style"]
        
        for style in styles:
            video_note_generator = VideoNoteGenerator(remote_worker_config)
            
            task = Task(
                id=f"test-style-{style}",
                priority=1,
                namespace_id="test_namespace",
                user_id="test_user",
                function="generate_video_note",
                input={
                    "url": self.YOUTUBE_URL,
                    "style": style,
                    "include_screenshots": False,
                    "include_links": False
                }
            )
            
            try:
                result = await video_note_generator.run(task, trace_info)
                
                assert result["markdown"] != ""
                assert result["transcript"]["full_text"] != ""
                assert result["video_info"]["title"] != ""
                
                print(f"Style '{style}' test passed, note length: {len(result['markdown'])} characters")
                
            finally:
                pass
    
    @pytest.mark.asyncio
    async def test_error_handling_invalid_url(self, remote_worker_config, trace_info):
        video_note_generator = VideoNoteGenerator(remote_worker_config)
        
        task = Task(
            id="test-invalid-url",
            priority=1,
            namespace_id="test_namespace",
            user_id="test_user",
            function="generate_video_note",
            input={
                "url": "https://www.youtube.com/watch?v=invalid_video_id_12345",
                "style": "Academic Style"
            }
        )
        
        with pytest.raises(Exception):
            await video_note_generator.run(task, trace_info)
    
    @pytest.mark.asyncio
    async def test_missing_video_url(self, remote_worker_config, trace_info):
        video_note_generator = VideoNoteGenerator(remote_worker_config)
        
        task = Task(
            id="test-missing-url",
            priority=1,
            namespace_id="test_namespace",
            user_id="test_user",
            function="generate_video_note",
            input={
                "style": "Academic Style"
            }
        )
        
        with pytest.raises(ValueError, match="url is required"):
            await video_note_generator.run(task, trace_info)
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_all_parameters_combination(self, remote_worker_config, trace_info):
        video_note_generator = VideoNoteGenerator(remote_worker_config)
        
        task = Task(
            id="test-all-params",
            priority=1,
            namespace_id="test_namespace",
            user_id="test_user",
            function="generate_video_note",
            input={
                "url": self.YOUTUBE_URL,
                "include_screenshots": True,
                "include_links": True,
                "language": "zh",
                "generate_thumbnail": True,
                "thumbnail_grid_size": [2, 2],
                "thumbnail_interval": 60
            }
        )
        
        try:
            result = await video_note_generator.run(task, trace_info)
            
            assert result["markdown"] != ""
            assert result["transcript"]["full_text"] != ""
            assert result["video_info"]["title"] != ""
            
            print(f"All features test passed, note length: {len(result['markdown'])} characters")
            if result.get("screenshots"):
                print(f"Generated {len(result['screenshots'])} Image objects (screenshots and thumbnails)")
                
        finally:
            pass
    
    @pytest.mark.asyncio
    async def test_platform_detection(self, remote_worker_config, trace_info):
        test_cases = [
            (self.YOUTUBE_URL, "youtube", "dQw4w9WgXcQ"),
            (self.BILIBILI_URL, "bilibili", "BV1uT4y1P7CX"),
        ]
        
        for url, expected_platform, expected_id in test_cases:
            video_note_generator = VideoNoteGenerator(remote_worker_config)
            
            task = Task(
                id=f"test-platform-{expected_platform}",
                priority=1,
                namespace_id="test_namespace",
                user_id="test_user",
                function="generate_video_note",
                input={
                    "url": url
                }
            )
            
            try:
                result = await video_note_generator.run(task, trace_info)
                
                video_info = result["video_info"]
                assert video_info["platform"] == expected_platform
                assert video_info["video_id"] == expected_id
                assert video_info["url"] == url
                
                print(f"Platform {expected_platform} detection correct, video ID: {expected_id}")
                
            finally:
                pass
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_process_local_video(self, remote_worker_config, trace_info):
        """Test process_local_video function directly with local video file"""
        local_video_path = "/Users/alex_wu/work/changyuan/codes/omnibox-wizard/tests/omnibox_wizard/resources/files/video.mp4"
        
        # Skip if test files don't exist
        if not os.path.exists(local_video_path):
            pytest.skip("Test video file not found. Skipping local video test.")
        
        video_note_generator = VideoNoteGenerator(remote_worker_config)
        
        try:
            # Test process_local_video directly
            result = await video_note_generator.process_local_video(
                file_path=local_video_path,
                include_screenshots=True,
                include_links=False,
                language="zh",
                generate_thumbnail=False,
                thumbnail_grid_size=[3, 3],
                thumbnail_interval=30,
                trace_info=trace_info
            )
            
            # Verify result is VideoNoteResult object
            from omnibox_wizard.worker.functions.video_note_generator import VideoNoteResult
            assert isinstance(result, VideoNoteResult)
            
            # Verify result structure
            assert result.markdown != ""
            assert result.transcript is not None
            assert result.video_info.platform == "local"
            assert result.video_info.title == Path(local_video_path).stem
            assert result.video_info.url == f"file://{local_video_path}"
            assert isinstance(result.images, list)
            
            # Verify transcript structure
            assert "full_text" in result.transcript
            assert result.transcript["full_text"] != ""
            
            # Verify screenshot functionality if enabled
            if result.images:
                for image in result.images:
                    from omnibox_wizard.worker.entity import Image
                    assert isinstance(image, Image)
                    assert hasattr(image, 'name')
                    assert hasattr(image, 'link')
                    assert hasattr(image, 'data')
                    assert hasattr(image, 'mimetype')
            
            print(f"Local video process_local_video test passed")
            print(f"Video file: {local_video_path}")
            print(f"Video title: {result.video_info.title}")
            print(f"Platform: {result.video_info.platform}")
            print(f"URL: {result.video_info.url}")
            print(f"Transcript length: {len(result.transcript['full_text'])} characters")
            print(f"Note length: {len(result.markdown)} characters")
            print(f"Generated image count: {len(result.images)}")
            
        except Exception as e:
            print(f"process_local_video test failed: {str(e)}")
            if "unsupported" in str(e).lower() or "permission" in str(e).lower():
                pytest.skip(f"Local video processing not supported: {str(e)}")
            else:
                raise
        finally:
            pass
    
    @pytest.mark.asyncio
    async def test_process_local_video_file_not_found(self, remote_worker_config, trace_info):
        video_note_generator = VideoNoteGenerator(remote_worker_config)
        
        non_existent_file = "file:///path/to/non_existent_video.mp4"
        
        task = Task(
            id="test-local-video-not-found",
            priority=1,
            namespace_id="test_namespace",
            user_id="test_user", 
            function="generate_video_note",
            input={
                "url": non_existent_file,
            }
        )
        
        with pytest.raises(Exception):
            await video_note_generator.run(task, trace_info)
            
        print("Local video file not found error handling test passed")