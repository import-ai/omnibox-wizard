import json as jsonlib
import mimetypes
import re
import tempfile
from pathlib import Path
from typing import List, Dict, Any

from opentelemetry import trace

from omnibox_wizard.common import project_root
from omnibox_wizard.common.template_parser import TemplateParser
from omnibox_wizard.common.trace_info import TraceInfo
from omnibox_wizard.common.utils import remove_continuous_break_lines
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.entity import Task, Image
from omnibox_wizard.worker.functions.base_function import BaseFunction
from omnibox_wizard.worker.functions.file_readers.audio_reader import ASRClient
from omnibox_wizard.worker.functions.video_downloaders.base_downloader import VideoInfo
from omnibox_wizard.worker.functions.video_downloaders.downloader_factory import DownloaderFactory
from omnibox_wizard.worker.functions.video_utils import VideoProcessor

tracer = trace.get_tracer('VideoNoteGenerator')


class VideoNoteResult:
    """Video note generation result"""

    def __init__(self, markdown: str, transcript: Dict[str, Any], video_info: VideoInfo,
                 screenshots: List[Image] = None, thumbnail_image: Image = None):
        self.markdown = markdown
        self.transcript = transcript
        self.video_info = video_info
        self.screenshots = screenshots or []
        self.thumbnail_image = thumbnail_image or None


