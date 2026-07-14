"""RAG Agent 的数据模型定义"""

from pydantic import BaseModel, Field


class Chunk(BaseModel):
    """文本切片"""

    seq: int = Field(..., description="切片序号")
    content: str = Field(..., description="切片内容")
    token_count: int = Field(0, description="token 数（近似）")


class ChatSource(BaseModel):
    """问答引用来源"""

    document_id: int
    filename: str
    snippet: str = Field(..., description="命中的文本片段")
    score: float = Field(..., description="相似度分数")


class ChatAnswer(BaseModel):
    """RAG 问答结果"""

    answer: str
    sources: list[ChatSource] = Field(default_factory=list)
