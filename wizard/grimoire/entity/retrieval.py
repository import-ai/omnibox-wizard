from pydantic import BaseModel, Field
from abc import abstractmethod


class Citation(BaseModel):
    title: str | None = None
    snippet: str | None = None
    link: str
    updated_at: str | None = None


class Score(BaseModel):
    recall: float
    rerank: float


class BaseRetrieval(BaseModel):
    score: Score = Field(default=None)

    @abstractmethod
    def to_prompt(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def to_citation(self) -> Citation:
        raise NotImplementedError
