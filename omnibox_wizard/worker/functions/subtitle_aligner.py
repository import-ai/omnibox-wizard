"""
Subtitle aligner for merging original subtitles with ASR results
Combines the accuracy of original subtitles with speaker diarization from ASR
"""
import logging
import re
from difflib import SequenceMatcher
from typing import List, Dict, Any, Tuple

logger = logging.getLogger(__name__)


class SubtitleAligner:
    """
    Align original subtitles with ASR results to combine:
    - Accurate text from original subtitles
    - Speaker information from ASR
    """

    @staticmethod
    def clean_subtitle_timestamps(text: str) -> str:
        """
        Remove timestamp markers from subtitle text

        Supports common timestamp formats:
        - [00:00:00 - 00:00:29]
        - [00:00:00]
        - 00:00:00 --> 00:00:29
        - 00:00:00.000 --> 00:00:29.000
        - 00:01.677 --> 00:01.687 (MM:SS.mmm format without hours)
        - <00:00:00>
        - (00:00:00)

        Args:
            text: Subtitle text with possible timestamps

        Returns:
            Cleaned text without timestamps
        """
        # Pattern 1: [HH:MM:SS - HH:MM:SS] or [HH:MM:SS]
        text = re.sub(r'\[\d{1,2}:\d{2}:\d{2}(?:\.\d+)?\s*-?\s*\d{0,2}:?\d{0,2}:?\d{0,2}\.?\d*]', '', text)

        # Pattern 2: 00:00:00 --> 00:00:29 (SRT format with hours)
        text = re.sub(r'\d{1,2}:\d{2}:\d{2}(?:[,.]\d+)?\s*-->\s*\d{1,2}:\d{2}:\d{2}(?:[,.]\d+)?', '', text)

        # Pattern 3: 00:01.677 --> 00:01.687 (MM:SS.mmm format without hours)
        text = re.sub(r'\d{1,2}:\d{2}\.\d+\s*-->\s*\d{1,2}:\d{2}\.\d+', '', text)

        # Pattern 4: <00:00:00> or (00:00:00)
        text = re.sub(r'[<(]\d{1,2}:\d{2}:\d{2}(?:\.\d+)?[)>]', '', text)

        # Pattern 5: Standalone timestamp at line start
        text = re.sub(r'^\d{1,2}:\d{2}:\d{2}(?:[,.]\d+)?\s*$', '', text, flags=re.MULTILINE)

        return text

    @staticmethod
    def normalize_text(text: str) -> str:
        """
        Normalize text for comparison by keeping only letters, digits, and CJK characters

        This removes all punctuation, spaces, and symbols to focus on actual content.
        Converts to lowercase for case-insensitive comparison.

        Args:
            text: Input text

        Returns:
            Normalized text (only alphanumeric and CJK characters, lowercase)
        """
        # Keep only letters, digits, and CJK characters
        # Remove all punctuation, spaces, and other symbols
        normalized = []
        for char in text:
            if char.isalnum() or '\u4e00' <= char <= '\u9fff' or '\u3400' <= char <= '\u4dbf':
                normalized.append(char.lower())

        return ''.join(normalized)

    @staticmethod
    def calculate_similarity(text1: str, text2: str) -> float:
        """
        Calculate similarity between two texts using SequenceMatcher

        Args:
            text1: First text
            text2: Second text

        Returns:
            Similarity ratio (0.0 to 1.0)
        """
        if not text1 or not text2:
            return 0.0

        # Normalize texts for comparison
        norm1 = SubtitleAligner.normalize_text(text1)
        norm2 = SubtitleAligner.normalize_text(text2)

        if not norm1 or not norm2:
            return 0.0

        # Calculate similarity using SequenceMatcher
        matcher = SequenceMatcher(None, norm1, norm2)
        return matcher.ratio()

    @staticmethod
    def extract_substring_by_chars(text: str, start_char: int, target_length: int) -> Tuple[str, int]:
        """
        Extract substring from text, keeping spaces but skipping only newlines

        For similarity calculation, we use normalized text (without punctuation/spaces).
        But for the extracted result, we keep the original format including spaces and punctuation.

        Args:
            text: Source text
            start_char: Starting character position in original text
            target_length: Target length (measured by normalized characters, i.e., letters/digits/CJK chars)

        Returns:
            Tuple of (extracted_text, chars_consumed_in_original)
        """
        if start_char >= len(text):
            return "", 0

        # Start from the position
        extracted = []
        normalized_count = 0
        pos = start_char

        while pos < len(text) and normalized_count < target_length:
            char = text[pos]

            # Skip only newlines (keep spaces and other characters)
            if char in '\n\r':
                pos += 1
                continue

            # Add character to extracted text
            extracted.append(char)

            # Count only meaningful characters: letters, digits, and CJK characters
            # Everything else (punctuation, spaces, symbols) is not counted
            # This matches the normalize_text logic for consistent length calculation
            if char.isalnum() or '\u4e00' <= char <= '\u9fff' or '\u3400' <= char <= '\u4dbf':
                normalized_count += 1

            pos += 1

        chars_consumed = pos - start_char
        return ''.join(extracted), chars_consumed

    @staticmethod
    def skip_to_next_sentence_start(text: str, pos: int) -> int:
        """
        Skip to the start of next sentence (after punctuation and whitespace)

        This ensures position always aligns with sentence boundaries.

        Args:
            text: Source text
            pos: Current position (may be in the middle of a sentence or after it)

        Returns:
            New position at the start of next sentence
        """
        if pos >= len(text):
            return pos

        # Sentence-ending punctuation marks
        sentence_endings = {'。', '.', '！', '!', '？', '?', '；', ';'}

        # If already at or past a sentence ending, skip it
        if text[pos] in sentence_endings:
            pos += 1
        else:
            # Find the next sentence ending
            while pos < len(text) and text[pos] not in sentence_endings:
                pos += 1
            # Skip the sentence ending if found
            if pos < len(text) and text[pos] in sentence_endings:
                pos += 1

        # Skip whitespace and newlines after the punctuation
        while pos < len(text) and text[pos] in ' \t\n\r':
            pos += 1

        return pos

    @staticmethod
    def find_best_substring_match(
            asr_text: str,
            subtitle_text: str,
            start_pos: int = 0
    ) -> Tuple[str, int, float]:
        """
        Find the best matching substring in subtitle for an ASR sentence

        Strategy:
        - Use character position instead of sentence consumption
        - Search for substrings of varying lengths (0.5x to 2.5x ASR length)
        - Handle punctuation differences by comparing normalized text

        Args:
            asr_text: ASR sentence text
            subtitle_text: Complete subtitle text (not split into sentences)
            start_pos: Starting character position in subtitle_text

        Returns:
            Tuple of (matched_substring, chars_consumed, similarity_score)
        """
        if not asr_text or not subtitle_text or start_pos >= len(subtitle_text):
            return asr_text, 0, 0.0

        # Normalize ASR text to get target length
        normalized_asr = SubtitleAligner.normalize_text(asr_text)
        asr_length = len(normalized_asr)

        if asr_length == 0:
            return asr_text, 0, 0.0

        best_match = asr_text
        best_similarity = 0.0
        best_chars_consumed = 0

        # Search range: 0.5x to 3.5x of ASR length
        # Wider range to handle cases where subtitle has lots of punctuation/spaces
        min_length = max(1, int(asr_length * 0.5))
        max_length = int(asr_length * 3.5) + 10  # Extra buffer for safety

        for target_length in range(min_length, max_length + 1):
            # Extract substring from subtitle
            substring, chars_consumed = SubtitleAligner.extract_substring_by_chars(
                subtitle_text, start_pos, target_length
            )

            if not substring:
                break

            # Calculate similarity
            similarity = SubtitleAligner.calculate_similarity(asr_text, substring)

            if similarity > best_similarity:
                best_similarity = similarity
                best_match = substring
                best_chars_consumed = chars_consumed

            # Early exit if we found a very good match
            if similarity > 0.95:
                break

        return best_match, best_chars_consumed, best_similarity

    @staticmethod
    def parse_subtitle_text(subtitle_text: str) -> List[Dict[str, Any]]:
        """
        Parse subtitle text into structured format

        Args:
            subtitle_text: Raw subtitle text (may include timestamps)

        Returns:
            List of subtitle entries with estimated timestamps
        """
        # Simple implementation: split by lines and estimate timestamps
        # TODO: Improve to handle SRT/VTT formats if needed
        lines = [line.strip() for line in subtitle_text.split('\n') if line.strip()]

        subtitles = []
        for idx, text in enumerate(lines):
            # Estimate timestamp based on position (very rough)
            subtitles.append({
                "text": text,
                "index": idx
            })

        return subtitles

    @staticmethod
    def align_subtitles_with_asr(
            subtitle_text: str,
            asr_sentences: List[Dict[str, Any]],
            similarity_threshold: float = 0.6
    ) -> Dict[str, Any]:
        """
        Align original subtitles with ASR results using character-position-based matching

        Strategy:
        1. Keep subtitle text as complete string (not split into sentences)
        2. Maintain a character position pointer in subtitle
        3. For each ASR sentence, find the best matching substring in remaining subtitle
        4. Use variable-length search (0.5x-2.5x ASR length) to handle punctuation differences
        5. Keep ASR's sentence structure, timing, and speaker info
        6. Only use subtitle text to correct ASR recognition errors

        This approach ensures:
        - ASR sentence boundaries are preserved (no matter how subtitle is split)
        - Subtitle only serves to correct text errors, not to change sentence structure
        - Works with different granularities between ASR and subtitle segmentation

        Args:
            subtitle_text: Original subtitle text (complete, not split)
            asr_sentences: ASR results with format:
                [{'begin_time': 0, 'end_time': 8130, 'text': 'xxx', 'speaker_id': 0, 'words': [...]}]
            similarity_threshold: Minimum similarity to accept a match (0.0 to 1.0, default 0.6)
                Higher threshold reduces false matches but may increase fallback to ASR

        Returns:
            Aligned transcript dict with 'sentences' key
        """
        if not asr_sentences:
            logger.warning("No ASR sentences to align")
            return {"sentences": []}

        if not subtitle_text or not subtitle_text.strip():
            logger.info("No subtitle text, using ASR text as-is")
            return {"sentences": asr_sentences}

        # Clean timestamps from subtitle text
        subtitle_text = SubtitleAligner.clean_subtitle_timestamps(subtitle_text)
        logger.debug(f"Cleaned subtitle text, length: {len(subtitle_text)}")

        logger.info(f"Aligning {len(asr_sentences)} ASR sentences with subtitles (character-position-based)")

        # Align each ASR sentence with subtitle substring
        aligned_sentences = []
        char_pos = 0  # Current character position in subtitle
        match_count = 0
        fallback_count = 0

        for i, asr_sentence in enumerate(asr_sentences):
            asr_text = asr_sentence.get('text', '').strip()
            begin_time = asr_sentence.get('begin_time', 0)
            end_time = asr_sentence.get('end_time', 0)
            speaker_id = asr_sentence.get('speaker_id', 0)
            words = asr_sentence.get('words', [])

            if not asr_text:
                # Empty ASR text, skip
                continue

            # Find best matching substring in remaining subtitle
            matched_text, chars_consumed, similarity = SubtitleAligner.find_best_substring_match(
                asr_text, subtitle_text, char_pos
            )

            # Decide whether to use matched text or fall back to ASR text
            if similarity >= similarity_threshold:
                # Good match found - use subtitle text to correct ASR
                final_text = matched_text
                # Advance position to the end of matched text, then skip to next sentence start
                # This ensures next sentence starts at sentence boundary
                char_pos += chars_consumed
                char_pos = SubtitleAligner.skip_to_next_sentence_start(subtitle_text, char_pos)
                match_count += 1
                logger.debug(
                    f"ASR[{i}] matched with similarity {similarity:.2f}, moved to next sentence at pos {char_pos}")
            else:
                # Low similarity - keep ASR text as-is
                final_text = asr_text
                fallback_count += 1
                # Skip to next sentence boundary to stay aligned
                # This prevents accumulating position errors
                char_pos = SubtitleAligner.skip_to_next_sentence_start(subtitle_text, char_pos)
                logger.debug(
                    f"ASR[{i}] fallback (similarity {similarity:.2f}), skipped to next sentence at pos {char_pos}")

            aligned_sentences.append({
                'begin_time': begin_time,
                'end_time': end_time,
                'text': final_text,
                'speaker_id': speaker_id,
                'words': words
            })

        logger.info(
            f"Alignment complete: {len(aligned_sentences)} sentences, {match_count} matched ({match_count * 100 // len(asr_sentences)}%), {fallback_count} fallback to ASR")
        return {"sentences": aligned_sentences}
