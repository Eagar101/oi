"""RAG Agent 的配置管理"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class RAGConfig:
    """从环境变量读取配置，复用 ANTHROPIC_* 调 LLM，本地 fastembed 做嵌入"""

    # LLM（复用其他 agent 的配置）
    api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    base_url: str = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    model: str = os.getenv("PLANNER_MODEL", "qianfan-code-latest")
    temperature: float = float(os.getenv("RAG_TEMPERATURE", "0.3"))
    max_tokens: int = int(os.getenv("RAG_MAX_TOKENS", "2048"))

    # 嵌入与切片
    embed_model: str = os.getenv("RAG_EMBED_MODEL", "BAAI/bge-small-zh-v1.5")
    chunk_size: int = int(os.getenv("RAG_CHUNK_SIZE", "500"))
    chunk_overlap: int = int(os.getenv("RAG_CHUNK_OVERLAP", "100"))
    top_k: int = int(os.getenv("RAG_TOP_K", "5"))
    doc_summary_tokens: int = int(os.getenv("RAG_DOC_SUMMARY_TOKENS", "600"))

    def validate(self) -> None:
        if not self.api_key:
            raise ValueError("未设置ANTHROPIC_API_KEY")
