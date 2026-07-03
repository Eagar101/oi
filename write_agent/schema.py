"""Write Agent 的数据模型定义"""

from pydantic import BaseModel, Field

from planner_agent.schema import PlannerOutput
from summary_agent.schema import SummaryOutput


class WriteInput(BaseModel):
    """Write Agent 的输入数据，包含前三个Agent的输出"""

    planner: PlannerOutput = Field(..., description="Planner Agent的输出")
    search_summary: str = Field(..., description="Search Agent的摘要文本")
    summary: SummaryOutput = Field(..., description="Summary Agent的输出")

    class Config:
        arbitrary_types_allowed = True