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
