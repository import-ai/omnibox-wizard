from abc import ABC, abstractmethod

from bs4 import BeautifulSoup, Tag


class BaseSelector(ABC):
    @abstractmethod
    def hit(self, url: str, soup: BeautifulSoup) -> bool:
        raise NotImplementedError()

    @abstractmethod
    def select(self, url: str, soup: BeautifulSoup) -> Tag:
        raise NotImplementedError()
