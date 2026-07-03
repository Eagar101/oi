"""FastAPI后端配置"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class APIConfig:
    """FastAPI后端配置"""

    # JWT配置
    jwt_secret: str = os.getenv("JWT_SECRET", "change-me-in-production")
    jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    jwt_expire_minutes: int = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))

    # 数据库
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./research.db")

    # 并发控制
    max_concurrent_per_user: int = int(os.getenv("MAX_CONCURRENT_PER_USER", "2"))
    max_concurrent_total: int = int(os.getenv("MAX_CONCURRENT_TOTAL", "10"))

    # 持久化目录
    reports_dir: str = os.getenv("WRITE_OUTPUT_DIR", "./reports")
    data_dir: str = os.getenv("SUMMARY_PERSIST_DIR", "./data")
