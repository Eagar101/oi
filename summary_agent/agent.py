"""Summary Agent 核心逻辑：CoT数据清洗 + 归纳总结 + 构建知识图谱节点"""

import json
import time

import anthropic

from .config import SummaryConfig
from .persist import save
from .schema import (
    FilteringLog,
    GraphEdge,
    GraphNode,
    MergedEntry,
    NodeSource,
    RemovedEntry,
    SummaryOutput,
)

# CoT数据清洗提示词
COT_CLEAN_PROMPT = """\
你是一个信息质量分析专家，需要运用思维链(Chain of Thought)对搜索结果进行数据清洗。

## 重要上下文
当前日期：{current_date}
在判断时效性时，请以该日期为基准，不要将过去的日期误判为未来时间。

## 任务
分析以下搜索结果，进行内容质量分析，过滤无效信息。

## 输入数据
关键词列表：{keywords}
搜索结果（原始）：
{search_results}

## 清洗要求（运用思维链逐步推理）
1. **相关性过滤**：对于每个搜索结果，分析其标题和片段内容与关键词列表的相关性。移除完全不相关或仅有微弱关联的结果。
2. **逻辑一致性检查**：检查搜索结果之间是否存在明显的事实矛盾或逻辑不一致。识别并标记可疑信息。注意：基于当前日期({current_date})判断时间引用是否合理，不要将过去的时间误判为未来。
3. **信息去重合并**：识别内容高度相似或重复的搜索结果，将其合并为代表性条目。
4. **内容质量分析**：评估每个结果的信息质量（完整性、准确性、时效性）。

## 输出格式
请输出JSON对象，包含两个字段：
1. `cleaned_sources`: 清洗后的搜索结果列表，每个条目包含`title`、`url`、`snippet`
2. `filtering_log`: 清洗过程记录，包含：
   - `removed_count`: 被移除的结果数量
   - `removed_reasons`: 每个被移除结果的原因（如"不相关"、"低质量"、"重复"）
   - `merged_entries`: 合并操作记录
   - `consistency_issues`: 发现的逻辑不一致问题

示例格式：
{{
  "cleaned_sources": [
    {{"title": "...", "url": "...", "snippet": "..."}}
  ],
  "filtering_log": {{
    "removed_count": 2,
    "removed_reasons": [
      {{"title": "...", "reason": "与关键词无关"}},
      {{"title": "...", "reason": "内容质量低"}}
    ],
    "merged_entries": [
    ],
    "consistency_issues": []
  }}
}}

请严格输出JSON，不要输出其他内容。
"""

# 批量关键词摘要（一次调用）
BATCH_SUMMARY_PROMPT = """\
你是一个信息归纳专家。请对以下每个关键词的搜索结果进行深度摘要。

搜索结果：
{search_results}

TODO列表：
{todos}

关键词列表：{keywords}

请输出JSON对象，key为关键词，value为200字以内的摘要。格式：
{{"关键词1": "摘要1", "关键词2": "摘要2", ...}}

要求：提炼核心要点和可操作建议，保留关键事实。只输出JSON，不要输出其他内容。
"""

# 构建知识图谱关系的prompt
GRAPH_PROMPT = """\
你是一个知识图谱构建专家。根据以下关键词和摘要，分析关键词之间的关系。

关键词列表：{keywords}

摘要：
{summaries}

请输出JSON数组，描述关键词之间的关系。格式：
[
  {{"from": "关键词A", "to": "关键词B", "relation": "关系描述"}}
]

关系类型参考：depends_on（依赖）、enables（使能）、relates_to（相关）、precedes（先于）
只输出JSON数组，不要输出其他内容。
"""

# 全局总结的prompt
GLOBAL_SUMMARY_PROMPT = """\
你是一个项目规划总结专家。请根据以下各关键词的摘要，生成一段全局总结。

原始意图：{original_summary}
各关键词摘要：
{keyword_summaries}

要求：
- 300字以内
- 涵盖所有关键词的核心要点
- 突出关键依赖和风险
- 为后续报告书写提供结构化信息
只输出总结文本，不要输出其他内容。
"""


