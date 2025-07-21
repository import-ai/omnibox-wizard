from abc import abstractmethod
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from omnibox_wizard.common.utils import remove_continuous_break_lines


def get_domain(url: str) -> str:
    return urlparse(url).netloc


class Prompt(BaseModel):
    @abstractmethod
    def to_prompt(self, i: int | None = None) -> str:
        raise NotImplementedError("Subclasses should implement this method.")


def to_prompt(tag_attrs: dict, body_attrs: dict, i: int | None = None, tag_name: str = "cite") -> str:
    if i is not None:
        tag_attrs = {"id": str(i)} | tag_attrs
    header_attrs: str = " ".join([f'{k}="{v}"' for k, v in tag_attrs.items() if v])
    contents: list[str] = [
        f"<{tag_name}{' ' if header_attrs else ''}{header_attrs}>",
        *[f"<{k}>{v}</{k}>" for k, v in body_attrs.items() if v],
        f"</{tag_name}>"
    ]
    return remove_continuous_break_lines("\n".join(contents))


class Citation(Prompt):
    title: str | None = None
    snippet: str | None = None
    link: str
    updated_at: str | None = None
    source: str | None = None

    def to_prompt(self, i: int | None = None):
        attrs: dict = self.model_dump(exclude_none=True, exclude={"snippet", "link"})
        if self.link and self.link.startswith("http") and (host := get_domain(self.link)):
            attrs["host"] = host
        return to_prompt(attrs, self.model_dump(exclude_none=True, include={"snippet"}), i=i)


class Score(BaseModel):
    recall: float | None = Field(default=None)
    rerank: float | None = Field(default=None)


class BaseRetrieval(Prompt):
    score: Score = Field(default_factory=Score)
    source: str

    @abstractmethod
    def to_citation(self) -> Citation:
        raise NotImplementedError

    def __eq__(self, other) -> bool:
        return self.to_prompt() == other.to_prompt() if isinstance(other, self.__class__) else False


def retrievals2prompt(retrievals: list[Prompt], current_cite_cnt: int = 0) -> str:
    retrieval_prompt_list: list[str] = []
    for i, retrieval in enumerate(retrievals):
        retrieval_prompt_list.append(retrieval.to_prompt(current_cite_cnt + i + 1))
    if retrieval_prompt_list:
        retrieval_prompt: str = "\n\n".join(retrieval_prompt_list)
        return "\n".join(["<retrievals>", retrieval_prompt, "</retrievals>"])
    return "Not found"
