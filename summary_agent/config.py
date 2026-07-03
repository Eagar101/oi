"""Summary Agent 的配置管理"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class SummaryConfig:
    """从环境变量读取配置"""

    api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    base_url: str = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    model: str = os.getenv("PLANNER_MODEL", "qianfan-code-latest")
    temperature: float = float(os.getenv("SUMMARY_TEMPERATURE", "0.3"))
    max_tokens: int = int(os.getenv("SUMMARY_MAX_TOKENS", "4096"))
    persist_dir: str = os.getenv("SUMMARY_PERSIST_DIR", "./data")

    def validate(self) -> None:
        if not self.api_key:
            raise ValueError("未设置ANTHROPIC_API_KEY")
