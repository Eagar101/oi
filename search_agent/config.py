"""Search Agent 的配置管理"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class SearchConfig:
    """从环境变量读取配置，与planner共享同一套API配置"""

    api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    base_url: str = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    model: str = os.getenv("PLANNER_MODEL", "qianfan-code-latest")
    temperature: float = float(os.getenv("PLANNER_TEMPERATURE", "0.3"))
    max_tokens: int = int(os.getenv("PLANNER_MAX_TOKENS", "2048"))
    max_results: int = int(os.getenv("SEARCH_MAX_RESULTS", "5"))
    deep_search: bool = os.getenv("SEARCH_DEEP_SEARCH", "true").lower() == "true"
    max_rounds: int = int(os.getenv("SEARCH_MAX_ROUNDS", "3"))

    def validate(self) -> None:
        if not self.api_key:
            raise ValueError(
                "未设置ANTHROPIC_API_KEY。请创建.env文件或在环境变量中设置。"
            )
