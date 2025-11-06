import json as jsonlib
import mimetypes
import re
import tempfile
from pathlib import Path
from typing import List, Dict, Any

from opentelemetry import propagate, trace

from omnibox_wizard.common import project_root
from omnibox_wizard.common.template_parser import TemplateParser
from omnibox_wizard.common.trace_info import TraceInfo
from omnibox_wizard.common.utils import remove_continuous_break_lines
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.entity import Task, Image
from omnibox_wizard.worker.functions.base_function import BaseFunction
from omnibox_wizard.worker.functions.file_readers.audio_reader import ASRClient
from omnibox_wizard.worker.functions.subtitle_aligner import SubtitleAligner
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
            file_upload_config=config.task.file_uploader,
            base_url=config.task.asr.base_url,
            headers={"Authorization": f"Bearer {config.task.asr.api_key}"},
        )

        # Initialize template parser
        prompts_dir = project_root.path("omnibox_wizard/resources/prompts")
        self.template_parser = TemplateParser(str(prompts_dir))

        # Base64 image pattern, consistent with office_reader.py
        self.base64_img_pattern = re.compile(r"data:image/[^;]+;base64,([^\"')}]+)")

        self.language_map = {"简体中文": ["zh", "ai-zh"], "English": ["en", "eng", "ai-en"]}

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

    @staticmethod
    def hms_to_seconds(time_str: str) -> int:
        """
        Convert time string (HH:MM:SS or MM:SS) to seconds

        Args:
            time_str: Time string in format "HH:MM:SS" or "MM:SS"

        Returns:
            Total seconds as integer
        """
        parts = time_str.strip().split(':')
        if len(parts) == 3:  # HH:MM:SS
            hours, minutes, seconds = map(int, parts)
            return hours * 3600 + minutes * 60 + seconds
        elif len(parts) == 2:  # MM:SS
            minutes, seconds = map(int, parts)
            return minutes * 60 + seconds
        else:
            raise ValueError(f"Invalid time format: {time_str}")

    def _extract_chapters_from_markdown(self, markdown: str, trace_info: TraceInfo) -> tuple[str, list[dict]]:
        """
        Extract chapters information from markdown content if present

        Args:
            markdown: The markdown content that may contain chapters
            trace_info: Trace information for logging

        Returns:
            Tuple of (cleaned_markdown, extracted_chapters)
            - cleaned_markdown: Markdown with chapters section removed
            - extracted_chapters: List of chapter dicts with start_time (seconds), end_time (seconds), title, description
        """
        # Pattern to match chapters between markers
        pattern = r'===BEGIN_CHAPTERS===\s*(.*?)\s*===END_CHAPTERS==='
        match = re.search(pattern, markdown, re.DOTALL)

        if not match:
            return markdown, []

        try:
            chapters_json = match.group(1).strip()
            chapters_data = jsonlib.loads(chapters_json)

            # Convert time strings to seconds
            extracted_chapters = []
            for chapter in chapters_data:
                start_seconds = self.hms_to_seconds(chapter['start_time'])
                end_seconds = self.hms_to_seconds(chapter['end_time'])
                extracted_chapters.append({
                    'title': chapter['title'],
                    'start_time': start_seconds,
                    'end_time': end_seconds,
                    'description': chapter.get('description', '')
                })

            # Remove the chapters section from markdown
            cleaned_markdown = re.sub(pattern, '', markdown, flags=re.DOTALL).strip()
            trace_info.debug({
                "extracted_chapters_count": len(extracted_chapters),
                "message": "Successfully extracted chapters from AI response"
            })

            return cleaned_markdown, extracted_chapters

        except Exception as e:
            trace_info.warning({
                "error": str(e),
                "message": "Failed to extract chapters from markdown, proceeding without chapters"
            })
            return markdown, []

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

        candidates = self.language_map.get(language, "zh")
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

        cookies = input_dict.get('cookies', None)

        span.set_attribute("config", jsonlib.dumps({
            "style": style,
            "include_screenshots": include_screenshots,
            "include_links": include_links,
            "language": language,
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
                download_result = await downloader.download(
                    video_url, temp_dir, download_video=include_screenshots, cookies=cookies)
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
    async def _transcribe_audio(
            self, audio_path: str, trace_info: TraceInfo, return_structured: bool = False) -> Dict[str, Any]:
        """
        Transcribe audio using ASR service

        Args:
            audio_path: Path to audio file
            trace_info: Trace information
            return_structured: If True, return structured ASR data; if False, return formatted text

        Returns:
            Dict with 'full_text' and optionally 'sentences' (if return_structured=True)
        """
        try:
            mimetype, _ = mimetypes.guess_type(audio_path)
            result = await self.asr_client.transcribe(file_path=audio_path, return_structured=return_structured)

            if return_structured and isinstance(result, dict):
                # Result is structured data with sentences
                sentences = result.get("sentences", [])
                full_text = ASRClient.convert_sentences_to_text(sentences)
                return {
                    "full_text": full_text,
                    "sentences": sentences
                }
            else:
                # Result is formatted text string (legacy mode, not used anymore)
                return {
                    "full_text": result if isinstance(result, str) else "",
                    "sentences": []
                }

        except Exception as e:
            trace_info.error({"error": str(e), "message": "Fail to transcribe audio"})
            raise

    @tracer.start_as_current_span('_generate_fallback_markdown')
    def _generate_fallback_markdown(
            self,
            video_info: VideoInfo,
            include_screenshots: bool,
            *_, **__
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
    ) -> tuple[str, list[dict]]:
        """
        Generate markdown notes from video content

        Returns:
            Tuple of (markdown, extracted_chapters)
            - markdown: The generated markdown content
            - extracted_chapters: List of chapters extracted from AI response (empty if chapters were provided or not extracted)
        """
        # Check if we have transcript content
        transcript_text = transcript.get('full_text', '').strip()

        if not transcript_text:
            # No audio content, use fallback template without LLM call
            trace_info.debug({"message": "No transcript available, generating fallback markdown without LLM"})
            fallback_markdown = self._generate_fallback_markdown(
                video_info, include_screenshots, include_links, language
            )
            return fallback_markdown, []

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

            # Extract chapters from response if no chapters were provided
            if not chapters:
                markdown, extracted_chapters = self._extract_chapters_from_markdown(response, trace_info)
                return markdown, extracted_chapters
            else:
                return response, []

        except Exception as e:
            trace_info.error({"error": str(e), "message": "Fail to generate AI note"})
            raise

    @tracer.start_as_current_span('_call_ai_for_summary')
    async def _call_ai_for_summary(self, prompt: str, trace_info: TraceInfo) -> str:
        """Call AI to generate summary"""
        openai_client = self.config.grimoire.openai.get_config("default")

        headers = {}
        propagate.inject(headers)

        if trace_info:
            headers = headers | {"X-Request-Id": trace_info.request_id}

        response = await openai_client.chat(
            messages=[
                {"role": "user", "content": prompt}
            ],
            extra_headers=headers if headers else None
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
            temp_dir: str,
            trace_info: TraceInfo
    ) -> VideoNoteResult:
        """Common video processing logic used by both URL and local file processing"""

        # 1. Audio transcription with subtitle alignment
        # New logic: Always run ASR for speaker diarization info when audio is available
        transcript_dict = {"full_text": "", "sentences": []}
        has_audio_content = False
        span = trace.get_current_span()

        if audio_path:
            # Always run ASR transcription to get speaker diarization info
            trace_info.debug({"message": "Starting ASR transcription for speaker diarization"})
            try:
                asr_result = await self._transcribe_audio(audio_path, trace_info, return_structured=True)
                asr_sentences = asr_result.get("sentences", [])

                # Check if we have subtitles to align with ASR
                subtitle_text = self._get_best_subtitle(subtitles, language) if subtitles else ""

                if subtitle_text and asr_sentences:
                    # We have both subtitles and ASR results - align them
                    trace_info.debug({
                        "subtitle_length": len(subtitle_text),
                        "asr_sentence_count": len(asr_sentences),
                        "message": "Aligning subtitles with ASR results"
                    })

                    aligned_result = SubtitleAligner.align_subtitles_with_asr(subtitle_text, asr_sentences)
                    aligned_sentences = aligned_result.get("sentences", [])

                    # Format aligned sentences into full text
                    full_text = ASRClient.convert_sentences_to_text(aligned_sentences)

                    transcript_dict = {
                        "full_text": full_text,
                        "sentences": aligned_sentences
                    }

                    trace_info.debug({
                        "aligned_sentence_count": len(aligned_sentences),
                        "message": "Subtitle alignment completed"
                    })
                elif asr_sentences:
                    # Only ASR results available (no subtitles)
                    transcript_dict = asr_result
                    trace_info.debug({
                        "asr_sentence_count": len(asr_sentences),
                        "message": "Using ASR transcription (no subtitles available)"
                    })
                else:
                    # ASR returned no results
                    trace_info.warning({"message": "ASR transcription returned no results"})

                has_audio_content = bool(transcript_dict.get("full_text", "").strip())
                trace_info.debug({
                    "transcript_length": len(transcript_dict.get("full_text", "")),
                    "message": "Audio transcription and alignment completed"
                })

            except Exception as e:
                trace_info.warning({
                    "error": str(e),
                    "message": "ASR transcription failed, falling back to subtitles only"
                })

                # Fallback to using raw subtitles if ASR fails
                subtitle_text = self._get_best_subtitle(subtitles, language) if subtitles else ""
                if subtitle_text:
                    # Split subtitle into sentences to maintain consistent data structure
                    # This ensures downstream code can rely on 'sentences' field
                    subtitle_lines = [line.strip() for line in subtitle_text.split('\n') if line.strip()]
                    sentences = [
                        {
                            "text": line,
                            "begin_time": 0,
                            "end_time": 0,
                            "speaker_id": 0,
                            "words": []
                        }
                        for line in subtitle_lines
                    ]
                    transcript_dict = {
                        "full_text": subtitle_text,
                        "sentences": sentences
                    }
                    has_audio_content = True
                    trace_info.debug({
                        "subtitle_length": len(subtitle_text),
                        "subtitle_sentence_count": len(sentences),
                        "message": "Using subtitle as fallback transcript (split into sentences)"
                    })
                else:
                    transcript_dict = {"full_text": "", "sentences": []}
        else:
            trace_info.debug({"message": "No audio stream detected, skipping transcription"})

        # For videos without audio content, force enable screenshots
        if not has_audio_content and video_path:
            trace_info.debug({"message": "No audio content available, forcing screenshot generation"})
            include_screenshots = True

        # 2. Generate notes
        trace_info.debug({"message": "Starting note generation"})
        std_chapter = []
        for chapter in chapters:
            chapter['start_time'] = int(chapter['start_time'])
            chapter['end_time'] = int(chapter['end_time'])
            std_chapter.append(chapter)

        span.set_attribute("transcript_dict", transcript_dict)

        markdown, extracted_chapters = await self._generate_markdown(
            video_info, transcript_dict, std_chapter, style, include_screenshots, include_links, language, trace_info
        )
        span.set_attribute("generated markdown", markdown)
        # Use extracted chapters if original chapters were empty
        if not chapters and extracted_chapters:
            trace_info.debug({
                "extracted_chapters_count": len(extracted_chapters),
                "message": "Using AI-generated chapters for screenshot extraction"
            })
            chapters = extracted_chapters

        trace_info.debug({"markdown_length": len(markdown), "message": "Note generation completed"})

        # 3. Process screenshots and thumbnails
        extracted_screenshots = []
        thumbnail_image = None

        # Initialize video processor with temp directory
        video_processor = VideoProcessor(temp_dir)

        if include_screenshots and video_path:
            trace_info.debug({"message": "Processing screenshots"})

            # New logic: Generate chapter-based screenshots if chapters are available
            if chapters:
                trace_info.debug({
                    "chapter_count": len(chapters),
                    "message": "Generating chapter-based screenshots (2x2 grids)"
                })
                markdown, extracted_screenshots = await video_processor.generate_chapter_screenshots(
                    video_path, chapters, markdown
                )
                span.set_attribute("processed_markdown", markdown)
            else:
                # Fallback to old logic: Extract screenshots from markdown markers
                trace_info.debug({"message": "Generating screenshots from markdown markers"})
                markdown, extracted_screenshots = await video_processor.extract_screenshots_as_images(
                    markdown, video_path
                )
                span.set_attribute("processed_markdown_2", markdown)

            trace_info.debug({
                "screenshot_count": len(extracted_screenshots),
                "message": "Screenshot processing completed"
            })

        markdown = remove_continuous_break_lines(markdown)
        # 4. Build result
        return VideoNoteResult(
            markdown=re.sub(r'^(?:```\n?|\n)+|(?:\n?```|\n)+$', '', markdown),
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

        trace_info.debug({"message": "Processing local video file", "file_path": file_path})

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
            trace_info.debug({"message": "Checking for audio stream"})
            audio_path = None
            try:
                if await video_processor.has_audio_stream(file_path):
                    trace_info.debug({"message": "Start to extract video audio"})
                    audio_path = await video_processor.extract_audio(file_path, output_format="wav")
                    trace_info.debug({"message": "Video audio extraction completed", "audio_path": audio_path})
                else:
                    trace_info.debug({"message": "No audio stream detected in video"})
            except Exception as e:
                trace_info.warning({"message": f"Audio extraction failed: {str(e)}. Proceeding without audio."})

            # Extract embedded subtitles from video
            trace_info.debug({"message": "Extracting embedded subtitles"})
            subtitles = {}
            try:
                subtitles = await video_processor.extract_embedded_subtitles(file_path)
                if subtitles:
                    trace_info.debug({
                        "subtitle_count": len(subtitles),
                        "subtitle_languages": list(subtitles.keys()),
                        "message": "Embedded subtitles extracted successfully"
                    })
                else:
                    trace_info.debug({"message": "No embedded subtitles found in video"})
            except Exception as e:
                trace_info.warning({"message": f"Subtitle extraction failed: {str(e)}. Proceeding without subtitles."})

            # Use common processing logic
            return await self._process_video_content(
                audio_path=audio_path,
                video_path=file_path,
                video_info=video_info,
                subtitles=subtitles,
                chapters=[],
                style=kwargs.get("style", "Concise Style"),
                include_screenshots=kwargs.get("include_screenshots", True),
                include_links=kwargs.get("include_links", False),
                language=kwargs.get("language", "zh"),
                temp_dir=temp_dir,
                trace_info=trace_info
            )
