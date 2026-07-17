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
你的目标是严格剔除"泛泛而谈"和"几乎完全无关"的内容，只保留对用户意图有实质信息价值的结果。

## 重要上下文
当前日期：{current_date}
在判断时效性时，请以该日期为基准，不要将过去的日期误判为未来时间。

## 用户意图（这是判定相关性的首要基准）
{intent}

## 关联关键词（辅助参考，非判定主体）
关键词列表：{keywords}

## 任务
逐条分析以下搜索结果，判定是否保留。务必从严。

## 输入数据
搜索结果（原始）：
{search_results}

## 相关性判定标准（核心，从严执行）
对每条结果按下述三类归类，只保留"高度相关"：
1. **几乎完全无关** → 必须移除。判定依据（满足任一即归此类）：
   - 标题/片段未提及用户意图涉及的主题、对象或领域
   - 仅因某个词偶然命中而内容讲的是完全不同的事
   - 是导航页、广告页、排行榜列表、商品列表、404/防爬验证等无信息量页面
2. **泛泛而谈** → 必须移除。判定依据：
   - 全是"很好用""很重要""推荐""值得一试"之类评论性套话，无具体事实、数据、步骤、对比或技术细节
   - 仅为通用常识或百科式百科定义堆砌，对"用户意图"无可推进认知的新信息
   - 内容空洞、可套用于任何主题的模板化文字
3. **高度相关** → 保留。判定依据（需满足）：
   - 紧扣用户意图，且提供具体事实、数据、方法步骤、技术原理、对比分析、案例或可操作建议中至少一项
   - 宁可移除存疑，也不要保留泛泛之谈

## 其他清洗要求（运用思维链逐步推理）
1. **逻辑一致性检查**：检查结果之间是否存在明显事实矛盾或逻辑不一致，标记可疑信息。基于当前日期({current_date})判断时间引用是否合理，不要把过去时间误判为未来。
2. **信息去重合并**：内容高度相似或重复的，合并为代表性条目。
3. **内容质量分析**：评估完整性、准确性、时效性，优先保留信息密度高的条目。

## 输出格式
请输出JSON对象，包含两个字段：
1. `cleaned_sources`: 清洗后的搜索结果列表，每个条目包含`title`、`url`、`snippet`
2. `filtering_log`: 清洗过程记录，包含：
   - `removed_count`: 被移除的结果数量
   - `removed_reasons`: 每个被移除结果的原因，使用具体类别：`几乎完全无关` / `泛泛而谈` / `低质量` / `重复`
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
      {{"title": "...", "reason": "泛泛而谈"}},
      {{"title": "...", "reason": "几乎完全无关"}}
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
        # 用户意图：首选 Search 的 query（即 Planner 的完整意图句），次选综合摘要
        intent = search_data.get("summary", "") or search_data.get("query", "")

        # 0. CoT数据清洗（1次LLM调用）
        cleaned_sources, filtering_log = self._cot_clean(intent, keywords, sources)

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
        self, intent: str, keywords: list[str], sources: list[dict],
    ) -> tuple[list[dict], FilteringLog]:
        """CoT数据清洗：以意图为基准剔除泛泛而谈/几乎完全无关，逻辑一致性检查，去重合并"""
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
            intent=intent or "（未提供）",
            keywords=json.dumps(keywords, ensure_ascii=False),
            search_results=sources_text,
        )
        raw = _call_with_retry(
            self.client, self.config, [{"role": "user", "content": prompt}]
        )
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

        # 先直接解析；失败则抽取首个 {...} 片段再试（兜住被思考文本/前后缀包裹的输出）
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            import re
            m = re.search(r"\{[\s\S]*\}", raw)
            if not m:
                # 降级：返回原始数据，空日志
                return sources, FilteringLog(
                    consistency_issues=["CoT清洗结果解析失败，使用原始数据"],
                )
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
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
