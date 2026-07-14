"""RAG Agent 核心：文档摄入、文档摘要、RAG 问答"""

import hashlib
import json
import time

import anthropic

from .chunker import recursive_split
from .config import RAGConfig
from .embedder import embed, embed_to_bytes
from .parser import parse_file
from .schema import ChatAnswer, ChatSource

from api import db

SUMMARIZE_DOC_PROMPT = """\
你是一个文档摘要专家。请对以下文档生成一份结构化摘要，用于辅助后续研究规划。

要求：
- 约{max_tokens}字以内
- 提取文档的核心主题、关键论点、重要事实和数据
- 保留专有名词和关键技术术语
- 不要编造文档中没有的信息
- 只输出摘要文本，不要输出其他内容

文档内容：
{content}
"""

RAG_ANSWER_PROMPT = """\
你是一个文档问答助手。请基于下方检索到的文档片段回答用户问题。

当前日期：{current_date}

## 检索到的文档片段
{context}

## 用户问题
{question}

## 要求
- 只基于上方片段作答，不要编造片段中没有的信息
- 如果片段不足以回答，说明"根据已有文档无法完整回答"并给出最接近的内容
- 回答简洁清晰，300字以内
- 可适当引用片段中的原话
"""


def _call_with_retry(client: anthropic.Anthropic, config: RAGConfig, **kwargs) -> str:
    """带重试的 LLM 调用"""
    for attempt in range(3):
        try:
            resp = client.messages.create(
                model=config.model,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                **kwargs,
            )
            text = next(
                (b.text for b in resp.content if b.type == "text"), None
            )
            return text.strip() if text else ""
        except anthropic.RateLimitError:
            wait = 15 * (attempt + 1)
            print(f"  速率限制，等待{wait}秒后重试...")
            time.sleep(wait)
    raise RuntimeError("连续3次触发速率限制，请稍后再试")


class RAGAgent:
    """文档摄入 + RAG 问答"""

    def __init__(self, config: RAGConfig | None = None) -> None:
        self.config = config or RAGConfig()
        self.config.validate()
        self.client = anthropic.Anthropic(
            api_key=self.config.api_key, base_url=self.config.base_url,
        )

    # ---------- 摄入 ----------
    def ingest(self, user_id: int, filename: str, raw: bytes) -> dict:
        """解析→切片→嵌入→入库。返回 {doc_id, filename, char_count, chunk_count}"""
        text = parse_file(filename, raw)
        if not text:
            raise ValueError("文档内容为空")

        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

        # 已有同内容文档则跳过重复嵌入
        existing = db.find_document_by_hash(user_id, content_hash)
        if existing:
            return {
                "doc_id": existing["id"],
                "filename": existing["filename"],
                "char_count": existing["char_count"],
                "chunk_count": db.count_chunks(existing["id"]),
                "deduplicated": True,
            }

        doc_id = db.create_document(
            user_id, filename, text, content_hash,
        )

        chunks = recursive_split(
            text, self.config.chunk_size, self.config.chunk_overlap,
        )
        if not chunks:
            return {"doc_id": doc_id, "filename": filename,
                    "char_count": len(text), "chunk_count": 0}

        # 批量嵌入
        contents = [c.content for c in chunks]
        vec_bytes = embed_to_bytes(contents, self.config)

        db.add_chunks(
            doc_id,
            [(c.seq, c.content, vb) for c, vb in zip(chunks, vec_bytes)],
        )
        return {
            "doc_id": doc_id,
            "filename": filename,
            "char_count": len(text),
            "chunk_count": len(chunks),
            "deduplicated": False,
        }

    # ---------- 文档摘要（注入 Planner）----------
    def summarize_document(self, doc_id: int) -> str:
        """生成文档摘要，带缓存"""
        doc = db.get_document(doc_id)
        if not doc:
            return ""
        if doc.get("summary"):
            return doc["summary"]

        content = doc["content"]
        # 长文档只取前 8000 字做摘要，避免超 token
        truncated = content[:8000]
        prompt = SUMMARIZE_DOC_PROMPT.format(
            max_tokens=self.config.doc_summary_tokens, content=truncated,
        )
        summary = _call_with_retry(
            self.client, self.config, messages=[{"role": "user", "content": prompt}],
        )
        if summary:
            db.update_document_summary(doc_id, summary)
        return summary or "（摘要生成失败）"

    def build_doc_context(self, doc_ids: list[int]) -> str:
        """为 Planner 拼接多文档摘要上下文"""
        if not doc_ids:
            return ""
        parts = []
        for did in doc_ids:
            doc = db.get_document(did)
            if not doc:
                continue
            summary = self.summarize_document(did)
            parts.append(f"[文档: {doc['filename']}]\n{summary}")
        if not parts:
            return ""
        return "\n\n[用户上传文档摘要]\n" + "\n\n".join(parts) + "\n"

    # ---------- RAG 问答 ----------
    def answer(self, user_id: int, question: str,
               doc_ids: list[int] | None = None) -> ChatAnswer:
        """向量检索 + LLM 生成回答"""
        q_vec = embed([question], self.config)
        if not q_vec:
            return ChatAnswer(answer="问题嵌入失败，无法检索。", sources=[])
        q_vec = q_vec[0]

        hits = db.search_similar(
            user_id, q_vec, top_k=self.config.top_k, doc_ids=doc_ids,
        )
        if not hits:
            return ChatAnswer(
                answer="未找到相关文档片段。请先上传文档或扩大检索范围。", sources=[],
            )

        context_parts = []
        sources = []
        for i, h in enumerate(hits, 1):
            doc = db.get_document(h["document_id"]) or {"filename": "未知"}
            context_parts.append(
                f"[片段{i}] 来源: {doc['filename']}\n{h['content']}"
            )
            sources.append(ChatSource(
                document_id=h["document_id"],
                filename=doc["filename"],
                snippet=h["content"][:200],
                score=float(h["score"]),
            ))

        prompt = RAG_ANSWER_PROMPT.format(
            current_date=time.strftime("%Y年%m月%d日"),
            context="\n\n".join(context_parts),
            question=question,
        )
        answer_text = _call_with_retry(
            self.client, self.config, messages=[{"role": "user", "content": prompt}],
        )
        return ChatAnswer(
            answer=answer_text or "（回答生成失败）", sources=sources,
        )
