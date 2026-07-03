"""JSON文件持久化模块：存储知识图谱节点和摘要"""

import json
import os
from datetime import datetime

from .schema import SummaryOutput


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def save(data: SummaryOutput, persist_dir: str, query: str = "") -> str:
    """将SummaryOutput持久化为JSON文件，返回文件路径"""
    _ensure_dir(persist_dir)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_query = query[:20].replace(" ", "_") if query else "unnamed"
    filename = f"summary_{safe_query}_{timestamp}.json"
    filepath = os.path.join(persist_dir, filename)

    payload = {
        "meta": {
            "created_at": datetime.now().isoformat(),
            "query": query,
            "node_count": len(data.nodes),
            "edge_count": len(data.edges),
        },
        "data": data.model_dump(),
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return filepath


def load(filepath: str) -> SummaryOutput:
    """从JSON文件读取SummaryOutput"""
    with open(filepath, encoding="utf-8") as f:
        payload = json.load(f)

    return SummaryOutput.model_validate(payload["data"])
