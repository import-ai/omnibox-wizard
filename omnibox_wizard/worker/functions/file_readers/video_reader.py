from typing import List, Tuple
from pathlib import Path

from omnibox_wizard.common.trace_info import TraceInfo
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.entity import Image
from omnibox_wizard.worker.functions.video_note_generator import VideoNoteGenerator


class VideoReader:
    def __init__(self, config: WorkerConfig):
        self.config = config
        self.video_note_generator = VideoNoteGenerator(config)
    
    async def convert(self, file_path: str, trace_info: TraceInfo, **kwargs) -> Tuple[str, List[Image]]:
        """
        Convert video file to markdown notes using video_note_generator
        
        Args:
            file_path: Path to the video file
            trace_info: Trace information for logging
            
        Returns:
            Tuple of (markdown_content, images_list)
        """
        try:
            # Use the refactored process_local_video method directly
            result = await self.video_note_generator.process_local_video(
                file_path,
                trace_info = trace_info,
                include_screenshots = kwargs.get("include_screenshots", True),
                include_links = kwargs.get("include_links", False),
                language = kwargs.get("language", "简体中文")
            )
            
            return result.markdown, result.screenshots
            
        except Exception as e:
            trace_info.error({"error": str(e), "message": "Video processing failed"})
            # Return basic video file info as fallback
            video_name = Path(file_path).name
            fallback_markdown = f"# {video_name}\n\nFail to process video file: {str(e)}"
            return fallback_markdown, []