from typing import Literal, Optional, List
from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000, description="User question")
    session_id: Optional[str] = Field(
        None,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Alphanumeric session ID for conversation memory",
    )
    agent: Optional[str] = Field(
        None,
        max_length=64,
        description="Optional forced sub-agent name ('auto' or specific registered agent e.g. 'doc_agent', 'db_agent', 'compliance_agent')",
    )


class AgentInfo(BaseModel):
    name: str
    display_name: str
    description: str
    version: str = "1.0.0"


class AgentsListResponse(BaseModel):
    agents: List[AgentInfo]


class SyncTableRequest(BaseModel):
    table_name: str
    text_columns: Optional[List[str]] = None
    title_column: Optional[str] = None
    id_column: Optional[str] = None


class TestQueryRequest(BaseModel):
    query: str


class FeedbackRequest(BaseModel):
    question: str = Field("", max_length=4000)
    feedback: Literal["positive", "negative"]
    comment: str = Field("", max_length=2000)
    # The agent whose answer is rated (the answer's active_agent), for the per-agent statistics
    agent: str = Field("", max_length=64, pattern=r"^[a-z0-9_]*$")


class DocumentAccessRequest(BaseModel):
    groups: List[str] = Field(
        default_factory=list, description="User groups allowed to search the document; empty: everyone"
    )


RequestStatus = Literal["open", "in_progress", "resolved", "rejected", "cancelled"]


class ServiceRequestCreate(BaseModel):
    category: str = Field(..., min_length=1, max_length=40)
    title: str = Field(..., min_length=3, max_length=200)
    description: str = Field("", max_length=4000)


class ServiceRequestUpdate(BaseModel):
    status: RequestStatus
    resolution_note: str = Field("", max_length=2000)
