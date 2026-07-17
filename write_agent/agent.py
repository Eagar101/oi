"""Write Agent 核心逻辑：生成Markdown格式的详细技术报告"""

import json
import os
import time

import anthropic

from .config import WriteConfig
from .schema import WriteInput

REPORT_PROMPT = """\
你是一位资深技术文档工程师，需要为客户编写一份详细的技术执行摘要报告。

# 报告要求
- 受众：客户或非技术管理者（需要将技术细节转化为商业价值）
- 长度：3-5页 Markdown 格式（约1500-2500字）
- 重点：突出行动项与实施计划，提供清晰的下一步
- 风格：专业、清晰、结构化，避免过度技术术语

# 输入数据
## 原始需求
{original_summary}

## 关键词分析
{keywords_summary}

## 行动项（TODO列表）
{todos}

## 知识图谱关系
{graph_relations}

## 全局总结
{global_summary}

## 搜索结果摘要
{search_summary}

# 报告结构（Markdown格式）
请生成完整的Markdown报告，包含以下章节：

1. **执行摘要**（1-2段）：概述项目目标、核心发现和关键建议
2. **背景与目标**：阐述原始需求与业务目标
3. **关键发现**：按重要性排列的关键词深度分析，每个关键词包含：
   - 核心要点
   - 相关来源（如有）
   - 与技术栈的关联
4. **行动项与实施计划**（重点章节）：
   - 表格形式列出所有TODO项，包含ID、任务、优先级、预计工作量、依赖项
   - 分阶段实施建议（近期/中期/长期）
   - 资源需求与风险缓解措施
5. **关系分析与建议**：
   - 关键词之间的依赖关系
   - 技术决策建议
   - 风险预警与应对策略
6. **附录**：
   - 关键词完整列表
   - 参考来源链接
   - 知识图谱关系图描述

# 输出要求
- 只输出Markdown格式报告，不要额外解释
- 使用恰当的标题层级（#、##、###）
- 表格使用Markdown表格语法
- 链接使用[文本](URL)格式
- 确保报告逻辑连贯，从高层次概述到具体细节
- 控制详略：篇幅有限时优先保证「执行摘要」「关键发现」「行动项」完整，附录可精简
- 必须完整收尾：若接近输出长度上限，主动压缩后续章节篇幅并补上完整的「附录」和结束语，务必生成到结尾，绝不中途截断或省略结尾
"""


def _call_with_retry(client: anthropic.Anthropic, config: WriteConfig, **kwargs) -> str:
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
            wait = 30 * (attempt + 1)
            print(f"  速率限制，等待{wait}秒后重试...")
            time.sleep(wait)
    raise RuntimeError("连续3次触发速率限制，请稍后再试")


class WriteAgent:
    """生成Markdown格式的详细技术报告"""

    def __init__(self, config: WriteConfig | None = None) -> None:
        self.config = config or WriteConfig()
        self.config.validate()
        self.client = anthropic.Anthropic(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
        )

    def generate_report(self, data: WriteInput, parent_report: str = "",
                        followup_query: str = "") -> str:
        """生成Markdown报告内容。
        - parent_report非空时，生成追加章节而非全新报告
        - followup_query为追问的原始问题
        """
        if parent_report:
            return self._generate_followup_section(data, parent_report, followup_query)
        prompt = self._build_prompt(data)
        return _call_with_retry(
            self.client,
            self.config,
            messages=[{"role": "user", "content": prompt}],
        )

    def _generate_followup_section(self, data: WriteInput,
                                    parent_report: str, query: str) -> str:
        """追问模式：生成追加章节并拼接到父报告末尾"""
        # 提取本次追问的关键发现
        keywords_summary = "\n".join(
            f"- **{n.keyword}**：{n.summary}" for n in data.summary.nodes
        )
        todos = "\n".join(
            f"- [{t.id}] {t.task} (优先级: {t.priority})"
            for t in data.planner.todos
        )

        prompt = f"""\
你是一位资深技术文档工程师。用户对原报告追问了新问题，请生成一个追加章节，回答追问并融入新发现。

## 追问问题
{query}

## 新增关键词分析
{keywords_summary}

## 新增行动项
{todos}

## 新增全局总结
{data.summary.global_summary}

## 搜索补充信息
{data.search_summary}

## 原报告（前4000字，仅供上下文参考）
{parent_report[:4000]}

## 输出要求
- 只输出一个完整的Markdown章节，开头形如 `## 追加研究：<自行概括的追问问题简述>`，由你根据追问问题提炼简述
- 章节包含：1) 追问背景；2) 新发现（按关键词分段）；3) 补充行动项；4) 对原报告的更新建议
- 不要重复原报告已有内容
- 400-800字
"""
        section = _call_with_retry(
            self.client,
            self.config,
            messages=[{"role": "user", "content": prompt}],
        )
        # 拼接到原报告末尾
        return f"{parent_report.rstrip()}\n\n---\n\n{section}\n"

    def generate_and_save(self, data: WriteInput, title: str = "",
                          parent_report: str = "", followup_query: str = "") -> tuple[str, str]:
        """生成报告并保存为文件，返回(报告内容, 文件路径)"""
        report = self.generate_report(data, parent_report=parent_report,
                                       followup_query=followup_query)

        os.makedirs(self.config.output_dir, exist_ok=True)

        # 生成文件名
        if not title:
            title = "技术报告"
        safe_title = "".join(c for c in title if c.isalnum() or c in " _-")[:50]
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"report_{safe_title}_{timestamp}.md"
        filepath = os.path.join(self.config.output_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(report)

        return report, filepath

    def _build_prompt(self, data: WriteInput) -> str:
        """构建报告生成prompt"""
        # 原始需求（Planner的summary）
        original_summary = data.planner.summary

        # 关键词分析（Summary的nodes）
        keywords_summary = "\n".join(
            f"- **{node.keyword}**：{node.summary}" for node in data.summary.nodes
        )

        # TODO列表（Planner的todos）
        todos = "\n".join(
            f"- [{todo.id}] {todo.task} (优先级: {todo.priority})"
            for todo in data.planner.todos
        )

        # 知识图谱关系（Summary的edges）
        relations = []
        for edge in data.summary.edges:
            from_kw = next(
                (n.keyword for n in data.summary.nodes if n.id == edge.from_id),
                edge.from_id,
            )
            to_kw = next(
                (n.keyword for n in data.summary.nodes if n.id == edge.to_id),
                edge.to_id,
            )
            relations.append(f"- {from_kw} → {to_kw} ({edge.relation})")
        graph_relations = "\n".join(relations) if relations else "（无显式关系）"

        # 全局总结
        global_summary = data.summary.global_summary

        # 搜索结果摘要
        search_summary = data.search_summary

        return REPORT_PROMPT.format(
            original_summary=original_summary,
            keywords_summary=keywords_summary,
            todos=todos,
            graph_relations=graph_relations,
            global_summary=global_summary,
            search_summary=search_summary,
        )