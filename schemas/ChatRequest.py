from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="The user's chat message.",
        examples=["Where is my order 1206573?"],
    )
    conversation_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Client-generated ID identifying the conversation thread, "
        "so the agent can recall earlier messages in the same chat.",
        examples=["8f14e45f-ceea-4d1e-8f9a-3f7d6a5c3b21"],
    )