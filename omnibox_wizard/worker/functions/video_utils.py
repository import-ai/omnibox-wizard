import base64
import logging
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import List, Optional, Tuple
import shortuuid
from omnibox_wizard.worker.functions.file_readers.utils import guess_extension

logger = logging.getLogger(__name__)


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
    
    def extract_audio(self, video_path: str, output_format: str = "wav") -> str:
        """
        Extract audio from video file
        
        Args:
            video_path: Video file path
            output_format: Output audio format (wav, mp3, m4a, etc.)
            
        Returns:
            Extracted audio file path
        """
        if not self.check_ffmpeg():
            raise RuntimeError("ffmpeg is not installed, cannot extract audio")
        
        video_name = Path(video_path).stem
        audio_filename = f"{video_name}_audio.{output_format}"
        audio_path = str(self.temp_dir / audio_filename)
        
        try:
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
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            
            if Path(audio_path).exists():
                logger.info(f"Audio extraction successful: {audio_path}")
                return audio_path
            else:
                raise RuntimeError("Audio file not generated")
                
        except subprocess.CalledProcessError as e:
            logger.error(f"Audio extraction failed: {e.stderr}")
            raise RuntimeError(f"Audio extraction failed: {e.stderr}")
        except Exception as e:
            logger.error(f"Audio extraction exception: {str(e)}")
            raise
    
    def generate_screenshot(self, video_path: str, timestamp: int, index: int = 0) -> str:
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
        
        filename = f"screenshot_{index:03d}_{timestamp}s_{uuid.uuid4().hex[:8]}.jpg"
        output_path = self.screenshot_dir / filename
        
        cmd = [
            "ffmpeg",
            "-ss", str(timestamp),        # Jump to specified time
            "-i", str(video_path),         # Input file
            "-frames:v", "1",              # Extract only one frame
            "-q:v", "2",                   # Quality setting (1-31, lower quality is better)
            str(output_path),
            "-y",                          # Overwrite existing file
            "-hide_banner",                # Hide copyright information
            "-loglevel", "error"           # Only show errors
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            logger.info(f"Generate screenshot successfully: {output_path}")
            return str(output_path)
        except subprocess.CalledProcessError as e:
            logger.error(f"Generate screenshot failed: {e.stderr}")
            raise RuntimeError(f"Generate screenshot failed: {e.stderr}")
    
    def extract_timestamps_from_markdown(self, markdown: str) -> List[Tuple[str, int]]:
        """
        Extract screenshot timestamps from Markdown text
        
        Supported formats:
        - *Screenshot-mm:ss
        - Screenshot-[mm:ss]
        - ![Screenshot](mm:ss)
        
        Args:
            markdown: Markdown text
            
        Returns:
            [(original marker, timestamp in seconds), ...]
        """
        patterns = [
            r"(?:\*Screenshot-(\d{1,2}):(\d{2}))",           # *Screenshot-mm:ss
            r"(?:Screenshot-\[(\d{1,2}):(\d{2})\])",         # Screenshot-[mm:ss]
            r"(?:!\[Screenshot\]\((\d{1,2}):(\d{2})\))",     # ![Screenshot](mm:ss)
        ]
        
        results = []
        for pattern in patterns:
            for match in re.finditer(pattern, markdown):
                mm = int(match.group(1))
                ss = int(match.group(2))
                total_seconds = mm * 60 + ss
                results.append((match.group(0), total_seconds))
        
        # Remove duplicates and sort by timestamp
        results = list(set(results))
        results.sort(key=lambda x: x[1])
        
        return results
    
    def get_video_duration(self, video_path: str) -> float:
        """Get video duration (seconds)"""
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path)
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return float(result.stdout.strip())
        except (subprocess.CalledProcessError, ValueError) as e:
            logger.error(f"Get video duration failed: {e}")
            return 0.0
    
    def extract_frames_for_grid(
        self, 
        video_path: str, 
        interval: int = 30,
        max_frames: int = 100,
        start_offset: int = 1
    ) -> List[str]:
        """
        Extract video frames for thumbnail grid at specified intervals
        
        Args:
            video_path: Video file path
            interval: Frame extraction interval (seconds)
            max_frames: Maximum number of frames
            start_offset: Start time offset to skip black screen at beginning (seconds)
            
        Returns:
            Extracted frame file path list
        """
        if not self.check_ffmpeg():
            raise RuntimeError("ffmpeg is not installed")
        
        duration = self.get_video_duration(video_path)
        if duration <= 0:
            raise ValueError("Cannot get video duration")
        
        # Calculate timestamps, starting from start_offset to avoid black screen
        timestamps = []
        current = start_offset
        while current < duration and len(timestamps) < max_frames:
            timestamps.append(current)
            current += interval
        
        # Extract frames
        frame_paths = []
        for idx, ts in enumerate(timestamps):
            time_label = f"{int(ts//60):02d}_{int(ts%60):02d}"
            output_path = self.frame_dir / f"frame_{time_label}_{idx:03d}.jpg"
            
            cmd = [
                "ffmpeg",
                "-ss", str(ts),
                "-i", str(video_path),
                "-frames:v", "1",
                "-q:v", "2",
                str(output_path),
                "-y",
                "-hide_banner",
                "-loglevel", "error"
            ]
            
            try:
                subprocess.run(cmd, check=True)
                frame_paths.append(str(output_path))
                logger.debug(f"Extract frame: {output_path}")
            except subprocess.CalledProcessError as e:
                logger.error(f"Extract frame failed (ts={ts}): {e}")
        
        return frame_paths
    
    def create_thumbnail_grid(
        self,
        video_path: str,
        grid_size: Tuple[int, int] = (3, 3),
        frame_interval: int = None,
        unit_width: int = 320,
        unit_height: int = 180,
        start_offset: int = 1
    ) -> List[str]:
        """
        Create video thumbnail grid
        Fixed logic: One video generates exactly one thumbnail grid with 9 images
        
        Args:
            video_path: Video file path
            grid_size: Grid size (fixed at 3x3)
            frame_interval: Frame extraction interval (auto-calculated if None)
            unit_width: Width of each thumbnail
            unit_height: Height of each thumbnail
            start_offset: Start time offset to skip black screen at beginning (seconds)
            
        Returns:
            List containing single base64 encoded grid image
        """
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            logger.error("PIL is not installed, cannot create thumbnail grid")
            return []
        
        # Fixed 3x3 grid
        cols, rows = 3, 3
        target_frames = 9
        
        # Get video duration and calculate frame interval
        duration = self.get_video_duration(video_path)
        if duration <= 0:
            logger.error("Cannot get video duration")
            return []
        
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
            
            time_label = f"{int(timestamp//60):02d}_{int(timestamp%60):02d}"
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
            
            try:
                subprocess.run(cmd, check=True)
                frame_paths.append(str(output_path))
                logger.debug(f"Extract frame: {output_path}")
            except subprocess.CalledProcessError as e:
                logger.error(f"Extract frame failed (ts={timestamp}): {e}")
        
        if not frame_paths:
            logger.warning("No frames extracted")
            return []
        
        logger.info(f"Extracted {len(frame_paths)} frames for 3x3 grid")
        
        # Create single grid image
        grid_img = Image.new("RGB", (unit_width * cols, unit_height * rows), (0, 0, 0))
        
        # Load font (try system font)
        font = None
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 16)
        except:
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
            except:
                font = ImageFont.load_default()
        
        for idx, frame_path in enumerate(frame_paths):
            if idx >= target_frames:
                break
                
            # Open and resize image
            img = Image.open(frame_path).convert("RGB")
            img = img.resize((unit_width, unit_height), Image.Resampling.LANCZOS)
            
            # Add timestamp label
            draw = ImageDraw.Draw(img)
            
            # Extract time from file name
            match = re.search(r"frame_(\d{2})_(\d{2})", Path(frame_path).name)
            if match:
                time_text = f"{match.group(1)}:{match.group(2)}"
                # Add black background for better readability
                bbox = draw.textbbox((10, 10), time_text, font=font)
                draw.rectangle([bbox[0]-2, bbox[1]-2, bbox[2]+2, bbox[3]+2], fill="black")
                draw.text((10, 10), time_text, fill="yellow", font=font)
            
            # Place in grid
            x = (idx % cols) * unit_width
            y = (idx // cols) * unit_height
            grid_img.paste(img, (x, y))
        
        # Save grid image
        grid_path = self.grid_dir / "grid.jpg"
        grid_img.save(grid_path, quality=85)
        logger.info(f"Created single 3x3 grid image: {grid_path}")
        
        # Convert to base64
        with open(grid_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
            return [f"data:image/jpeg;base64,{encoded}"]
    
    def extract_screenshots_as_images(
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
        from omnibox_wizard.worker.entity import Image
        
        if not self.check_ffmpeg():
            logger.warning("ffmpeg is not installed, skipping screenshot generation")
            return markdown, []
        
        timestamps = self.extract_timestamps_from_markdown(markdown)
        
        if not timestamps:
            logger.info("No screenshot markers found")
            return markdown, []
        
        logger.info(f"Found {len(timestamps)} screenshot markers")
        
        screenshots = []
        processed_markdown = markdown
        
        for idx, (marker, timestamp) in enumerate(timestamps):
            try:
                # Generate screenshot
                screenshot_path = self.generate_screenshot(video_path, timestamp, idx)
                
                # Read screenshot file and convert to base64
                with open(screenshot_path, 'rb') as f:
                    image_data = base64.b64encode(f.read()).decode('utf-8')
                
                # Create Image object
                filename = Path(screenshot_path).name
                screenshot_image = Image(
                    name=f"{filename}",
                    link=f"{filename}",
                    data=image_data,
                    mimetype="image/jpeg"
                )
                
                screenshots.append(screenshot_image)
                
                # time_display = f"{timestamp//60}:{timestamp%60:02d}"
                # img_markdown = f"{time_display}\n\n{filename}"
                img_markdown = f"\n![]({filename})\n"
                processed_markdown = processed_markdown.replace(marker, img_markdown, 1)
                
                logger.info(f"Extract screenshot: {marker} -> Image object")
                
            except Exception as e:
                processed_markdown = processed_markdown.replace(marker, '', 1)
        
        return processed_markdown, screenshots

    def create_thumbnail_grid_as_images(
        self,
        video_path: str,
        grid_size: Tuple[int, int] = (3, 3),
        frame_interval: int = None,
        unit_width: int = 320,
        unit_height: int = 180,
        start_offset: int = 1
    ) -> List:
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
        from omnibox_wizard.worker.entity import Image
        
        try:
            from PIL import Image as PILImage, ImageDraw, ImageFont
        except ImportError:
            logger.error("PIL is not installed, cannot create thumbnail grid")
            return []
        
        # Fixed 3x3 grid
        cols, rows = 3, 3
        target_frames = 9
        
        # Get video duration and calculate frame interval
        duration = self.get_video_duration(video_path)
        if duration <= 0:
            logger.error("Cannot get video duration")
            return []
        
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
            
            time_label = f"{int(timestamp//60):02d}_{int(timestamp%60):02d}"
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
            
            try:
                subprocess.run(cmd, check=True)
                frame_paths.append(str(output_path))
                logger.debug(f"Extract frame: {output_path}")
            except subprocess.CalledProcessError as e:
                logger.error(f"Extract frame failed (ts={timestamp}): {e}")
        
        if not frame_paths:
            logger.warning("No frames extracted")
            return []
        
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
                draw.rectangle([bbox[0]-2, bbox[1]-2, bbox[2]+2, bbox[3]+2], fill="black")
                draw.text((10, 10), time_text, fill="yellow", font=font)
            
            # Place in grid
            x = (idx % cols) * unit_width
            y = (idx // cols) * unit_height
            grid_img.paste(img, (x, y))
        
        # Save to memory buffer
        import io
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