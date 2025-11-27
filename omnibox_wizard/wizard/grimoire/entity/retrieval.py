from abc import abstractmethod, ABC
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from common.utils import remove_continuous_break_lines


def get_domain(url: str) -> str:
    return urlparse(url).netloc


class PromptContext(BaseModel, ABC):
    @abstractmethod
    def to_prompt(self) -> str:
        raise NotImplementedError("Subclasses should implement this method.")


def to_prompt(
    tag_attrs: dict, body_attrs: dict, i: int | None = None, tag_name: str = "cite"
) -> str:
    if i is not None:
        tag_attrs = {"id": str(i)} | tag_attrs
    header_attrs: str = " ".join([f'{k}="{v}"' for k, v in tag_attrs.items() if v])
    contents: list[str] = [
        f"<{tag_name}{' ' if header_attrs else ''}{header_attrs}>",
        *[f"<{k}>{v}</{k}>" for k, v in body_attrs.items() if v],
        f"</{tag_name}>",
    ]
    return remove_continuous_break_lines("\n".join(contents))


class PromptCite(PromptContext, ABC):
    id: int = Field(default=-1)

    @abstractmethod
    def to_prompt(self, exclude_id: bool = False) -> str:
        raise NotImplementedError("Subclasses should implement this method.")


class Citation(PromptCite):
    title: str | None = None
    snippet: str | None = None
    link: str
    updated_at: str | None = None
    source: str | None = None

    def to_prompt(self, exclude_id: bool = False) -> str:
        attrs: dict = self.model_dump(exclude_none=True, exclude={"snippet", "link"})
        if (
            self.link
            and self.link.startswith("http")
            and (host := get_domain(self.link))
        ):
            attrs["host"] = host
        return to_prompt(
            attrs,
            self.model_dump(exclude_none=True, include={"snippet"}),
            i=None if exclude_id else self.id,
        )


class Score(BaseModel):
    recall: float | None = Field(default=None)
    rerank: float | None = Field(default=None)


class BaseRetrieval(PromptCite):
    score: Score = Field(default_factory=Score)
    source: str

    @abstractmethod
    def to_citation(self) -> Citation:
        raise NotImplementedError

    def __eq__(self, other) -> bool:
        if isinstance(other, self.__class__):
            return self.to_prompt(exclude_id=True) == other.to_prompt(exclude_id=True)
        return False


def retrievals2prompt(retrievals: list[PromptCite]) -> str:
    retrieval_prompt_list: list[str] = []
    for i, retrieval in enumerate(retrievals):
        retrieval_prompt_list.append(retrieval.to_prompt())
    if retrieval_prompt_list:
        retrieval_prompt: str = "\n\n".join(retrieval_prompt_list)
        return "\n".join(["<retrievals>", retrieval_prompt, "</retrievals>"])
    return "Not found"