def _extract_text(response: anthropic.types.Message) -> str:
    """从Anthropic响应中提取文本（跳过ThinkingBlock）"""
    for block in response.content:
        if block.type == "text":
            return block.text
    raise ValueError("模型未返回文本内容")


def _call_with_retry(client: anthropic.Anthropic, config: SummaryConfig, messages: list[dict]) -> str:
    """带重试和间隔的LLM调用"""
    for attempt in range(3):
        try:
            resp = client.messages.create(
                model=config.model,
                max_tokens=config.max_tokens,
                temperature=config.temperature,
                messages=messages,
            )
            return _extract_text(resp).strip()
        except anthropic.RateLimitError:
            wait = 30 * (attempt + 1)
            print(f"  速率限制，等待{wait}秒后重试...")
            time.sleep(wait)
    raise RuntimeError("连续3次触发速率限制，请稍后再试")


class SummaryAgent:
    """归纳总结搜索内容，构建知识图谱节点，持久化为JSON"""

    def __init__(self, config: SummaryConfig | None = None) -> None:
        self.config = config or SummaryConfig()
        self.config.validate()
        self.client = anthropic.Anthropic(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
        )

    def run(self, search_json: str) -> SummaryOutput:
        """接收Search Agent的JSON输出，返回SummaryOutput"""
        search_data = json.loads(search_json)

        keywords = search_data.get("raw_keywords", [])
        sources = search_data.get("sources", [])
        todos = search_data.get("todos", [])

        # 0. CoT数据清洗（1次LLM调用）
        cleaned_sources, filtering_log = self._cot_clean(keywords, sources)

        # 1. 批量关键词摘要（1次LLM调用，使用清洗后数据）
        time.sleep(2)
        summaries = self._batch_summarize(keywords, cleaned_sources, todos)
        nodes = self._build_nodes(keywords, summaries, cleaned_sources, todos)

        # 2. 构建知识图谱关系（1次LLM调用）
        time.sleep(2)
        edges = self._build_edges(keywords, nodes)

        # 3. 全局总结（1次LLM调用）
        time.sleep(2)
        global_summary = self._global_summary(
            search_data.get("summary", ""), nodes
        )

        return SummaryOutput(
            nodes=nodes,
            edges=edges,
            global_summary=global_summary,
            filtering_log=filtering_log,
        )

    def run_and_save(self, search_json: str, query: str = "") -> tuple[SummaryOutput, str]:
        """执行总结并持久化，返回(结果, 文件路径)"""
        result = self.run(search_json)
        filepath = save(result, self.config.persist_dir, query)
        return result, filepath

    def run_as_json(self, search_json: str) -> str:
        """执行总结，返回JSON字符串"""
        result = self.run(search_json)
        return result.model_dump_json(indent=2, ensure_ascii=False)

    def _cot_clean(
        self, keywords: list[str], sources: list[dict],
    ) -> tuple[list[dict], FilteringLog]:
        """CoT数据清洗：相关性过滤、逻辑一致性检查、去重合并"""
        if not sources:
            return [], FilteringLog()

        current_date = time.strftime("%Y年%m月%d日")

        sources_text = "\n".join(
            f"- [{i + 1}] 标题: {s.get('title', '')}\n"
            f"    URL: {s.get('url', '')}\n"
            f"    摘要: {s.get('snippet', '')}"
            for i, s in enumerate(sources)
        )
        prompt = COT_CLEAN_PROMPT.format(
            current_date=current_date,
            keywords=json.dumps(keywords, ensure_ascii=False),
            search_results=sources_text,
        )
        raw = _call_with_retry(
            self.client, self.config, [{"role": "user", "content": prompt}]
        )
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # 降级：返回原始数据，空日志
            return sources, FilteringLog(
                consistency_issues=["CoT清洗结果解析失败，使用原始数据"],
            )

        cleaned = data.get("cleaned_sources", [])
        log_data = data.get("filtering_log", {})

        log = FilteringLog(
            removed_count=log_data.get("removed_count", 0),
            removed_reasons=[
                RemovedEntry(title=r.get("title", ""), reason=r.get("reason", ""))
                for r in log_data.get("removed_reasons", [])
            ],
            merged_entries=[
                MergedEntry(
                    from_titles=m.get("from", []),
                    to_title=m.get("to", ""),
                    reason=m.get("reason", ""),
                )
                for m in log_data.get("merged_entries", [])
            ],
            consistency_issues=log_data.get("consistency_issues", []),
        )

        # 清洗后为空则回退到原始数据
        if not cleaned:
            return sources, FilteringLog(
                consistency_issues=["清洗后无有效结果，回退到原始数据"],
            )

        return cleaned, log

    def _batch_summarize(
        self,
        keywords: list[str],
        sources: list[dict],
        todos: list[dict],
    ) -> dict[str, str]:
        """一次LLM调用，批量生成所有关键词的摘要"""
        sources_text = "\n".join(
            f"- [{s.get('title', '')}] {s.get('snippet', '')}" for s in sources
        )
        todos_text = "\n".join(
            f"- [{t.get('id')}] {t.get('task')} (优先级: {t.get('priority')})"
            for t in todos
        )
        prompt = BATCH_SUMMARY_PROMPT.format(
            keywords=json.dumps(keywords, ensure_ascii=False),
            search_results=sources_text or "（无搜索结果）",
            todos=todos_text or "（无TODO）",
        )
        raw = _call_with_retry(
            self.client, self.config, [{"role": "user", "content": prompt}]
        )
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {kw: "（摘要生成失败）" for kw in keywords}

    def _build_nodes(
        self,
        keywords: list[str],
        summaries: dict[str, str],
        sources: list[dict],
        todos: list[dict],
    ) -> list[GraphNode]:
        """将摘要组装为知识图谱节点"""
        nodes = []
        for i, kw in enumerate(keywords):
            related_ids = [t["id"] for t in todos if kw in t.get("task", "")]
            node_sources = [
                NodeSource(
                    title=s.get("title", ""),
                    url=s.get("url", ""),
                    snippet=s.get("snippet", ""),
                )
                for s in sources
            ]
            nodes.append(
                GraphNode(
                    id=f"keyword_{i + 1}",
                    keyword=kw,
                    summary=summaries.get(kw, "（无摘要）"),
                    sources=node_sources,
                    related_todo_ids=related_ids,
                )
            )
        return nodes

    def _build_edges(
        self, keywords: list[str], nodes: list[GraphNode]
    ) -> list[GraphEdge]:
        """调用LLM分析关键词间关系，构建图谱边"""
        if len(keywords) < 2:
            return []

        summaries_text = "\n".join(
            f"- {n.keyword}: {n.summary}" for n in nodes
        )
        prompt = GRAPH_PROMPT.format(
            keywords=json.dumps(keywords, ensure_ascii=False),
            summaries=summaries_text,
        )
        raw = _call_with_retry(
            self.client, self.config, [{"role": "user", "content": prompt}]
        )
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

        try:
            relations = json.loads(raw)
        except json.JSONDecodeError:
            return []

        kw_to_id = {n.keyword: n.id for n in nodes}

        edges = []
        for r in relations:
            from_id = kw_to_id.get(r.get("from", ""))
            to_id = kw_to_id.get(r.get("to", ""))
            if from_id and to_id:
                edges.append(
                    GraphEdge(
                        from_id=from_id,
                        to_id=to_id,
                        relation=r.get("relation", "relates_to"),
                    )
                )
        return edges

    def _global_summary(
        self, original_summary: str, nodes: list[GraphNode]
    ) -> str:
        """调用LLM生成全局总结"""
        kw_summaries = "\n".join(
            f"- {n.keyword}: {n.summary}" for n in nodes
        )
        prompt = GLOBAL_SUMMARY_PROMPT.format(
            original_summary=original_summary,
            keyword_summaries=kw_summaries,
        )
        return _call_with_retry(
            self.client, self.config, [{"role": "user", "content": prompt}]
        )
