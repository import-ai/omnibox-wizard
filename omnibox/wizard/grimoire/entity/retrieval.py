from abc import abstractmethod

from pydantic import BaseModel, Field


class Citation(BaseModel):
    title: str | None = None
    snippet: str | None = None
    link: str
    updated_at: str | None = None


class Score(BaseModel):
    recall: float | None = Field(default=None)
    rerank: float | None = Field(default=None)


class BaseRetrieval(BaseModel):
    score: Score = Field(default_factory=Score)

    def source(self) -> str:
        return self.__class__.__name__

    @abstractmethod
    def to_prompt(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def to_citation(self) -> Citation:
        raise NotImplementedError


def retrievals2prompt(retrievals: list[BaseRetrieval], current_cite_cnt: int = 0) -> str:
    retrieval_prompt_list: list[str] = []
    for i, retrieval in enumerate(retrievals):
        prompt_list: list[str] = [
            f'<cite id="{current_cite_cnt + i + 1}" source="{retrieval.source()}">',
            retrieval.to_prompt(),
            '</cite>'
        ]
        retrieval_prompt_list.append("\n".join(prompt_list))
    if retrieval_prompt_list:
        retrieval_prompt: str = "\n\n".join(retrieval_prompt_list)
        return "\n".join(["<retrievals>", retrieval_prompt, "</retrievals>"])
    return "Not found"
