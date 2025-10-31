import asyncio
import base64
import io
import logging
import re
import subprocess
import uuid
from pathlib import Path
from typing import List, Optional, Tuple
from PIL import Image as PILImage, ImageDraw, ImageFont
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

    @tracer.start_as_current_span("generate_screenshot")
    async def generate_screenshot(self, video_path: str, timestamp: int, index: int = 0) -> str:
        """
        Generate a single screenshot
        
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
            "-q:v", "2",  # Quality setting (1-31, lower quality is better)
            str(output_path),
            "-y",  # Overwrite existing file
            "-hide_banner",  # Hide copyright information
            "-loglevel", "error",  # Only show errors
            "-strict","unofficial"

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

    @tracer.start_as_current_span("extract_keyframes")
    async def extract_keyframes(
            self,
            video_path: str,
            start_time: int,
            end_time: int,
            num_frames: int = 3
    ) -> List[str]:
        """
        Extract keyframes from video segment using ffmpeg thumbnail filter

        Args:
            video_path: Video file path
            start_time: Segment start time (seconds)
            end_time: Segment end time (seconds)
            num_frames: Number of keyframes to extract (default: 3)

        Returns:
            List of extracted frame paths
        """
        if not self.check_ffmpeg():
            logger.warning("ffmpeg is not installed, skipping keyframe extraction")
            return []

        duration = end_time - start_time
        if duration <= 0:
            logger.warning(f"Invalid segment duration: {duration}")
            return []

        frame_paths = []

        # Calculate interval to get evenly distributed frames
        interval = max(1, duration / (num_frames + 1))

        for i in range(num_frames):
            timestamp = start_time + (i + 1) * interval
            if timestamp >= end_time:
                timestamp = end_time - 1

            output_path = self.frame_dir / f"keyframe_{start_time}_{i}_{uuid.uuid4().hex[:8]}.jpg"

            cmd = [
                "ffmpeg",
                "-ss", str(timestamp),
                "-i", str(video_path),
                "-frames:v", "1",
                "-q:v", "2",
                str(output_path),
                "-y",
                "-hide_banner",
                "-loglevel", "error"
            ]

            try:
                await exec_cmd(cmd)
                frame_paths.append(str(output_path))
                logger.debug(f"Extracted keyframe at {timestamp}s: {output_path}")
            except Exception as e:
                logger.warning(f"Failed to extract keyframe at {timestamp}s: {e}")

        return frame_paths

    @tracer.start_as_current_span("create_chapter_grid")
    async def create_chapter_grid(
            self,
            video_path: str,
            chapter: dict,
            chapter_idx: int,
            max_unit_size: int = 320
    ) -> Image | None:
        """
        Create a 2x2 grid image for a chapter (first frame + 3 keyframes)
        Automatically adjusts cell size based on video aspect ratio

        Args:
            video_path: Video file path
            chapter: Chapter dict with start_time, end_time, title, description
            chapter_idx: Chapter index (for naming)
            max_unit_size: Maximum size for the longer dimension of each cell (default: 320)

        Returns:
            Image object with the 2x2 grid
        """
        start_time = int(chapter['start_time'])
        end_time = int(chapter['end_time'])

        # Get video resolution to determine aspect ratio
        video_width, video_height = await self.get_video_resolution(video_path)
        aspect_ratio = video_width / video_height

        # Calculate unit dimensions based on aspect ratio
        if aspect_ratio >= 1:  # Landscape or square (e.g., 16:9, 4:3)
            unit_width = max_unit_size
            unit_height = int(max_unit_size / aspect_ratio)
        else:  # Portrait (e.g., 9:16)
            unit_width = int(max_unit_size * aspect_ratio)
            unit_height = max_unit_size

        logger.info(f"Video aspect ratio: {aspect_ratio:.2f} ({video_width}x{video_height}), "
                   f"using cell size: {unit_width}x{unit_height}")

        # Generate first frame (chapter start)
        first_frame_path = await self.generate_screenshot(video_path, start_time, chapter_idx * 10)

        # Extract 3 keyframes from the chapter
        keyframe_paths = await self.extract_keyframes(video_path, start_time, end_time, num_frames=3)

        # Combine all frames
        all_frames = [first_frame_path] + keyframe_paths

        if len(all_frames) < 4:
            # Pad with duplicates if needed
            while len(all_frames) < 4:
                all_frames.append(all_frames[-1])

        # Create 2x2 grid
        cols, rows = 2, 2
        grid_img = PILImage.new("RGB", (unit_width * cols, unit_height * rows), (0, 0, 0))

        # Load font
        font = None
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        except:
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
            except:
                font = ImageFont.load_default()

        for idx, frame_path in enumerate(all_frames[:4]):
            if not Path(frame_path).exists():
                continue

            # Open and resize image while maintaining aspect ratio
            img = PILImage.open(frame_path).convert("RGB")

            # Resize to fit within cell dimensions while maintaining aspect ratio
            img.thumbnail((unit_width, unit_height), PILImage.Resampling.LANCZOS)

            # Create a cell with black background
            cell = PILImage.new("RGB", (unit_width, unit_height), (0, 0, 0))

            # Center the image in the cell
            offset_x = (unit_width - img.width) // 2
            offset_y = (unit_height - img.height) // 2
            cell.paste(img, (offset_x, offset_y))

            # Place in grid
            x = (idx % cols) * unit_width
            y = (idx // cols) * unit_height
            grid_img.paste(cell, (x, y))

        # Save to memory buffer
        buffer = io.BytesIO()
        grid_img.save(buffer, format='JPEG', quality=85)
        buffer.seek(0)

        # Convert to base64
        image_data = base64.b64encode(buffer.read()).decode('utf-8')

        # Create Image object
        chapter_title = chapter.get('title', f'Chapter {chapter_idx + 1}')
        filename = f"chapter_{chapter_idx}_{uuid.uuid4().hex[:8]}.jpg"

        chapter_image = Image(
            name=filename,
            link=filename,
            data=image_data,
            mimetype="image/jpeg"
        )

        logger.info(f"Created 2x2 grid for chapter {chapter_idx}: {chapter_title}")
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

        screenshots = []
        processed_markdown = markdown

        # Generate grids for each chapter concurrently
        tasks = []
        for idx, chapter in enumerate(chapters):
            tasks.append(self.create_chapter_grid(video_path, chapter, idx))

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

    @tracer.start_as_current_span("create_thumbnail_grid_as_images")
    async def create_thumbnail_grid_as_images(
            self,
            video_path: str,
            grid_size: Tuple[int, int] = (3, 3),
            frame_interval: int = None,
            unit_width: int = 320,
            unit_height: int = 180,
            start_offset: int = 1
    ) -> Image | None:
        """
        Create video thumbnail grid and return Image object list
        Fixed logic: One video generates exactly one thumbnail grid with 9 images
        
        Args:
            video_path: Video file path
            grid_size: Grid size (fixed at 3x3)
            frame_interval: Frame extraction interval (auto-calculated if None)
            unit_width: Width of each thumbnail
            unit_height: Height of each thumbnail
            start_offset: Start time offset to skip black screen at beginning (seconds)
            
        Returns:
            Image object list (always contains exactly one grid image)
        """

        # Fixed 3x3 grid
        cols, rows = 3, 3
        target_frames = 9

        # Get video duration and calculate frame interval
        duration = await self.get_video_duration(video_path)
        if duration <= 0:
            logger.error("Cannot get video duration")
            return None

        if frame_interval is None:
            # Auto-calculate interval to get exactly 9 frames evenly distributed
            available_duration = duration - start_offset
            if available_duration <= 0:
                frame_interval = 1
            else:
                frame_interval = max(1, int(available_duration / target_frames))

        # Extract exactly 9 frames
        frame_paths = []
        for i in range(target_frames):
            timestamp = start_offset + i * frame_interval
            if timestamp >= duration:
                break

            time_label = f"{int(timestamp // 60):02d}_{int(timestamp % 60):02d}"
            output_path = self.frame_dir / f"frame_{time_label}_{i:03d}.jpg"

            cmd = [
                "ffmpeg",
                "-ss", str(timestamp),
                "-i", str(video_path),
                "-frames:v", "1",
                "-q:v", "2",
                str(output_path),
                "-y",
                "-hide_banner",
                "-loglevel", "error"
            ]

            code, _, _ = await exec_cmd(cmd)
            assert code == 0
            frame_paths.append(str(output_path))
            logger.debug(f"Extract frame: {output_path}")

        if not frame_paths:
            logger.warning("No frames extracted")
            return None

        logger.info(f"Extracted {len(frame_paths)} frames for 3x3 grid")

        # Create single grid image
        grid_img = PILImage.new("RGB", (unit_width * cols, unit_height * rows), (0, 0, 0))

        # Load font (try system font)
        font = None
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
        except:
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 16)
            except:
                font = ImageFont.load_default()

        for idx, frame_path in enumerate(frame_paths):
            if idx >= target_frames:
                break

            # Open and resize image
            img = PILImage.open(frame_path).convert("RGB")
            img = img.resize((unit_width, unit_height), PILImage.Resampling.LANCZOS)

            # Add timestamp label
            draw = ImageDraw.Draw(img)

            # Extract time from file name
            match = re.search(r"frame_(\d{2})_(\d{2})", Path(frame_path).name)
            if match:
                time_text = f"{match.group(1)}:{match.group(2)}"
                # Add black background for better readability
                bbox = draw.textbbox((10, 10), time_text, font=font)
                draw.rectangle([bbox[0] - 2, bbox[1] - 2, bbox[2] + 2, bbox[3] + 2], fill="black")
                draw.text((10, 10), time_text, fill="yellow", font=font)

            # Place in grid
            x = (idx % cols) * unit_width
            y = (idx // cols) * unit_height
            grid_img.paste(img, (x, y))

        # Save to memory buffer
        buffer = io.BytesIO()
        grid_img.save(buffer, format='JPEG', quality=85)
        buffer.seek(0)

        # Convert to base64
        image_data = base64.b64encode(buffer.read()).decode('utf-8')

        # Create Image object
        thumbnail_image = Image(
            name="Video Thumbnail Grid",
            link="/thumbnails/grid.jpg",
            data=image_data,
            mimetype="image/jpeg"
        )

        logger.info("Created single 3x3 grid thumbnail image")
        return thumbnail_image

    def cleanup(self):
        """Clean up temporary files"""
        import shutil
        try:
            if self.temp_dir.exists():
                shutil.rmtree(self.temp_dir)
                logger.info(f"Clean up temporary directory: {self.temp_dir}")
        except Exception as e:
            logger.warning(f"Clean up temporary files failed: {e}")
