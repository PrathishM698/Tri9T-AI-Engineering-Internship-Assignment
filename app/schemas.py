from pydantic import BaseModel, ConfigDict, Field
from typing import Any

class NodeSummary(BaseModel):
    id: int
    heading: str
    level: int
    parent_id: int | None
    content_hash: str
    node_type: str
    model_config = ConfigDict(from_attributes=True)

class NodeDetail(NodeSummary):
    version_id: int
    logical_key: str
    body_text: str
    children: list[NodeSummary] = Field(default_factory=list)

class SelectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=250)
    node_ids: list[int] = Field(min_length=1)

class GenerateRequest(BaseModel):
    selection_id: int
    regenerate: bool = False

class TestCase(BaseModel):
    title: str = Field(min_length=3)
    requirement: str = Field(min_length=3)
    preconditions: list[str] = Field(default_factory=list)
    steps: list[str] = Field(min_length=1)
    expected_result: str = Field(min_length=3)
    risk: str = "medium"

class GenerationOutput(BaseModel):
    test_cases: list[TestCase] = Field(min_length=3, max_length=5)

class IngestResponse(BaseModel):
    document_key: str
    version_label: str
    version_id: int
    node_count: int
    top_level_count: int
    message: str
