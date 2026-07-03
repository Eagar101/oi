"""Planner Agent 的JSON输出模型定义"""

from pydantic import BaseModel, Field


class TodoItem(BaseModel):
    """单个TODO条目"""

    id: int = Field(..., description="TODO条目的唯一编号")
    task: str = Field(..., description="具体的待办任务描述")
    priority: str = Field(..., description="优先级: high / medium / low")


class PlannerOutput(BaseModel):
    """Planner Agent的标准输出结构"""

    keywords: list[str] = Field(..., description="从输入中提取的关键词列表")
    summary: str = Field(..., description="对用户输入的一句话总结")
    todos: list[TodoItem] = Field(..., description="拆解后的TODO列表")
