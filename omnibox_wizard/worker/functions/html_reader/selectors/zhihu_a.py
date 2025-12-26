from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from omnibox_wizard.worker.functions.html_reader.selectors.base import BaseSelector


class ZhihuAnswerSelector(BaseSelector):
    def hit(self, url: str, soup: BeautifulSoup) -> bool:
        parsed = urlparse(url)
        return (
            parsed.netloc == "www.zhihu.com"
            and "/question/" in parsed.path
            and "/answer/" in parsed.path
        )

    def select(self, url: str, soup: BeautifulSoup) -> Tag:
        return soup.select_one("div.AnswerCard div.RichContent")
