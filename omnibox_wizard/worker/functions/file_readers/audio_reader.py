import logging
import os

import httpx
from opentelemetry import trace
from pydub import AudioSegment

from omnibox_wizard.worker.config import FileUploaderConfig
from omnibox_wizard.worker.functions.file_uploaders.s3_uploader import S3Uploader

tracer = trace.get_tracer(__name__)
logger = logging.getLogger(__name__)


class ASRClient(httpx.AsyncClient):

    def __init__(self, model: str, file_upload_config: FileUploaderConfig, *args, **kwargs):
        self.model: str = model
        self.file_uploader = S3Uploader(
            bucket=file_upload_config.bucket,
            access_key=file_upload_config.access_key,
            secret_key=file_upload_config.secret_key,
            endpoint_url=file_upload_config.endpoint,
            prefix=file_upload_config.prefix,
            expire_hours=file_upload_config.expire_hours
        )
        super().__init__(*args, **kwargs)

    @tracer.start_as_current_span("ASRClient.submit_task")
    async def _submit_task(self, file_url: str) -> str:
        """
        Submit ASR transcription task

        Args:
            file_url: Public URL of the audio file

        Returns:
            Task ID

        Raises:
            RuntimeError: If task submission fails
        """
        data = {
            "model": self.model,
            "input": {"file_urls": [file_url]},
            "parameters": {
                "diarization_enabled": True,
                "timestamp_alignment_enabled": True
            }
        }

        try:
            logger.debug(f"Submitting ASR task for file: {file_url}")
            response = await self.post(
                "/services/audio/asr/transcription",
                json=data,
                headers={"X-DashScope-Async": "enable"},
                timeout=60,
            )

            if not response.is_success:
                raise RuntimeError(f"Failed to submit ASR task: {response.status_code} {response.text}")

            result = response.json()
            task_id = result.get("output", {}).get("task_id")

            if not task_id:
                raise RuntimeError(f"No task_id in response: {result}")

            logger.debug(f"ASR task submitted successfully, task_id: {task_id}")
            return task_id

        except httpx.HTTPError as e:
            raise RuntimeError(f"HTTP error during task submission: {str(e)}")

    @tracer.start_as_current_span("ASRClient.query_task")
    async def _query_task(self, task_id: str, timeout: int = 600, poll_interval: float = 2.0) -> list:
        """
        Query ASR task status and wait for completion

        Args:
            task_id: Task ID from submit_task
            timeout: Maximum time to wait (seconds)
            poll_interval: Time between status checks (seconds)

        Returns:
            List of results with transcription URLs

        Raises:
            RuntimeError: If task fails or times out
        """
        import asyncio
        import time

        start_time = time.time()

        while True:
            # Check timeout
            elapsed = time.time() - start_time
            if elapsed > timeout:
                raise RuntimeError(f"ASR task timeout after {timeout} seconds")

            try:
                logger.debug(f"Querying task status, task_id: {task_id}, elapsed: {elapsed:.1f}s")
                response = await self.post(
                    f"/tasks/{task_id}",
                    headers={"X-DashScope-Async": "enable"},
                    timeout=30,
                )

                if not response.is_success:
                    raise RuntimeError(f"Failed to query task status: {response.status_code} {response.text}")

                result = response.json()
                task_status = result.get("output", {}).get("task_status")

                logger.debug(f"Task {task_id} status: {task_status}")

                if task_status == "SUCCEEDED":
                    logger.debug(f"ASR task {task_id} succeeded")
                    results = result.get("output", {}).get("results", [])
                    return results

                elif task_status in ["RUNNING", "PENDING"]:
                    # Task still in progress, wait and retry
                    logger.debug(f"Task still {task_status}, waiting {poll_interval}s...")
                    await asyncio.sleep(poll_interval)
                    continue

                elif task_status == "FAILED":
                    error_msg = result.get("output", {}).get("error", "Unknown error")
                    raise RuntimeError(f"ASR task failed: {error_msg}")

                else:
                    raise RuntimeError(f"Unknown task status: {task_status}, response: {result}")

            except httpx.HTTPError as e:
                logger.warning(f"HTTP error while polling task status: {str(e)}, retrying...")
                await asyncio.sleep(poll_interval)
                continue

    @tracer.start_as_current_span("ASRClient.transcribe")
    async def transcribe(self, file_path: str, return_structured: bool = False) -> str | dict:
        """
        Transcribe audio file using DashScope ASR service (async mode)

        Workflow:
        1. Upload file to OSS -> get public URL
        2. Submit ASR task -> get task_id
        3. Poll task status -> wait for SUCCEEDED
        4. Fetch transcription result from transcription_url
        5. Parse and format result
        6. Cleanup OSS file

        Args:
            file_path: Path to local audio file
            return_structured:
                If True, return structured data with speaker info
                if False, return formatted text

        Returns:
            If return_structured=True: dict with 'sentences' key containing detailed ASR results
            If return_structured=False: Formatted text string with timestamps and speaker labels
        """
        span = trace.get_current_span()

        # Upload file to get public URL
        file_url = None

        try:
            # Step 1: Upload file to OSS
            logger.debug(f"Uploading audio file to OSS: {file_path}")
            file_url = await self.file_uploader.upload(file_path)
            logger.debug(f"Audio file uploaded, public URL: {file_url}")

            span.set_attributes({
                "file_url": file_url,
                "uploader_type": type(self.file_uploader).__name__,
                "asr_model_name": f"self.model",
                "asr_base_url": f"self.base_url"
            })
            # Step 2: Submit ASR task
            task_id = await self._submit_task(file_url)
            span.set_attribute("task_id", task_id)

            # Step 3: Query task status until completion
            results = await self._query_task(task_id)

            # Step 4: Fetch and parse transcription results
            all_sentences = []

            for result_item in results:
                subtask_status = result_item.get("subtask_status")
                if subtask_status != "SUCCEEDED":
                    logger.warning(f"Subtask failed with status: {subtask_status}")
                    continue

                transcription_url = result_item.get("transcription_url")
                if not transcription_url:
                    logger.warning("No transcription_url in result")
                    continue

                # Fetch detailed transcription result (valid for 24 hours)
                logger.debug(f"Fetching transcription result from: {transcription_url}")
                trans_response = await self.get(transcription_url, timeout=60)

                if not trans_response.is_success:
                    logger.warning(f"Failed to fetch transcription result: {trans_response.status_code}")
                    continue

                trans_data = trans_response.json()

                # Parse transcription data
                for transcript in trans_data.get("transcripts", []):
                    for sentence in transcript.get("sentences", []):
                        all_sentences.append(sentence)

            if not all_sentences:
                logger.warning("No transcription content found in results")
                return {} if return_structured else ""

            logger.debug(f"Transcription completed, total sentences: {len(all_sentences)}")

            # Return structured data if requested
            if return_structured:
                return {"sentences": all_sentences}

            # Otherwise return formatted text
            return self.convert_sentences_to_text(all_sentences)

        except Exception as e:
            error_msg = f"ASR transcription failed: {str(e)}"
            logger.error(error_msg)
            span.set_attribute("error", error_msg)
            raise RuntimeError(error_msg)

    @staticmethod
    def _format_time(milliseconds: int) -> str:
        """
        Format time from milliseconds to MM:SS or HH:MM:SS

        Args:
            milliseconds: Time in milliseconds

        Returns:
            Formatted time string (MM:SS for duration < 1 hour, HH:MM:SS for duration >= 1 hour)
        """
        total_seconds = milliseconds // 1000
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes:02d}:{secs:02d}"

    @classmethod
    def convert_sentences_to_text(cls, all_sentences) -> str:
        sentence_info = []
        for sentence in all_sentences:
            start_time = cls._format_time(sentence.get("begin_time", 0))
            speaker_id = sentence.get("speaker_id", 0)
            text = sentence.get("text", "")
            one_sentence = f"[{start_time}] Speaker {speaker_id}: {text}"
            sentence_info.append(one_sentence)
        return '\n'.join(sentence_info)


class M4AConvertor:
    @classmethod
    def convert(cls, m4a_filepath: str) -> str:
        mp3_filepath: str = os.path.splitext(m4a_filepath)[0] + '.mp3'
        audio = AudioSegment.from_file(m4a_filepath, format="m4a")
        audio.export(mp3_filepath, format="mp3")
        return mp3_filepath
