from pydantic import BaseModel, Field


class Citation(BaseModel):
    title: str
    snippet: str
    link: str


class Score(BaseModel):
    recall: float
    rerank: float


class BaseRetrieval(BaseModel):
    score: Score = Field(default=None)

    def to_prompt(self) -> str:
        raise NotImplementedError

    def to_citation(self) -> Citation:
        raise NotImplementedError
