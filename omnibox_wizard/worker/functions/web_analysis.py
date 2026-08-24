import os
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from opentelemetry import trace
from wizard_common.worker.entity import Task, TaskFunction

from common.trace_info import TraceInfo
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.functions.base_function import BaseFunction
from omnibox_wizard.worker.functions.collect_url import CollectUrlFunction

tracer = trace.get_tracer(__name__)


def is_xhs(url: str) -> bool:
    domain: str = urlparse(url).netloc
    for pattern in ["xiaohongshu.com", "xhslink.com"]:
        if pattern in domain:
            return True
    return False


def is_douyin(url: str) -> bool:
    domain: str = urlparse(url).netloc
    for pattern in ["douyin.com"]:
        if pattern in domain:
            return True
    return False


def is_tiktok(url: str) -> bool:
    domain: str = urlparse(url).netloc
    for pattern in ["tiktok.com", "tiktokv.com"]:
        if pattern in domain:
            return True
    return False


def is_instagram(url: str) -> bool:
    domain: str = urlparse(url).netloc
    for pattern in ["instagram.com"]:
        if pattern in domain:
            return True
    return False


def _instagram_target_article_has_video(
    soup: BeautifulSoup,
    shortcode: str,
) -> bool:
    for article in soup.select("article"):
        for link in article.select("a[href]"):
            path = urlparse(str(link.get("href") or "")).path
            path_parts = [part for part in path.split("/") if part]

            matches_shortcode = any(
                path_parts[index] in {"p", "reel", "reels"}
                and path_parts[index + 1] == shortcode
                for index in range(len(path_parts) - 1)
            )
            if matches_shortcode and article.select_one("video"):
                return True
    return False


def is_ximalaya(url: str) -> bool:
    host: str = urlparse(url).hostname or ""
    for domain in ["ximalaya.com", "xima.tv"]:
        if host == domain or host.endswith(f".{domain}"):
            return True
    return False


def is_xiaoyuzhou(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname or ""

    if host != "xiaoyuzhoufm.com" and not host.endswith(".xiaoyuzhoufm.com"):
        return False

    return parsed.path.startswith("/episode/")


def is_audio(url: str) -> bool:
    return is_ximalaya(url) or is_xiaoyuzhou(url)


class WebAnalysisFunction(BaseFunction):
    def __init__(self, config: WorkerConfig):
        self.collect_url = CollectUrlFunction(config)
        self.video_prefixes: list[str] = list(
            filter(bool, os.getenv("OB_VIDEO_PREFIXES", "").split(","))
        )

    async def _analyze_instagram(
        self,
        url: str,
        html: str,
        title: str,
    ) -> tuple[bool, str, str, str]:
        parsed = urlparse(url)
        if parsed.path.startswith(("/reel/", "/reels/")):
            return True, url, html, title
        if not parsed.path.startswith("/p/"):
            return False, url, html, title

        path_parts = [part for part in parsed.path.split("/") if part]
        is_standard_post = (
            parsed.scheme == "https"
            and parsed.netloc.lower() == "www.instagram.com"
            and len(path_parts) == 2
            and path_parts[0] == "p"
        )
        if not is_standard_post:
            return False, url, html, title

        shortcode = path_parts[1]
        canonical_url = f"https://www.instagram.com/p/{shortcode}/"
        span = trace.get_current_span()

        span.set_attribute("instagram_shortcode", shortcode)
        span.set_attribute("instagram_detail_scraped", False)

        try:
            scrape_result = await self.collect_url._scrape_url(canonical_url)
            if not scrape_result.html.strip():
                raise RuntimeError("Instagram detail scrape returned empty HTML")
        except Exception as error:
            span.record_exception(error)
        else:
            url = canonical_url
            html = scrape_result.html
            title = scrape_result.title
            span.set_attribute("instagram_detail_scraped", True)

        soup = BeautifulSoup(html, "html.parser")
        is_video = bool(soup.select_one("main video"))
        if not is_video:
            is_video = _instagram_target_article_has_video(soup, shortcode)

        return is_video, url, html, title

    def is_video(self, url: str, html: str) -> bool:
        soup = BeautifulSoup(html, "html.parser")
        if is_xhs(url):
            element = soup.find(attrs={"data-type": True})
            return element.get("data-type") == "video" if element else False
        if is_douyin(url):
            if feed_active := soup.find(attrs={"data-e2e": "feed-active-video"}):
                return any(
                    "hideXgVideo" not in c.get("class", "")
                    for c in feed_active.find_all("xg-video-container")
                )
            return True
        if is_tiktok(url):
            parsed = urlparse(url)
            if "/photo/" in parsed.path:
                return False
            if "/video/" in parsed.path:
                return True
            active_slide = soup.find(attrs={"class": "swiper-slide-active"})
            if active_slide:
                active_html = str(active_slide)
                if (
                    "photomode" in active_html
                    or "DivPhotoPlayerContainer" in active_html
                    or "ImgPhotoSlide" in active_html
                ):
                    return False
            return True
        for prefix in self.video_prefixes:
            if url.startswith(prefix):
                return True
        return False

    @tracer.start_as_current_span("WebAnalysisFunction.run")
    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        span = trace.get_current_span()
        url = task.input["url"]
        html = task.input["html"]
        title = task.input.get("title", "")

        span.set_attribute("url", url)

        is_audio_content = is_audio(url)
        if is_audio_content:
            is_video = False
        elif is_instagram(url):
            is_video, url, html, title = await self._analyze_instagram(
                url,
                html,
                title,
            )
        else:
            is_video = self.is_video(url, html)

        span.set_attribute("url", url)
        span.set_attribute("is_audio", is_audio_content)
        span.set_attribute("is_video", is_video)

        if is_audio_content:
            next_function = TaskFunction.GENERATE_AUDIO_NOTE
        elif is_video:
            next_function = TaskFunction.GENERATE_VIDEO_NOTE
        else:
            next_function = TaskFunction.COLLECT

        return {
            "is_audio": is_audio_content,
            "is_video": is_video,
            "next_tasks": [
                task.create_next_task(
                    next_function, {"url": url, "html": html, "title": title}
                ).model_dump()
            ],
        }
