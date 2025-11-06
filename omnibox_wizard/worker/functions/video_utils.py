import asyncio
import base64
import io
import json
import logging
import re
import subprocess
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import av
import cv2
import numpy as np
from PIL import Image as PILImage
from opentelemetry import trace

from omnibox_wizard.worker.entity import Image

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("VideoUtils")


@tracer.start_as_current_span("exec_cmd")
async def exec_cmd(cmd: list[str]) -> tuple[int, str, str]:
    span = trace.get_current_span()
    span.set_attribute("command", " ".join(cmd))

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    stdout, stderr = await process.communicate()

    out = stdout.decode('utf-8', errors='ignore')
    err = stderr.decode('utf-8', errors='ignore')

    if process.returncode != 0:
        span.set_attributes({"error": err, "return_code": process.returncode, "stdout": stdout.decode()})
        raise RuntimeError(f"exec cmd failed: {err}, cmd: {' '.join(cmd)}")

    return process.returncode, out, err


class VideoProcessor:
    """Video processing utility class, including screenshot generation and video thumbnail generation"""

    def __init__(self, temp_dir: Optional[str] = None):
        self.temp_dir = Path(temp_dir) if temp_dir else Path.cwd() / "temp_video"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.screenshot_dir = self.temp_dir / "screenshots"
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.frame_dir = self.temp_dir / "frames"
        self.frame_dir.mkdir(parents=True, exist_ok=True)
        self.grid_dir = self.temp_dir / "grids"
        self.grid_dir.mkdir(parents=True, exist_ok=True)

    def check_ffmpeg(self) -> bool:
        """Check if ffmpeg is installed"""
        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("ffmpeg is not installed, screenshot generation will be disabled")
            return False

    async def has_audio_stream(self, video_path: str) -> bool:
        """
        Check if video file has audio stream
        
        Args:
            video_path: Video file path
            
        Returns:
            True if video has audio stream, False otherwise
        """
        if not self.check_ffmpeg():
            logger.warning("ffmpeg is not available, cannot check audio stream")
            return False

        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            str(video_path)
        ]

        try:
            code, stdout, stderr = await exec_cmd(cmd)
            # If there's output, it means audio stream exists
            has_audio = bool(stdout.strip())
            logger.info(f"Video {video_path} has audio stream: {has_audio}")
            return has_audio
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to check audio stream: {e.stderr}")
            return False

    @tracer.start_as_current_span("extract_audio")
    async def extract_audio(self, video_path: str, output_format: str = "wav") -> str:
        """
        Extract audio from video file
        
        Args:
            video_path: Video file path
            output_format: Output audio format (wav, mp3, m4a, etc.)
            
        Returns:
            Extracted audio file path
            
        Raises:
            RuntimeError: If video has no audio stream or extraction fails
        """
        if not self.check_ffmpeg():
            raise RuntimeError("ffmpeg is not installed, cannot extract audio")

        # Check if video has audio stream first
        if not await self.has_audio_stream(video_path):
            raise RuntimeError("Video file has no audio stream")

        video_name = Path(video_path).stem
        audio_filename = f"{video_name}_audio.{output_format}"
        audio_path = str(self.temp_dir / audio_filename)

        # Use ffmpeg to extract audio from video
        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-vn",  # No video stream
            "-acodec", "pcm_s16le" if output_format == "wav" else "libmp3lame",
            "-ar", "16000",  # 16kHz sample rate, suitable for speech recognition
            "-ac", "1",  # Single channel
            "-y",  # Overwrite output file
            audio_path
        ]

        logger.info(f"Extract audio: {' '.join(cmd)}")
        await exec_cmd(cmd)

        if Path(audio_path).exists():
            logger.info(f"Audio extraction successful: {audio_path}")
            return audio_path
        else:
            raise RuntimeError("Audio file not generated")

    @tracer.start_as_current_span("extract_embedded_subtitles")
    async def extract_embedded_subtitles(self, video_path: str) -> dict:
        """
        Extract embedded subtitles from video file

        Uses ffmpeg to extract all subtitle streams from video.
        Returns a dictionary with language codes as keys and subtitle content as values.

        Args:
            video_path: Video file path

        Returns:
            Dictionary of subtitles {language_code: subtitle_text}
            Empty dict if no subtitles found or extraction fails

        Example:
            {"en": "subtitle content...", "zh": "字幕内容..."}
        """
        if not self.check_ffmpeg():
            logger.warning("ffmpeg is not available, cannot extract subtitles")
            return {}

        # Step 1: Detect subtitle streams using ffprobe
        cmd_probe = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            "-select_streams", "s",
            str(video_path)
        ]

        try:
            code, stdout, stderr = await exec_cmd(cmd_probe)
            probe_data = json.loads(stdout) if stdout.strip() else {}
            streams = probe_data.get("streams", [])

            if not streams:
                logger.info(f"No embedded subtitles found in {video_path}")
                return {}

            logger.info(f"Found {len(streams)} subtitle stream(s) in video")

        except Exception as e:
            logger.warning(f"Failed to probe subtitle streams: {str(e)}")
            return {}

        # Step 2: Extract each subtitle stream
        subtitles = {}

        for idx, stream in enumerate(streams):
            stream_index = stream.get("index")
            # Get language from tags (may be 'language', 'lang', or missing)
            tags = stream.get("tags", {})
            language = tags.get("language") or tags.get("lang") or f"subtitle_{idx}"
            codec_name = stream.get("codec_name", "unknown")

            # Determine output format based on codec
            # Common subtitle codecs: srt, ass, ssa, webvtt, mov_text
            if codec_name in ["subrip", "srt"]:
                ext = "srt"
            elif codec_name in ["ass", "ssa"]:
                ext = "ass"
            elif codec_name in ["webvtt"]:
                ext = "vtt"
            else:
                ext = "srt"  # Default to srt, ffmpeg will try to convert

            subtitle_filename = f"subtitle_{idx}_{language}.{ext}"
            subtitle_path = str(self.temp_dir / subtitle_filename)

            # Extract this subtitle stream
            cmd_extract = [
                "ffmpeg",
                "-i", str(video_path),
                "-map", f"0:s:{idx}",  # Select subtitle stream by index
                "-y",  # Overwrite
                subtitle_path
            ]

            try:
                logger.info(f"Extracting subtitle stream {idx} ({language}, {codec_name}) to {subtitle_path}")
                await exec_cmd(cmd_extract)

                # Read subtitle content
                if Path(subtitle_path).exists():
                    with open(subtitle_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read().strip()
                        if content:
                            subtitles[language] = content
                            logger.info(f"Successfully extracted subtitle: {language} ({len(content)} chars)")
                        else:
                            logger.warning(f"Subtitle file is empty: {subtitle_path}")
                else:
                    logger.warning(f"Subtitle file not generated: {subtitle_path}")

            except Exception as e:
                logger.warning(f"Failed to extract subtitle stream {idx}: {str(e)}")
                continue

        logger.info(f"Extracted {len(subtitles)} subtitle(s): {list(subtitles.keys())}")
        return subtitles

    @tracer.start_as_current_span("generate_screenshot")
    async def generate_screenshot(self, video_path: str, timestamp: int, index: int = 0) -> str:
        """
        Generate a single high-quality screenshot

        Args:
            video_path: Video file path
            timestamp: Screenshot timestamp (seconds)
            index: Screenshot index (for naming)

        Returns:
            Screenshot file path
        """
        if not self.check_ffmpeg():
            raise RuntimeError("ffmpeg is not installed, cannot generate screenshot")

        filename = f"screenshot_{index:03d}_{timestamp}s_{uuid.uuid4().hex[:8]}.png"
        output_path = self.screenshot_dir / filename

        cmd = [
            "ffmpeg",
            "-ss", str(timestamp),  # Jump to specified time
            "-i", str(video_path),  # Input file
            "-frames:v", "1",  # Extract only one frame
            "-q:v", "1",  # Highest quality setting (1-31, lower is better)
            str(output_path),
            "-y",  # Overwrite existing file
            "-hide_banner",  # Hide copyright information
            "-loglevel", "error",  # Only show errors
            "-strict", "unofficial"
        ]

        await exec_cmd(cmd)
        return str(output_path)

    def extract_timestamps_from_markdown(self, markdown: str) -> List[Tuple[str, int]]:
        """
        Extract screenshot timestamps from Markdown text

        Supported formats:
        - *Screenshot-hh:mm:ss* or *Screenshot-hh:mm:ss (with or without closing *)
        - *Screenshot-mm:ss* or *Screenshot-mm:ss
        - Screenshot-[hh:mm:ss] or Screenshot-[mm:ss]
        - ![Screenshot](hh:mm:ss) or ![Screenshot](mm:ss)

        Args:
            markdown: Markdown text

        Returns:
            [(original marker, timestamp in seconds), ...]
        """
        results = []

        # Pattern : *Screenshot-hh:mm:ss* or *Screenshot-hh:mm:ss (optional closing *)
        # Also matches mm:ss format
        pattern1 = r"\*Screenshot-(\d{1,2}):(\d{2})(?::(\d{2}))?\*?"
        for match in re.finditer(pattern1, markdown):
            h_or_m = int(match.group(1))
            m_or_s = int(match.group(2))
            ss = match.group(3)

            if ss:  # hh:mm:ss format
                total_seconds = h_or_m * 3600 + m_or_s * 60 + int(ss)
            else:  # mm:ss format
                total_seconds = h_or_m * 60 + m_or_s

            results.append((match.group(0), total_seconds))

        # Remove duplicates and sort by timestamp
        results = list(set(results))
        results.sort(key=lambda x: x[1])

        return results

    @classmethod
    async def get_video_duration(cls, video_path: str) -> float:
        """Get video duration (seconds)"""
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path)
        ]

        try:
            code, stdout, stderr = await exec_cmd(cmd)
            return float(stdout.strip())
        except (subprocess.CalledProcessError, ValueError) as e:
            logger.error(f"Get video duration failed: {e}")
            return 0.0

    @classmethod
    async def get_video_resolution(cls, video_path: str) -> Tuple[int, int]:
        """
        Get video resolution (width, height)

        Args:
            video_path: Video file path

        Returns:
            Tuple of (width, height), or (1920, 1080) as default if failed
        """
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0",
            str(video_path)
        ]

        try:
            code, stdout, stderr = await exec_cmd(cmd)
            width, height = map(int, stdout.strip().split(','))
            return width, height
        except (subprocess.CalledProcessError, ValueError) as e:
            logger.error(f"Get video resolution failed: {e}, using default 1920x1080")
            return 1920, 1080

    @tracer.start_as_current_span('get_screenshot_image')
    async def get_screenshot_image(self, video_path: str, timestamp: int, idx: int,
                                   semaphore: asyncio.Semaphore) -> Image | None:
        span = trace.get_current_span()
        async with semaphore:
            try:
                # Generate screenshot
                screenshot_path = await self.generate_screenshot(video_path, timestamp, idx)

                # Read screenshot file and convert to base64
                with open(screenshot_path, 'rb') as f:
                    image_data = base64.b64encode(f.read()).decode('utf-8')

                # Create Image object
                filename = Path(screenshot_path).name
                return Image(
                    name=filename,
                    link=filename,
                    data=image_data,
                    mimetype="image/jpeg"
                )
            except Exception as e:
                span.record_exception(e)
                return None

    @tracer.start_as_current_span("extract_frames_batch")
    async def extract_frames_batch(
            self,
            video_path: str,
            timestamps: List[float]
    ) -> Dict[float, np.ndarray]:
        span = trace.get_current_span()

        span.set_attribute("timestamps_cnt", len(timestamps))
        if not timestamps:
            return {}

        frames_dict = {}
        cap = cv2.VideoCapture(video_path)

        if not cap.isOpened():
            span.set_attribute(
                "fail_reason", f"Failed to open video: {video_path}, pyav not installed, {cv2.getBuildInformation()}"
            )
            try:
                logger.info(f"Using PyAV to extract {len(timestamps)} frames from {video_path}")
                frames_dict = await self.extract_frames_batch_pyav(video_path, timestamps)
                if frames_dict:
                    return frames_dict
                logger.warning("PyAV extraction returned empty, falling back to OpenCV")
            except Exception as e:
                logger.warning(f"PyAV extraction failed: {e}, falling back to OpenCV")
                span.set_attribute("pyav_error", str(e))
            return frames_dict

        try:
            fps = cap.get(cv2.CAP_PROP_FPS)
            if fps <= 0:
                logger.warning(f"Invalid FPS: {fps}, using default 30")
                fps = 30

            logger.info(f"Video FPS: {fps}")

            current_pos = 0.0

            for timestamp in timestamps:
                target_frame_number = int(timestamp * fps)

                if timestamp < current_pos:
                    logger.warning(f"Timestamp {timestamp} is before current position {current_pos}, seeking...")
                    cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame_number)
                else:
                    frames_to_skip = target_frame_number - int(current_pos * fps)

                    if frames_to_skip > fps * 2:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame_number)
                    else:
                        for _ in range(frames_to_skip):
                            cap.grab()

                ret, frame = cap.read()

                if ret and frame is not None:
                    frames_dict[timestamp] = frame.copy()
                    current_pos = timestamp
                    logger.debug(f"Extracted frame at {timestamp}s")
                else:
                    logger.warning(f"Failed to read frame at {timestamp}s")
                    ret, frame = cap.read()
                    if ret and frame is not None:
                        frames_dict[timestamp] = frame.copy()
                        logger.debug(f"Used next frame for {timestamp}s")
        except Exception as e:
            span.set_attributes({"error_msg": f"{e}"})
        finally:
            cap.release()

        return frames_dict

    @tracer.start_as_current_span("extract_frames_batch_pyav")
    async def extract_frames_batch_pyav(
            self,
            video_path: str,
            timestamps: List[float]
    ) -> Dict[float, np.ndarray]:
        span = trace.get_current_span()

        if not timestamps:
            return {}

        sorted_timestamps = sorted(set(timestamps))

        try:
            loop = asyncio.get_event_loop()
            frames_dict = await loop.run_in_executor(
                None,
                self._extract_frames_pyav_sync,
                video_path,
                sorted_timestamps
            )

            logger.info(f"PyAV extracted {len(frames_dict)}/{len(sorted_timestamps)} frames")
            span.set_attribute("extracted_frames", len(frames_dict))
            return frames_dict

        except Exception as e:
            logger.error(f"PyAV extraction failed: {e}")
            span.record_exception(e)
            raise

    def _extract_frames_pyav_sync(
            self,
            video_path: str,
            timestamps: List[float]
    ) -> Dict[float, np.ndarray]:
        frames_dict = {}
        used_frame_times = set()  # Track actual frame times to avoid duplicates

        try:
            container = av.open(video_path)
            video_stream = container.streams.video[0]
            video_stream.thread_type = 'NONE'
            time_base = float(video_stream.time_base)

            sorted_timestamps = sorted(timestamps)

            for i, timestamp in enumerate(sorted_timestamps):
                try:
                    # Each chapter has 4 timestamps (0%, 33%, 66%, 90%)
                    # Seek at the beginning of each chapter (every 4 timestamps)
                    should_seek = (i % 4 == 0)

                    if should_seek:
                        seek_target = int(timestamp / time_base)
                        container.seek(seek_target, backward=True, any_frame=False, stream=video_stream)
                        video_stream.codec_context.flush_buffers()
                        logger.debug(f"Seeking to {timestamp}s (chapter {i // 4 + 1} start)")

                    best_frame_data = None
                    best_diff = float('inf')
                    best_frame_time = None
                    max_search_frames = 50  # Limit search to avoid infinite loops

                    for frame_idx, frame in enumerate(container.decode(video_stream)):
                        if frame_idx >= max_search_frames:
                            break

                        if frame.pts is None:
                            continue
                        frame_time = float(frame.pts * time_base)

                        # Skip if we've already used this exact frame for another timestamp
                        is_duplicate = any(abs(frame_time - used_time) < 0.01 for used_time in used_frame_times)

                        if not is_duplicate:
                            time_diff = abs(frame_time - timestamp)

                            if time_diff < best_diff:
                                best_diff = time_diff
                                best_frame_data = frame.to_ndarray(format='bgr24').copy()
                                best_frame_time = frame_time

                        # Stop searching once we've passed the target timestamp significantly
                        # But continue if we haven't found a non-duplicate frame yet
                        if frame_time > timestamp + 1.0 and best_frame_data is not None:
                            break

                    if best_frame_data is not None:
                        frames_dict[timestamp] = best_frame_data
                        used_frame_times.add(best_frame_time)
                        logger.debug(
                            f"PyAV extracted frame at {timestamp}s (actual: {best_frame_time:.3f}s, diff: {best_diff:.3f}s)")
                    else:
                        logger.warning(f"No suitable frame found for timestamp {timestamp}s")

                except Exception as e:
                    logger.warning(f"Failed to extract frame at {timestamp}s with PyAV: {e}")
                    continue

            container.close()

        except Exception as e:
            logger.error(f"PyAV container error: {e}")
            raise

        return frames_dict

    @tracer.start_as_current_span("create_chapter_grid")
    async def create_chapter_grid(
            self,
            video_path: str,
            chapter: dict,
            chapter_idx: int,
            max_unit_size: int = 960,
            video_resolution: Tuple[int, int] = None,
            preloaded_frames: Dict[float, np.ndarray] = None,
            timestamps: List[float] = None
    ) -> Image | None:
        """
        Create a 2x2 grid image for a chapter (first frame + 3 keyframes)
        Automatically adjusts cell size based on video aspect ratio
        Uses high-quality settings for sharp images

        Args:
            video_path: Video file path
            chapter: Chapter dict with start_time, end_time, title, description
            chapter_idx: Chapter index (for naming)
            max_unit_size: Maximum size for the longer dimension of each cell (default: 960 for Full HD)
            video_resolution: Optional pre-fetched video resolution (width, height) to avoid repeated ffprobe calls
            preloaded_frames: Optional dict of pre-extracted frames (timestamp -> numpy array), for performance optimization

        Returns:
            Image object with the 2x2 grid
        """
        # Get video resolution to determine aspect ratio
        if video_resolution:
            video_width, video_height = video_resolution
        else:
            video_width, video_height = await self.get_video_resolution(video_path)
        aspect_ratio = video_width / video_height

        # Calculate unit dimensions based on aspect ratio
        # Use very high resolution for crystal clear images
        if aspect_ratio >= 1:  # Landscape or square (e.g., 16:9, 4:3)
            unit_width = max_unit_size
            unit_height = int(max_unit_size / aspect_ratio)
        else:  # Portrait (e.g., 9:16)
            unit_width = int(max_unit_size * aspect_ratio)
            unit_height = max_unit_size

        logger.info(f"Video aspect ratio: {aspect_ratio:.2f} ({video_width}x{video_height}), "
                    f"using cell size: {unit_width}x{unit_height}, "
                    f"grid size: {unit_width * 2}x{unit_height * 2}")

        all_frames = []
        output_dir = self.frame_dir

        # Use preloaded frames if available, otherwise extract with ffmpeg
        if preloaded_frames is not None:
            logger.info(f"Using preloaded frames for chapter {chapter_idx}")

            for i, timestamp in enumerate(timestamps):
                output_path = output_dir / f"chapter_{chapter_idx}_frame_{i + 1:03d}.png"

                # Find the closest matching timestamp in preloaded frames
                if timestamp in preloaded_frames:
                    frame = preloaded_frames[timestamp]
                else:
                    # Find closest timestamp
                    closest_ts = min(preloaded_frames.keys(), key=lambda _: abs(_ - timestamp))
                    frame = preloaded_frames[closest_ts]
                    logger.debug(f"Using closest frame at {closest_ts}s for target {timestamp}s")

                # Convert BGR (OpenCV) to RGB (PIL) and save
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil_img = PILImage.fromarray(frame_rgb)
                pil_img.save(str(output_path), quality=95)
                all_frames.append(str(output_path))

        else:
            # Fallback to ffmpeg extraction
            logger.info(f"Using ffmpeg extraction for chapter {chapter_idx}")

            for i, timestamp in enumerate(timestamps):
                output_path = output_dir / f"chapter_{chapter_idx}_frame_{i + 1:03d}.png"

                cmd = [
                    "ffmpeg",
                    "-ss", str(timestamp),
                    "-i", str(video_path),
                    "-frames:v", "1",
                    "-q:v", "3",
                    str(output_path),
                    "-y",
                    "-hide_banner",
                    "-loglevel", "error"
                ]
                try:
                    await exec_cmd(cmd)
                    all_frames.append(str(output_path))
                except Exception as e:
                    logger.warning(f"Failed to extract frames for chapter {chapter_idx}: {e}")
                    return None

        if len(all_frames) < 4:
            # Pad with duplicates if needed
            while len(all_frames) < 4:
                all_frames.append(all_frames[-1])

        # Create 2x2 grid
        cols, rows = 2, 2
        grid_img = PILImage.new("RGB", (unit_width * cols, unit_height * rows), (0, 0, 0))

        for idx, frame_path in enumerate(all_frames[:4]):
            if not Path(frame_path).exists():
                continue

            # Open and resize image while maintaining aspect ratio
            img = PILImage.open(frame_path).convert("RGB")

            # Calculate target size to fill the cell while maintaining aspect ratio
            img_aspect = img.width / img.height
            cell_aspect = unit_width / unit_height

            if img_aspect > cell_aspect:
                # Image is wider, scale by height
                new_height = unit_height
                new_width = int(unit_height * img_aspect)
            else:
                # Image is taller, scale by width
                new_width = unit_width
                new_height = int(unit_width / img_aspect)

            # Use LANCZOS for highest quality downsampling
            img = img.resize((new_width, new_height), PILImage.Resampling.LANCZOS)

            # Crop to exact cell size (center crop)
            if new_width > unit_width or new_height > unit_height:
                left = (new_width - unit_width) // 2
                top = (new_height - unit_height) // 2
                right = left + unit_width
                bottom = top + unit_height
                img = img.crop((left, top, right, bottom))

            # Place directly in grid (no black background needed after cropping)
            x = (idx % cols) * unit_width
            y = (idx // cols) * unit_height
            grid_img.paste(img, (x, y))

        # Save to memory buffer with highest quality
        buffer = io.BytesIO()
        # Use PNG for lossless quality (better clarity but larger file size)
        # Compress level 6 is a good balance between quality and file size
        grid_img.save(buffer, format='PNG', optimize=True, compress_level=6)
        buffer.seek(0)

        # Convert to base64
        image_data = base64.b64encode(buffer.read()).decode('utf-8')

        # Create Image object
        chapter_title = chapter.get('title', f'Chapter {chapter_idx + 1}')
        filename = f"chapter_{chapter_idx}_{uuid.uuid4().hex[:8]}.png"

        chapter_image = Image(
            name=filename,
            link=filename,
            data=image_data,
            mimetype="image/png"
        )

        logger.info(f"Created 2x2 grid for chapter {chapter_idx}: {chapter_title}, "
                    f"final size: {unit_width * 2}x{unit_height * 2}")
        return chapter_image

    @tracer.start_as_current_span("generate_chapter_screenshots")
    async def generate_chapter_screenshots(
            self,
            video_path: str,
            chapters: List[dict],
            markdown: str
    ) -> tuple[str, list]:
        """
        Generate screenshot grids for each chapter and insert into markdown

        Args:
            video_path: Video file path
            chapters: List of chapter dicts with start_time, end_time, title, description
            markdown: Original markdown content with *Chapter-{index}* markers

        Returns:
            (processed markdown, Image object list)
        """
        span = trace.get_current_span()

        if not self.check_ffmpeg():
            logger.warning("ffmpeg is not installed, skipping chapter screenshots")
            return markdown, []

        if not chapters:
            logger.info("No chapters provided, skipping chapter screenshots")
            return markdown, []

        span.set_attribute("chapter_count", len(chapters))

        # Get video resolution once for all chapters
        video_resolution = await self.get_video_resolution(video_path)
        logger.info(f"Video resolution: {video_resolution[0]}x{video_resolution[1]}")

        # Collect all timestamps needed for all chapters (optimized batch extraction)
        all_timestamps = []
        for chapter in chapters:
            start_time = int(chapter['start_time'])
            end_time = int(chapter['end_time'])
            duration = end_time - start_time

            # Calculate the 4 timestamps for each chapter
            chapter_timestamps = [
                start_time,  # First frame (0%)
                start_time + duration * 0.33,  # Second frame (33%)
                start_time + duration * 0.66,  # Third frame (66%)
                start_time + duration * 0.90  # Fourth frame (90%)
            ]
            all_timestamps.extend(chapter_timestamps)

        all_timestamps = list(sorted(set(all_timestamps)))

        preloaded_frames = await self.extract_frames_batch(video_path, all_timestamps)

        if not preloaded_frames:
            logger.warning("Failed to extract frames with OpenCV, falling back to ffmpeg")
            preloaded_frames = None

        screenshots = []
        processed_markdown = markdown

        # Generate grids for each chapter concurrently
        tasks = []
        for idx, chapter in enumerate(chapters):
            tasks.append(self.create_chapter_grid(
                video_path, chapter, idx,
                video_resolution=video_resolution,
                preloaded_frames=preloaded_frames,
                timestamps=all_timestamps[idx * 4: idx * 4 + 4]
            ))

        # Wait for all grids to be generated
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Replace chapter markers with actual screenshots
        for idx, (chapter, result) in enumerate(zip(chapters, results)):
            if isinstance(result, Exception):
                logger.error(f"Failed to create grid for chapter {idx}: {result}")
                # Remove the marker if screenshot generation failed
                marker = f"*Chapter-{idx}*"
                processed_markdown = processed_markdown.replace(marker, "", 1)
                continue

            if result:
                screenshots.append(result)

                # Create markdown image with chapter info
                chapter_desc = chapter.get('description', '')

                # Format image markdown with optional description
                if chapter_desc:
                    img_markdown = f"![]({result.link})\n*{chapter_desc}*\n"
                else:
                    img_markdown = f"![]({result.link})\n"

                # Replace the chapter marker with the image
                marker = f"*Chapter-{idx}*"
                if marker in processed_markdown:
                    processed_markdown = processed_markdown.replace(marker, img_markdown, 1)
                    logger.debug(f"Replaced marker '{marker}' with screenshot")
                else:
                    # If marker not found, try to append at the end as fallback
                    logger.warning(f"Chapter marker '{marker}' not found in markdown, appending at end")
                    processed_markdown += f"\n\n{img_markdown}"

        span.set_attribute("processed_markdown", processed_markdown)
        logger.info(f"Generated {len(screenshots)} chapter screenshot grids")
        return processed_markdown, screenshots

    @tracer.start_as_current_span("extract_screenshots_as_images")
    async def extract_screenshots_as_images(
            self,
            markdown: str,
            video_path: str
    ) -> tuple[str, list]:
        """
        Extract screenshot markers from Markdown and generate actual screenshots, returning Image object list

        Args:
            markdown: Markdown text containing screenshot markers
            video_path: Video file path

        Returns:
            (processed markdown, Image object list)
        """
        span = trace.get_current_span()

        if not self.check_ffmpeg():
            logger.warning("ffmpeg is not installed, skipping screenshot generation")
            return markdown, []

        timestamps = self.extract_timestamps_from_markdown(markdown)

        if not timestamps:
            logger.info("No screenshot markers found")
            return markdown, []

        span.set_attribute("screenshots_cnt", len(timestamps))

        screenshots = []
        processed_markdown = markdown

        tasks: list[asyncio.Task[Image | None]] = []

        semaphore = asyncio.Semaphore(2)

        for idx, (marker, timestamp) in enumerate(timestamps):
            tasks.append(asyncio.create_task(self.get_screenshot_image(video_path, timestamp, idx, semaphore)))

        for (marker, timestamp), task in zip(timestamps, tasks):
            if image := await task:
                screenshots.append(image)
                # time_display = f"{timestamp//60}:{timestamp%60:02d}"
                # img_markdown = f"{time_display}\n\n{filename}"
                img_markdown = f"\n![]({image.link})\n"
                processed_markdown = processed_markdown.replace(marker, img_markdown, 1)
            else:
                processed_markdown = processed_markdown.replace(marker, '', 1)

        return processed_markdown, screenshots

    def cleanup(self):
        """Clean up temporary files"""
        import shutil
        try:
            if self.temp_dir.exists():
                shutil.rmtree(self.temp_dir)
                logger.info(f"Clean up temporary directory: {self.temp_dir}")
        except Exception as e:
            logger.warning(f"Clean up temporary files failed: {e}")
