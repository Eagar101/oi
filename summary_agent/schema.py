"""Summary Agent 的数据模型定义"""

from pydantic import BaseModel, Field


class NodeSource(BaseModel):
    """节点的引用来源"""

    title: str
    url: str
    snippet: str


class RemovedEntry(BaseModel):
    """被移除的搜索结果"""

    title: str
    reason: str


class MergedEntry(BaseModel):
    """合并操作记录"""

    from_titles: list[str]
    to_title: str
    reason: str


class FilteringLog(BaseModel):
    """CoT清洗日志"""

    removed_count: int = 0
    removed_reasons: list[RemovedEntry] = Field(default_factory=list)
    merged_entries: list[MergedEntry] = Field(default_factory=list)
    consistency_issues: list[str] = Field(default_factory=list)


class GraphNode(BaseModel):
    """知识图谱节点：每个关键词对应一个节点"""

    id: str = Field(..., description="节点ID，格式为 keyword_N")
    keyword: str = Field(..., description="关键词")
    summary: str = Field(..., description="该关键词的深度摘要")
    sources: list[NodeSource] = Field(default_factory=list, description="引用来源")
    related_todo_ids: list[int] = Field(default_factory=list, description="关联的TODO编号")


class GraphEdge(BaseModel):
    """知识图谱边：关键词之间的关系"""

    from_id: str = Field(..., description="起始节点ID")
    to_id: str = Field(..., description="目标节点ID")
    relation: str = Field(..., description="关系描述，如 depends_on / enables / relates_to")


class SummaryOutput(BaseModel):
    """Summary Agent 的完整输出"""

    nodes: list[GraphNode] = Field(..., description="知识图谱节点列表")
    edges: list[GraphEdge] = Field(..., description="知识图谱边列表")
    global_summary: str = Field(..., description="全局总结")
    filtering_log: FilteringLog = Field(
        default_factory=FilteringLog,
        description="CoT数据清洗日志",
    )
