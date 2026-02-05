import json
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from opentelemetry import trace

from wizard_common.worker.entity import GeneratedContent, Image
from omnibox_wizard.worker.functions.html_reader.processors.base import (
    HTMLReaderBaseProcessor,
)

tracer = trace.get_tracer("FeishuProcessor")


class FeishuProcessor(HTMLReaderBaseProcessor):
    """Processor for Feishu (Lark) wiki/docs pages.

    Extracts content from Feishu's JavaScript data structures.
    The actual document content is stored in window.DATA.clientVars.data.block_map
    """

    FEISHU_DOMAINS = {"feishu.cn", "larksuite.com", "larkoffice.com"}

    def hit(self, html: str, url: str) -> bool:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        # Check for Feishu domains
        for feishu_domain in self.FEISHU_DOMAINS:
            if feishu_domain in domain:
                return True

        # Also check HTML content for Feishu-specific markers
        if "feishu-static" in html or "lark" in html.lower():
            return True

        return False

    @tracer.start_as_current_span("FeishuProcessor.convert")
    async def convert(self, html: str, url: str) -> GeneratedContent:
        span = trace.get_current_span()
        span.set_attributes({"url": url})

        # Extract document data from HTML
        doc_data = self._extract_doc_data(html)

        if not doc_data:
            # Fallback: try to extract from rendered HTML
            span.set_attribute("fallback", "html_parsing")
            return self._fallback_parse(html, url)

        block_map = doc_data.get("block_map", {})
        block_sequence = doc_data.get("block_sequence", [])

        span.set_attributes({
            "block_count": len(block_map),
            "sequence_length": len(block_sequence),
        })

        # Convert blocks to markdown
        markdown_lines = []
        for block_id in block_sequence:
            block = block_map.get(block_id)
            if not block:
                continue

            md = self._block_to_markdown(block)
            if md:
                markdown_lines.append(md)

        markdown = "\n\n".join(markdown_lines)

        # Extract title from first heading or page block
        title = self._extract_title(block_map, block_sequence) or "Feishu Document"

        # Extract images
        images = self._extract_images(block_map, block_sequence)

        span.set_attributes({
            "title": title,
            "markdown_length": len(markdown),
            "image_count": len(images),
        })

        return GeneratedContent(
            title=title,
            markdown=markdown,
            images=images if images else None,
        )

    def _extract_doc_data(self, html: str) -> dict | None:
        """Extract document data from Feishu's JavaScript variables."""
        soup = BeautifulSoup(html, "html.parser")

        # Method 1: Look for DATA in script tags
        for script in soup.find_all("script"):
            script_text = str(script.string or "")

            # Try to find window.DATA
            if "window.DATA" in script_text or "DATA=" in script_text:
                # Extract DATA object
                data_match = re.search(
                    r'window\.DATA\s*=\s*(\{.*?\});',
                    script_text,
                    re.DOTALL,
                )
                if not data_match:
                    data_match = re.search(
                        r'DATA\s*=\s*(\{.*?\});',
                        script_text,
                        re.DOTALL,
                    )

                if data_match:
                    try:
                        data = json.loads(data_match.group(1))
                        if "clientVars" in data and "data" in data["clientVars"]:
                            client_data = data["clientVars"]["data"]
                            return {
                                "block_map": client_data.get("block_map", {}),
                                "block_sequence": client_data.get(
                                    "block_sequence",
                                    list(client_data.get("block_map", {}).keys()),
                                ),
                            }
                    except json.JSONDecodeError:
                        continue

        # Method 2: Look for server-rendered data
        for script in soup.find_all("script"):
            script_text = str(script.string or "")

            if "SERVER_DATA" in script_text:
                match = re.search(
                    r'window\.SERVER_DATA\s*=\s*(\{.*?\});',
                    script_text,
                    re.DOTALL,
                )
                if match:
                    try:
                        data = json.loads(match.group(1))
                        if "document" in data and "blocks" in data["document"]:
                            return {
                                "block_map": data["document"]["blocks"],
                                "block_sequence": list(data["document"]["blocks"].keys()),
                            }
                    except json.JSONDecodeError:
                        continue

        # Method 3: Try to find any JSON that looks like Feishu blocks
        for script in soup.find_all("script", type="application/json"):
            try:
                data = json.loads(script.string or "{}")
                if "block_map" in data or "blocks" in data:
                    return {
                        "block_map": data.get("block_map") or data.get("blocks", {}),
                        "block_sequence": data.get(
                            "block_sequence",
                            list(data.get("block_map", {}).keys()),
                        ),
                    }
            except (json.JSONDecodeError, AttributeError):
                continue

        return None

    def _block_to_markdown(self, block: dict) -> str | None:
        """Convert a single block to markdown."""
        if not block or "data" not in block:
            return None

        data = block["data"]
        block_type = data.get("type", "text")
        text = self._get_block_text(block)

        converters = {
            "page": lambda txt: f"# {txt}" if txt else None,
            "heading1": lambda txt: f"# {txt}" if txt else None,
            "heading2": lambda txt: f"## {txt}" if txt else None,
            "heading3": lambda txt: f"### {txt}" if txt else None,
            "heading4": lambda txt: f"#### {txt}" if txt else None,
            "heading5": lambda txt: f"##### {txt}" if txt else None,
            "heading6": lambda txt: f"###### {txt}" if txt else None,
            "text": lambda txt: txt if txt else None,
            "bullet": lambda txt: f"- {txt}" if txt else None,
            "ordered": lambda txt: f"1. {txt}" if txt else None,
            "code": lambda txt: f"```\n{txt}\n```" if txt else None,
            "quote": lambda txt: f"> {txt}" if txt else None,
            "divider": lambda _: "---",
            "image": lambda txt: f"![{txt}](image)" if txt else "![Image](image)",
            "table": lambda _: "[Table]",
            "sheet": lambda _: "[Spreadsheet]",
            "file": lambda txt: f"[File: {txt}]" if txt else "[File]",
            "diagram": lambda _: "[Diagram]",
            "mindnote": lambda _: "[Mind Map]",
        }

        converter = converters.get(block_type)
        if converter:
            return converter(text)

        return text if text else None

    def _get_block_text(self, block: dict) -> str:
        """Extract text content from a block."""
        if not block or "data" not in block:
            return ""

        data = block["data"]

        # Try different text locations in Feishu block structure
        if data.get("text", {}).get("initialAttributedTexts"):
            return self._extract_attributed_text(
                data["text"]["initialAttributedTexts"]
            )

        if data.get("caption", {}).get("text", {}).get("initialAttributedTexts"):
            return self._extract_attributed_text(
                data["caption"]["text"]["initialAttributedTexts"]
            )

        # Fallback: try content field
        return data.get("content", "")

    def _extract_attributed_text(self, attributed_texts: dict) -> str:
        """Extract plain text from Feishu's attributed text format."""
        if not attributed_texts or "text" not in attributed_texts:
            return ""

        texts = attributed_texts["text"]
        if not texts:
            return ""

        # Sort by key (position) and join
        sorted_keys = sorted(texts.keys(), key=lambda x: int(x) if x.isdigit() else 0)
        return "".join(str(texts[key]) for key in sorted_keys)

    def _extract_title(self, block_map: dict, block_sequence: list) -> str | None:
        """Extract title from first heading or page block."""
        for block_id in block_sequence:
            block = block_map.get(block_id)
            if not block:
                continue

            block_type = block.get("data", {}).get("type", "")
            text = self._get_block_text(block)

            if block_type in ("page", "heading1", "heading2") and text:
                return text

        return None

    def _extract_images(self, block_map: dict, block_sequence: list) -> list[Image]:
        """Extract image information from blocks."""
        images = []

        for block_id in block_sequence:
            block = block_map.get(block_id)
            if not block:
                continue

            block_type = block.get("data", {}).get("type", "")
            if block_type == "image":
                image_data = block.get("data", {}).get("image", {})
                token = image_data.get("token", "")
                name = image_data.get("name", "image.png")

                # Feishu image URLs typically need to be constructed from tokens
                # The actual URL would require API calls or proper token resolution
                if token:
                    images.append(
                        Image.model_validate(
                            {
                                "name": name,
                                "link": f"feishu://image/{token}",
                                "data": "",
                                "mimetype": image_data.get("mimeType", "image/png"),
                            }
                        )
                    )

        return images

    def _fallback_parse(self, html: str, _url: str) -> GeneratedContent:
        """Fallback parsing when structured data extraction fails."""
        from html2text import html2text

        soup = BeautifulSoup(html, "html.parser")

        # Try to find the main content area
        content_selectors = [
            "[data-docx]",
            ".docx-wrapper",
            ".wiki-content",
            "article",
            ".document-body",
        ]

        content = None
        for selector in content_selectors:
            content = soup.select_one(selector)
            if content:
                break

        if not content:
            content = soup.body or soup

        # Remove navigation elements
        for nav in content.find_all(["nav", "header", "footer", "aside"]):
            nav.decompose()

        markdown = html2text(str(content), bodywidth=0)

        # Try to find title
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else "Feishu Document"

        return GeneratedContent(
            title=title,
            markdown=markdown.strip(),
            images=None,
        )
