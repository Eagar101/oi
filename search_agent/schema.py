"""Search Agent 的JSON输出模型定义"""

from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    """单条搜索来源"""

    title: str = Field(..., description="搜索结果标题")
    url: str = Field(..., description="搜索结果链接")
    snippet: str = Field(..., description="搜索结果摘要片段")


class SearchRound(BaseModel):
    """单轮搜索记录"""

    query: str = Field(..., description="该轮搜索的查询词")
    results_count: int = Field(..., description="该轮返回的结果数")
    is_deep_dive: bool = Field(default=False, description="是否为深度搜索轮次")


class SearchOutput(BaseModel):
    """Search Agent的标准输出结构"""

    query: str = Field(..., description="主搜索查询词")
    summary: str = Field(..., description="LLM对搜索结果的综合摘要")
    sources: list[SearchResult] = Field(..., description="去重合并后的搜索来源列表")
    raw_keywords: list[str] = Field(..., description="来自planner的原始关键词")
    search_rounds: list[SearchRound] = Field(
        default_factory=list, description="搜索轮次记录"
    )
