from pydantic import BaseModel


class OpenAIMessage(BaseModel):
    role: str
    content: str


class Message(BaseModel):
    conversation_id: str
    message_id: str
    message: OpenAIMessage
