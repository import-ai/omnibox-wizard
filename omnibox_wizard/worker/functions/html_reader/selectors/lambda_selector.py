from typing import Callable
from urllib.parse import urlparse, ParseResult

from bs4 import BeautifulSoup, Tag

from omnibox_wizard.worker.functions.html_reader.selectors.base import BaseSelector

HitFuncType = Callable[[ParseResult, BeautifulSoup], bool]


class LambdaSelector(BaseSelector):
    def __init__(
        self, hit_func: HitFuncType, selector: dict, select_all: bool = False
    ) -> None:
        self.select_all = select_all
        self.selector: dict = selector
        self.hit_func: HitFuncType = hit_func

    def hit(self, url: str, soup: BeautifulSoup) -> bool:
        return self.hit_func(urlparse(url), soup)

    def select(self, url: str, soup: BeautifulSoup) -> Tag:
        if self.select_all:
            items = soup.find_all(**self.selector)
            if items:
                standalone_soup = BeautifulSoup("", "html.parser")
                div = standalone_soup.new_tag("div")
                for item in items:
                    div.append(item)
                return div
        if content := soup.find(**self.selector):
            return content
        return soup
