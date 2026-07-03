"""Search Agent 核心逻辑：多轮深度搜索 + 自动子查询 + 去重合并"""

import json
import time

import anthropic

from planner_agent.schema import PlannerOutput

from .config import SearchConfig
from .schema import SearchOutput, SearchResult, SearchRound
from .searcher import search

SUMMARY_PROMPT = """\
你是一个搜索结果摘要助手。根据用户的搜索查询和搜索结果，生成一段简洁的综合摘要。

要求：
- 摘要不超过200字
- 提取搜索结果中最有价值的信息
- 如果搜索结果与查询不太相关，说明"未找到高度相关的结果"并给出最接近的内容
- 不要编造搜索结果中没有的信息
"""

# 判断搜索结果是否充分，并生成子查询
SUFFICIENCY_PROMPT = """\
你是一个搜索质量评估专家。判断当前搜索结果是否已充分覆盖关键词。

当前日期：{current_date}

关键词列表：{keywords}
已搜索的查询：{searched_queries}

已有搜索结果摘要：
{existing_summary}

请分析：
1. 哪些关键词尚未被充分覆盖？
2. 是否需要生成新的子查询来补充信息？

如果信息已充分覆盖，输出空数组：[]
如果需要补充搜索，输出子查询列表（JSON数组）：
["子查询1", "子查询2"]

规则：
- 最多生成2个子查询
- 子查询应针对覆盖不足的关键词
- 子查询应比原始查询更具体（如加上"最佳实践"、"教程"、"对比"等修饰词）
- 如果已有3轮搜索，无论是否充分都输出[]
只输出JSON数组，不要输出其他内容。
"""


def _call_with_retry(client: anthropic.Anthropic, config: SearchConfig, **kwargs) -> str:
    """带重试的LLM调用"""
    for attempt in range(3):
        try:
            resp = client.messages.create(
                model=config.model,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                **kwargs,
            )
            text = next(
                (block.text for block in resp.content if block.type == "text"),
                None,
            )
            return text.strip() if text else ""
        except anthropic.RateLimitError:
            wait = 15 * (attempt + 1)
            print(f"  速率限制，等待{wait}秒后重试...")
            time.sleep(wait)
    raise RuntimeError("连续3次触发速率限制，请稍后再试")


def _dedup_sources(sources: list[SearchResult]) -> list[SearchResult]:
    """按URL去重，保留首次出现的结果"""
    seen = set()
    unique = []
    for s in sources:
        if s.url not in seen:
            seen.add(s.url)
            unique.append(s)
    return unique


class SearchAgent:
    """多轮深度搜索智能体：自动拆分子查询，合并去重"""

    def __init__(self, config: SearchConfig | None = None) -> None:
        self.config = config or SearchConfig()
        self.config.validate()
        self.client = anthropic.Anthropic(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
        )

    def run(self, planner_json: str) -> SearchOutput:
        """接收planner的JSON字符串，执行多轮搜索并返回结构化结果"""
        planner_output = PlannerOutput.model_validate_json(planner_json)
        return self.run_from_planner(planner_output)

    def run_from_planner(self, planner_output: PlannerOutput) -> SearchOutput:
        """接收PlannerOutput对象，执行多轮深度搜索"""
        keywords = planner_output.keywords
        main_query = " ".join(keywords)

        # ---- 第1轮：每个关键词单独搜索 ----
        all_sources: list[SearchResult] = []
        searched_queries: list[str] = []
        rounds: list[SearchRound] = []

        for kw in keywords:
            print(f"  搜索关键词: {kw}")
            results = search(kw, max_results=self.config.max_results)
            all_sources.extend(results)
            searched_queries.append(kw)
            rounds.append(SearchRound(
                query=kw, results_count=len(results), is_deep_dive=False,
            ))
            time.sleep(1)

        # ---- 第2轮：组合查询补充 ----
        print(f"  组合搜索: {main_query}")
        combo_results = search(main_query, max_results=self.config.max_results)
        all_sources.extend(combo_results)
        searched_queries.append(main_query)
        rounds.append(SearchRound(
            query=main_query, results_count=len(combo_results), is_deep_dive=False,
        ))

        # ---- 第3轮+：深度搜索（如启用） ----
        if self.config.deep_search:
            all_sources = _dedup_sources(all_sources)
            existing_summary = self._quick_summary(main_query, all_sources)
            round_num = 2

            while round_num < self.config.max_rounds:
                sub_queries = self._generate_sub_queries(
                    keywords, searched_queries, existing_summary,
                )
                if not sub_queries:
                    print("  信息已充分，跳过深度搜索")
                    break

                for sq in sub_queries:
                    print(f"  深度搜索: {sq}")
                    deep_results = search(sq, max_results=self.config.max_results)
                    all_sources.extend(deep_results)
                    searched_queries.append(sq)
                    rounds.append(SearchRound(
                        query=sq, results_count=len(deep_results), is_deep_dive=True,
                    ))
                    time.sleep(1)

                all_sources = _dedup_sources(all_sources)
                round_num += 1

                if round_num < self.config.max_rounds:
                    existing_summary = self._quick_summary(main_query, all_sources)
                    time.sleep(2)

        # 最终去重
        all_sources = _dedup_sources(all_sources)

        # LLM综合摘要
        summary = self._summarize(main_query, all_sources)

        return SearchOutput(
            query=main_query,
            summary=summary,
            sources=all_sources,
            raw_keywords=keywords,
            search_rounds=rounds,
        )

    def _quick_summary(self, query: str, sources: list[SearchResult]) -> str:
        """快速生成搜索结果摘要，用于判断充分性"""
        if not sources:
            return "（无搜索结果）"
        results_text = "\n".join(
            f"- [{s.title}] {s.snippet[:80]}" for s in sources[:10]
        )
        raw = _call_with_retry(
            self.client,
            self.config,
            system=SUMMARY_PROMPT,
            messages=[{
                "role": "user",
                "content": f"搜索查询：{query}\n\n搜索结果：\n{results_text}",
            }],
        )
        return raw if raw else "（摘要生成失败）"

    def _generate_sub_queries(
        self,
        keywords: list[str],
        searched_queries: list[str],
        existing_summary: str,
    ) -> list[str]:
        """LLM判断搜索充分性并生成子查询"""
        prompt = SUFFICIENCY_PROMPT.format(
            current_date=time.strftime("%Y年%m月%d日"),
            keywords=json.dumps(keywords, ensure_ascii=False),
            searched_queries=json.dumps(searched_queries, ensure_ascii=False),
            existing_summary=existing_summary,
        )
        raw = _call_with_retry(
            self.client,
            self.config,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

        try:
            queries = json.loads(raw)
            if isinstance(queries, list) and queries:
                return queries[:2]
        except json.JSONDecodeError:
            pass
        return []

    def _summarize(self, query: str, sources: list[SearchResult]) -> str:
        """调用LLM对搜索结果生成摘要"""
        if not sources:
            return "未找到相关搜索结果。"

        results_text = "\n".join(
            f"- [{s.title}]({s.url}): {s.snippet}" for s in sources
        )

        raw = _call_with_retry(
            self.client,
            self.config,
            system=SUMMARY_PROMPT,
            messages=[{
                "role": "user",
                "content": f"搜索查询：{query}\n\n搜索结果：\n{results_text}",
            }],
        )
        return raw if raw else "摘要生成失败。"

    def run_as_json(self, planner_json: str) -> str:
        """接收planner的JSON，返回search结果的JSON字符串"""
        result = self.run(planner_json)
        return result.model_dump_json(indent=2, ensure_ascii=False)
