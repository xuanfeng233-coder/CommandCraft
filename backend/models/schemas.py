"""Pydantic data models for API request/response."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# --- Chat Request / Response ---

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="用户输入的自然语言消息")
    session_id: str | None = Field(None, description="会话 ID，为空则创建新会话")
    task_id: str | None = Field(None, description="指定回答哪个 paused task")


class CommandOutput(BaseModel):
    command: str = Field(..., description="完整命令字符串")
    explanation: str = Field("", description="命令各部分解释")
    variants: list[str] = Field(default_factory=list, description="可选变体写法")
    warnings: list[str] = Field(default_factory=list, description="注意事项")


class QuestionOption(BaseModel):
    value: str
    label: str


class ParameterQuestion(BaseModel):
    param: str = Field(..., description="参数名")
    question: str = Field(..., description="面向用户的自然语言提问")
    options: list[QuestionOption] = Field(default_factory=list)
    default: str | None = None


# --- Project Mode Models ---

class CommandBlockEntry(BaseModel):
    type: str = Field(..., description="impulse | chain | repeating")
    conditional: bool = False
    needs_redstone: bool = False
    command: str = ""
    comment: str = ""


class ProjectTask(BaseModel):
    task_id: str
    description: str = ""
    commands: list[str] = Field(default_factory=list)
    command_blocks: list[CommandBlockEntry] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)


class ProjectPhase(BaseModel):
    phase_name: str
    description: str = ""
    tasks: list[ProjectTask] = Field(default_factory=list)


class BlockPosition(BaseModel):
    x: int = 0
    y: int = 0
    z: int = 0


class BlockLayoutEntry(BaseModel):
    position: BlockPosition = Field(default_factory=BlockPosition)
    direction: str = "east"
    block_type: str = "chain_command_block"
    conditional: bool = False
    auto: bool = True
    command: str = ""
    custom_name: str = ""
    group_id: str = ""


class BlockGroup(BaseModel):
    group_id: str
    name: str = ""
    description: str = ""
    trigger_method: str = ""


class BlockDimensions(BaseModel):
    width: int = 0
    height: int = 0
    depth: int = 0


class ProjectResult(BaseModel):
    project_name: str = ""
    overview: str = ""
    phases: list[ProjectPhase] = Field(default_factory=list)
    layout: list[BlockLayoutEntry] = Field(default_factory=list)
    groups: list[BlockGroup] = Field(default_factory=list)
    dimensions: BlockDimensions = Field(default_factory=BlockDimensions)


class ChatResponse(BaseModel):
    type: str = Field(..., description="single_command | conversation | project | error")
    command: CommandOutput | None = None
    questions: list[ParameterQuestion] | None = None
    project: ProjectResult | None = None
    message: str | None = Field(None, description="通用文本消息")
    thinking: str | None = Field(None, description="思维链内容")
    session_id: str | None = None


# --- SSE Event Payloads ---

class SSEEvent(BaseModel):
    event: str = Field(..., description="thinking | content | done | error")
    data: dict[str, Any] = Field(default_factory=dict)


# --- Task Decomposition Models ---

class TaskDefinition(BaseModel):
    task_id: str
    description: str = Field("", description="简短人类可读描述")
    user_request: str = Field("", description="自包含的请求文本")
    recommended_commands: list[str] = Field(default_factory=list)
    output_type: str = Field("simple_command", description="simple_command | execute_chain | rawtext | selector | project")
    execution_mode: str = Field("continuous", description="continuous | once")
    depends_on: list[str] = Field(default_factory=list, description="此任务依赖的前置任务 ID 列表")


class DecompositionResult(BaseModel):
    project_name: str = ""
    overview: str = ""
    tasks: list[TaskDefinition] = Field(default_factory=list)
    is_single_task: bool = False


# --- Agent Internal Models ---

class AnalysisResult(BaseModel):
    mode: str = Field(..., description="single_command | edit_command | project_plan")
    summary: str = Field(..., description="需求摘要")
    relevant_commands: list[str] = Field(default_factory=list)
    complexity: str = Field("simple", description="simple | moderate | complex")


class GenerationResult(BaseModel):
    type: str = Field("single_command")
    command: CommandOutput | None = None
    questions: list[ParameterQuestion] | None = None
    project: ProjectResult | None = None
    message: str | None = None
    thinking: str | None = None


# --- Health ---

class HealthResponse(BaseModel):
    status: str  # ok | not_configured | api_unreachable | model_unavailable
    provider_name: str = ""
    model_name: str = ""
    rag_index_status: dict[str, bool] | None = None