class VideoNoteGenerator(BaseFunction):
    """Video note generator"""

    def __init__(self, config: WorkerConfig):
        self.config = config
        self.asr_client = ASRClient(
            model=config.task.asr.model,
            base_url=config.task.asr.base_url,
            headers={"Authorization": f"Bearer {config.task.asr.api_key}"},
        )

        # Initialize template parser
        prompts_dir = project_root.path("omnibox_wizard/resources/prompts")
        self.template_parser = TemplateParser(str(prompts_dir))

        # Base64 image pattern, consistent with office_reader.py
        self.base64_img_pattern = re.compile(r"data:image/[^;]+;base64,([^\"')}]+)")

        self.language_map = {"简体中文": "zh", "English": "en"}

    @staticmethod
    def seconds_to_hms(seconds: int) -> str:
        """
        Convert seconds to HH:MM:SS format string

        Args:
            seconds: Total seconds

        Returns:
            Formatted time string "HH:MM:SS"
        """
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def _get_best_subtitle(self, subtitles: dict, language: str) -> str:
        """
        Intelligently select the best subtitle from available options

        Args:
            subtitles: Dictionary of subtitles {lang: content}
            language: Preferred language (e.g., "简体中文", "English")

        Returns:
            Subtitle text content (empty string if none found)
        """
        if not subtitles:
            return ""

        lang_code = self.language_map.get(language, "zh")

        # Priority: manual subtitle > AI subtitle > any available subtitle
        candidates = [
            lang_code,              # zh, en
            f"ai-{lang_code}",     # ai-zh, ai-en
        ]

        # Try exact matches first
        for pattern in candidates:
            if pattern in subtitles and subtitles[pattern].strip():
                return subtitles[pattern]

        # Try prefix matches (e.g., "zh" matches "zh-CN", "zh-Hans")
        for pattern in candidates:
            for sub_lang, content in subtitles.items():
                if sub_lang.startswith(pattern) and content.strip():
                    return content

        # If no match found, return first available subtitle
        return next((content for content in subtitles.values() if content.strip()), "")

    @tracer.start_as_current_span('run')
    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        """Execute video note generation task"""
        span = trace.get_current_span()

        input_dict = task.input

        # Validate input
        video_url = input_dict.get("url", "")
        title = input_dict.get("title", "")

        # Parse configuration parameters
        style = input_dict.get("style", "Concise Style")
        include_screenshots = input_dict.get("include_screenshots", True)
        include_links = input_dict.get("include_links", False)
        language = input_dict.get("language", "简体中文")

        # Video thumbnail configuration
        generate_thumbnail = input_dict.get("generate_thumbnail", False)
        thumbnail_grid_size = input_dict.get("thumbnail_grid_size", [3, 3])
        thumbnail_interval = input_dict.get("thumbnail_interval", 30)  # seconds

        cookies = input_dict.get('cookies', None)
        
        span.set_attribute("config", jsonlib.dumps({
            "style": style,
            "include_screenshots": include_screenshots,
            "include_links": include_links,
            "language": language,
            "generate_thumbnail": generate_thumbnail,
            "thumbnail_grid_size": thumbnail_grid_size,
            "thumbnail_interval": thumbnail_interval,
        }, ensure_ascii=False, separators=(",", ":")))

        trace_info = trace_info.bind(
            video_url=video_url,
            include_screenshots=include_screenshots,
            include_links=include_links
        )
        trace_info.debug({"message": "Starting video note generation"})

        with tempfile.TemporaryDirectory(prefix="video_note_") as temp_dir:
            try:
                # 1. Create downloader and download
                trace_info.debug({"message": "Creating downloader"})
                video_dl_base_url = self.config.task.video_dl_base_url
                downloader = DownloaderFactory.create_downloader(video_url, video_dl_base_url)
                platform = DownloaderFactory.get_platform(video_url)
                trace_info.debug({"platform": platform, "message": "Downloader created"})

                # 2. Download audio and video (if needed)
                trace_info.debug({"message": "Starting content download"})
                download_result = await downloader.download(video_url, temp_dir, download_video=include_screenshots, cookies=cookies)
                trace_info.debug({
                    "audio_path": download_result.audio_path,
                    "video_path": download_result.video_path,
                    "message": "Content download completed"
                })

                # 3. Process video content using common logic
                result = await self._process_video_content(
                    audio_path=download_result.audio_path,
                    video_path=download_result.video_path,
                    video_info=download_result.video_info,
                    subtitles=download_result.subtitles,
                    chapters=download_result.chapters,
                    style=style,
                    include_screenshots=include_screenshots,
                    include_links=include_links,
                    language=language,
                    generate_thumbnail=generate_thumbnail,
                    thumbnail_grid_size=thumbnail_grid_size,
                    thumbnail_interval=thumbnail_interval,
                    temp_dir=temp_dir,
                    trace_info=trace_info
                )

                trace_info.debug({"message": "Video note generation successful"})
                result_dict = {
                    "markdown": f"> [{title}]({download_result.video_info.real_url})\n\n" + result.markdown,
                    "transcript": result.transcript,
                    "video_info": {
                        "title": result.video_info.title,
                        "duration": result.video_info.duration,
                        "video_id": result.video_info.video_id,
                        "platform": result.video_info.platform,
                        "url": result.video_info.url,
                        "description": result.video_info.description,
                        "uploader": result.video_info.uploader,
                        "upload_date": result.video_info.upload_date
                    },
                    "images": [img.model_dump() for img in result.screenshots],
                }
                if result.thumbnail_image:
                    result_dict["thumbnail_image"] = result.thumbnail_image.model_dump()
                return result_dict

            except Exception as e:
                trace_info.error({"error": str(e), "message": "Video note generation failed"})
                raise

    @tracer.start_as_current_span('_transcribe_audio')
    async def _transcribe_audio(self, audio_path: str, trace_info: TraceInfo) -> Dict[str, Any]:
        try:
            mimetype, _ = mimetypes.guess_type(audio_path)
            text = await self.asr_client.transcribe(audio_path, mimetype)

            return {
                "full_text": text,
                "segments": [{"start": 0.0, "end": 0.0, "text": text}]
            }

        except Exception as e:
            trace_info.error({"error": str(e), "message": "Fail to transcribe audio"})
            raise

    @tracer.start_as_current_span('_generate_fallback_markdown')
    def _generate_fallback_markdown(
            self,
            video_info: VideoInfo,
            include_screenshots: bool,
            include_links: bool,
            language: str
    ) -> str:

        markdown_parts = []
        if include_screenshots:
            # Add screenshot placeholders
            total_screenshots = 5
            duration_seconds = video_info.duration

            if duration_seconds > 0:
                interval = duration_seconds / (total_screenshots + 1)

                for i in range(1, total_screenshots + 1):
                    timestamp_seconds = int(interval * i)
                    hours = timestamp_seconds // 3600
                    minutes = (timestamp_seconds % 3600) // 60
                    seconds = timestamp_seconds % 60
                    markdown_parts.append(f"*Screenshot-{hours:02d}:{minutes:02d}:{seconds:02d}")
                    markdown_parts.append("")

        return "\n".join(markdown_parts)

    @tracer.start_as_current_span('_generate_markdown')
    async def _generate_markdown(
            self,
            video_info: VideoInfo,
            transcript: Dict[str, Any],
            chapters: list[dict],
            style: str,
            include_screenshots: bool,
            include_links: bool,
            language: str,
            trace_info: TraceInfo
    ) -> str:
        # Check if we have transcript content
        transcript_text = transcript.get('full_text', '').strip()

        if not transcript_text:
            # No audio content, use fallback template without LLM call
            trace_info.info({"message": "No transcript available, generating fallback markdown without LLM"})
            return self._generate_fallback_markdown(
                video_info, include_screenshots, include_links, language
            )

        # Use Jinja2 template with proper conditional rendering
        template = self.template_parser.get_template("video_note_generation.md")
        prompt = self.template_parser.render_template(
            template,
            video_title=video_info.title,
            video_platform=video_info.platform,
            video_duration=f"{video_info.duration / 60:.1f}",
            transcript_text=transcript_text,
            chapters=chapters,
            note_style=style,
            include_screenshots=include_screenshots,
            include_links=include_links,
            lang=language
        )

        try:
            response = await self._call_ai_for_summary(prompt, trace_info)
            return response

        except Exception as e:
            trace_info.error({"error": str(e), "message": "Fail to generate AI note"})
            raise

    @tracer.start_as_current_span('_call_ai_for_summary')
    async def _call_ai_for_summary(self, prompt: str, trace_info: TraceInfo) -> str:
        """Call AI to generate summary"""
        openai_client = self.config.grimoire.openai.get_config("default")

        response = await openai_client.chat(
            messages=[
                {"role": "user", "content": prompt}
            ],
            extra_headers={"X-Request-Id": trace_info.request_id}
        )

        return response.choices[0].message.content

    @tracer.start_as_current_span('_process_video_content')
    async def _process_video_content(
            self,
            audio_path: str | None,
            video_path: str,
            video_info: VideoInfo,
            subtitles: dict,
            chapters: list[dict],
            style: str,
            include_screenshots: bool,
            include_links: bool,
            language: str,
            generate_thumbnail: bool,
            thumbnail_grid_size: list,
            thumbnail_interval: int,
            temp_dir: str,
            trace_info: TraceInfo
    ) -> VideoNoteResult:
        """Common video processing logic used by both URL and local file processing"""

        # 1. Audio transcription (only if audio_path is provided)
        transcript_dict = {"full_text": "", "segments": []}
        has_audio_content = False

        if len(subtitles) > 0:
            subtitle_text = self._get_best_subtitle(subtitles, language)

            if subtitle_text:
                transcript_dict = {"full_text": subtitle_text, "segments": []}
                has_audio_content = True
                trace_info.info({
                    "subtitle_length": len(subtitle_text),
                    "available_langs": list(subtitles.keys()),
                    "message": "Using subtitle as transcript"
                })
            else:
                trace_info.warning({"message": "Subtitles exist but all are empty"})
        elif audio_path:
            trace_info.info({"message": "Starting audio transcription"})
            try:
                transcript_dict = await self._transcribe_audio(audio_path, trace_info)
                has_audio_content = bool(transcript_dict.get("full_text", "").strip())
                trace_info.info({"transcript_length": len(transcript_dict.get("full_text", "")),
                                 "message": "Audio transcription completed"})
            except Exception as e:
                trace_info.warning(
                    {"error": str(e), "message": "Audio transcription failed, continuing with empty transcript"})
                transcript_dict = {"full_text": "", "segments": []}
        else:
            trace_info.info({"message": "No audio stream detected, skipping transcription"})

        # For videos without audio content, force enable screenshots
        if not has_audio_content and video_path:
            trace_info.info({"message": "No audio content available, forcing screenshot generation"})
            include_screenshots = True

        # 2. Generate notes
        trace_info.info({"message": "Starting note generation"})
        std_chapter = []
        for chapter in chapters:
            chapter['start_time'] = self.seconds_to_hms(int(chapter['start_time']))
            chapter['end_time'] = self.seconds_to_hms(int(chapter['end_time']))
            std_chapter.append(chapter)
            
        markdown = await self._generate_markdown(
            video_info, transcript_dict, std_chapter, style, include_screenshots, include_links, language, trace_info
        )
        trace_info.info({"markdown_length": len(markdown), "message": "Note generation completed"})

        # 3. Process screenshots and thumbnails
        extracted_screenshots = []
        thumbnail_image = None

        # Initialize video processor with temp directory
        video_processor = VideoProcessor(temp_dir)

        if include_screenshots and video_path:
            trace_info.info({"message": "Processing screenshots"})
            markdown, extracted_screenshots = await video_processor.extract_screenshots_as_images(
                markdown, video_path
            )
            trace_info.info({
                "screenshot_count": len(extracted_screenshots),
                "message": "Screenshot processing completed"
            })

        if generate_thumbnail and video_path:
            trace_info.info({"message": "Generating video thumbnail grid"})
            thumbnail_image = await video_processor.create_thumbnail_grid_as_images(
                video_path,
                grid_size=tuple(thumbnail_grid_size),
                frame_interval=thumbnail_interval
            )
            trace_info.info({
                "message": "Thumbnail grid generation completed"
            })

        # 4. Build result
        return VideoNoteResult(
            markdown=remove_continuous_break_lines(markdown),
            transcript=transcript_dict,
            video_info=video_info,
            screenshots=extracted_screenshots,
            thumbnail_image=thumbnail_image
        )

    @tracer.start_as_current_span("process_local_video")
    async def process_local_video(self, file_path: str, **kwargs) -> VideoNoteResult:
        """Process local video file directly"""
        trace_info = kwargs.get("trace_info")
        if not trace_info:
            raise ValueError("trace_info is required")

        trace_info.info({"message": "Processing local video file", "file_path": file_path})

        with tempfile.TemporaryDirectory(prefix="video_local_") as temp_dir:
            # Create video info for local file
            video_name = Path(file_path).stem
            # Initialize video processor with temp directory
            video_processor = VideoProcessor(temp_dir)

            # Get real video duration
            duration = 0
            try:
                duration = await video_processor.get_video_duration(file_path)
            except Exception as e:
                trace_info.warning({"message": f"Failed to get video duration: {str(e)}"})

            video_info = VideoInfo(
                title=video_name,
                duration=duration,
                video_id=video_name,
                platform="local",
                url=f"file://{file_path}",
                description="",
                uploader="",
                upload_date=""
            )
            # Check if video has audio stream and extract if available
            trace_info.info({"message": "Checking for audio stream"})
            audio_path = None
            try:
                if await video_processor.has_audio_stream(file_path):
                    trace_info.info({"message": "Start to extract video audio"})
                    audio_path = await video_processor.extract_audio(file_path, output_format="wav")
                    trace_info.info({"message": "Video audio extraction completed", "audio_path": audio_path})
                else:
                    trace_info.info({"message": "No audio stream detected in video"})
            except Exception as e:
                trace_info.warning({"message": f"Audio extraction failed: {str(e)}. Proceeding without audio."})

            # Use common processing logic
            return await self._process_video_content(
                audio_path=audio_path,
                video_path=file_path,
                video_info=video_info,
                subtitles={},
                chapters=[],
                style=kwargs.get("style", "Concise Style"),
                include_screenshots=kwargs.get("include_screenshots", True),
                include_links=kwargs.get("include_links", False),
                language=kwargs.get("language", "zh"),
                generate_thumbnail=kwargs.get("generate_thumbnail", True),
                thumbnail_grid_size=kwargs.get("thumbnail_grid_size", [3, 3]),
                thumbnail_interval=kwargs.get("thumbnail_interval", 30),
                temp_dir=temp_dir,
                trace_info=trace_info
            )
