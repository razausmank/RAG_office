from pydantic import BaseModel, Field 

class ChatRequest(BaseModel):
    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="The user's chat message.",
        examples=["Where is my order ORD-00042?"],
    )