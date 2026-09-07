from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from html2text import html2text
from wizard_common.worker.entity import GeneratedContent

from omnibox_wizard.worker.functions.html_reader.processors.base import (
    HTMLReaderBaseProcessor,
)


class ZhihuProcessor(HTMLReaderBaseProcessor):
    """Convert Zhihu column articles into focused note content."""

    def hit(self, html: str, url: str) -> bool:
        parsed = urlparse(url)
        path_parts = [part for part in parsed.path.split("/") if part]

        return (
            parsed.hostname == "zhuanlan.zhihu.com"
            and len(path_parts) == 2
            and path_parts[0] == "p"
            and bool(path_parts[1])
        )

    @staticmethod
    def _extract_title(article: Tag) -> str:
        title = article.select_one(".Post-Header h1.Post-Title")
        return title.get_text(" ", strip=True) if title else ""

    @staticmethod
    def _extract_column(article: Tag) -> tuple[str, str]:
        column_link = article.select_one('.Post-Header a[href*="/column/"]')
        if not column_link:
            return "", ""

        href = column_link.get("href")
        if not href:
            return "", ""

        text = column_link.get_text(" ", strip=True)
        if "·" in text:
            text = text.rsplit("·", maxsplit=1)[-1].strip()

        return text, urljoin("https://zhuanlan.zhihu.com", href)

    @staticmethod
    def _extract_image_refs(body: Tag) -> list[tuple[str, str]]:
        image_refs: list[tuple[str, str]] = []
        seen_urls: set[str] = set()

        for image in body.select("img"):
            src = str(image.get("src") or "").strip()
            if not src or src in seen_urls:
                continue

            seen_urls.add(src)
            alt = str(image.get("alt") or "").strip()
            image_refs.append((src, alt or str(len(image_refs) + 1)))

        return image_refs

    @staticmethod
    def _build_markdown(
        body_markdown: str,
        column_name: str,
        column_url: str,
    ) -> str:
        parts = []

        if body_markdown:
            parts.append(body_markdown)

        if column_name and column_url:
            parts.append(f"所属专栏：[{column_name}]({column_url})")

        return "\n\n".join(parts).strip()

    async def convert(self, html: str, url: str) -> GeneratedContent:
        if not self.hit(html, url):
            raise ValueError("Unsupported Zhihu column article URL")

        soup = BeautifulSoup(html, "html.parser")
        article = soup.select_one("article.Post-Main")
        if not article:
            raise ValueError("Zhihu column article was not found")

        body = article.select_one(".Post-RichText")
        if not body:
            raise ValueError("Zhihu column article body was not found")

        title = self._extract_title(article)
        column_name, column_url = self._extract_column(article)
        image_refs = self._extract_image_refs(body)
        body_markdown = html2text(str(body), bodywidth=0).strip()
        markdown = self._build_markdown(
            body_markdown,
            column_name,
            column_url,
        )

        if not markdown:
            raise ValueError("Zhihu column article has no content")

        images = await self.get_images(image_refs) if image_refs else []

        return GeneratedContent(
            title=title or None,
            markdown=markdown,
            images=images or None,
        )
