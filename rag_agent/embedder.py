"""嵌入模型单例：fastembed 本地 ONNX 推理"""

import threading

import numpy as np

from .config import RAGConfig

_embedder = None
_embedder_lock = threading.Lock()
_embedder_model: str | None = None


def get_embedder(config: RAGConfig | None = None):
    """单例获取 fastembed TextEmbedding，避免重复加载模型"""
    global _embedder, _embedder_model
    cfg = config or RAGConfig()
    with _embedder_lock:
        if _embedder is None or _embedder_model != cfg.embed_model:
            from fastembed import TextEmbedding

            print(f"  加载嵌入模型: {cfg.embed_model}（首次需下载，请稍候）...")
            _embedder = TextEmbedding(model_name=cfg.embed_model)
            _embedder_model = cfg.embed_model
    return _embedder


def embed(texts: list[str], config: RAGConfig | None = None) -> list[np.ndarray]:
    """对一批文本生成向量，返回归一化的 numpy 数组列表"""
    if not texts:
        return []
    model = get_embedder(config)
    vectors = list(model.embed(texts))
    out = []
    for v in vectors:
        arr = np.asarray(v, dtype=np.float32)
        norm = np.linalg.norm(arr)
        if norm > 0:
            arr = arr / norm
        out.append(arr)
    return out


def embed_to_bytes(texts: list[str], config: RAGConfig | None = None) -> list[bytes]:
    """嵌入并序列化为 bytes（用于 SQLite BLOB 存储）"""
    return [v.tobytes() for v in embed(texts, config)]
