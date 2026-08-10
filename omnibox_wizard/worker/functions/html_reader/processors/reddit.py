from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag
from html2text import html2text
from wizard_common.worker.entity import GeneratedContent

from omnibox_wizard.worker.functions.html_reader.processors.base import (
    HTMLReaderBaseProcessor,
)


class RedditProcessor(HTMLReaderBaseProcessor):
    SUPPORTED_HOSTS = {"reddit.com", "www.reddit.com"}

    @classmethod
    def _extract_post_id(cls, url: str) -> str | None:
        parsed = urlparse(url)
        if parsed.hostname not in cls.SUPPORTED_HOSTS:
            return None

        path_parts = [part for part in parsed.path.split("/") if part]
        if len(path_parts) not in {4, 5}:
            return None

        if path_parts[0] != "r" or path_parts[2] != "comments":
            return None

        post_id = path_parts[3]
        if not post_id.isascii() or not post_id.isalnum():
            return None

        return post_id

    @staticmethod
    def _extract_title(post: Tag) -> str:
        title_tag = post.select_one('h1[slot="title"]')
        if title_tag:
            title = title_tag.get_text(" ", strip=True)
            if title:
                return title

        return str(post.get("post-title") or "").strip()

    @staticmethod
    def _extract_body_markdown(post: Tag) -> str:
        body = post.select_one('[property="schema:articleBody"]')
        if not body:
            return ""

        return html2text(str(body), bodywidth=0).strip()

    @staticmethod
    def _extract_image_refs(post: Tag) -> list[tuple[str, str]]:
        if post.get("post-type") == "video":
            return []

        media = post.select_one('[slot="post-media-container"]')
        if not media:
            return []

        poster_image_tags = [
            image_tag
            for image_tag in media.select('img[slot="poster"]')
            if str(image_tag.get("src") or "").strip()
        ]
        original_image_tags = [
            image_tag
            for image_tag in media.find_all("img")
            if urlparse(str(image_tag.get("src") or "")).hostname == "i.redd.it"
        ]
        image_tags = (
            poster_image_tags
            or original_image_tags
            or media.select("img.media-lightbox-img")
        )

        image_refs: list[tuple[str, str]] = []
        seen_urls: set[str] = set()

        for image_tag in image_tags:
            src = str(image_tag.get("src") or "").strip()
            if not src or src in seen_urls:
                continue

            seen_urls.add(src)
            alt = str(image_tag.get("alt") or "").strip()
            image_refs.append((src, alt or str(len(image_refs) + 1)))

        return image_refs

    @staticmethod
    def _build_markdown(*parts: str) -> str:
        return "\n\n".join(part.strip() for part in parts if part.strip())

    def hit(self, html: str, url: str) -> bool:
        """Return whether the URL identifies a supported Reddit post."""
        return self._extract_post_id(url) is not None

    async def convert(self, html: str, url: str) -> GeneratedContent:
        """Convert a Reddit post into normalized generated content."""
        post_id = self._extract_post_id(url)
        if not post_id:
            raise ValueError("Unsupported Reddit post URL")

        soup = BeautifulSoup(html, "html.parser")
        post = soup.find("shreddit-post", id=f"t3_{post_id}")
        if not isinstance(post, Tag):
            raise ValueError(f"Reddit post t3_{post_id} was not found")

        title = self._extract_title(post)
        body_markdown = self._extract_body_markdown(post)
        image_refs = self._extract_image_refs(post)
        image_markdown = "\n\n".join(f"![{alt}]({src})" for src, alt in image_refs)

        markdown = self._build_markdown(
            title,
            body_markdown,
            image_markdown,
        )
        if not markdown:
            raise ValueError(f"Reddit post t3_{post_id} has no content")

        images = await self.get_images(image_refs) if image_refs else []
        return GeneratedContent(
            title=title or None,
            markdown=markdown,
            images=images or None,
        )
