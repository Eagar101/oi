"""Planner Agent 核心逻辑：将用户长句切断为关键词并总结TODO"""

import json
import time

import anthropic

from .config import PlannerConfig
from .schema import PlannerOutput

SYSTEM_PROMPT = """\
你是一个专业的计划助手(Planner Agent)。你的任务是：

1. 从用户的输入中提取关键信息，拆分为独立的关键词
2. 用一句话总结用户的核心意图
3. 将用户的意图拆解为可执行的TODO列表，每个TODO标注优先级(high/medium/low)

你必须严格按以下JSON格式输出，不要输出任何其他内容：
{
  "keywords": ["关键词1", "关键词2", ...],
  "summary": "一句话总结",
  "todos": [
    {"id": 1, "task": "具体待办事项", "priority": "high"},
    {"id": 2, "task": "具体待办事项", "priority": "medium"},
    ...
  ]
}

规则：
- keywords：提取3-8个关键词，按重要性排序
- summary：简明扼要，不超过50字
- todos：每个task必须是具体可执行的动作，按优先级从高到低排列
- 优先级分配：紧急且重要=high，重要不紧急=medium，一般=low
- 严格输出JSON，不要包含markdown代码块标记或任何解释性文字
"""


def _call_with_retry(client: anthropic.Anthropic, config: PlannerConfig, **kwargs) -> str:
    """带重试和间隔的LLM调用，返回文本内容"""
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
            if text is None:
                raise ValueError("模型未返回文本内容")
            return text.strip()
        except anthropic.RateLimitError:
            wait = 15 * (attempt + 1)
            print(f"  速率限制，等待{wait}秒后重试...")
            time.sleep(wait)
    raise RuntimeError("连续3次触发速率限制，请稍后再试")


class PlannerAgent:
    """将用户长句切断为关键词并总结TODO的智能体"""

    def __init__(self, config: PlannerConfig | None = None) -> None:
        self.config = config or PlannerConfig()
        self.config.validate()
        self.client = anthropic.Anthropic(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
        )

    def plan(self, user_input: str) -> PlannerOutput:
        """处理用户输入，返回结构化的计划"""
        raw = _call_with_retry(
            self.client,
            self.config,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_input}],
        )
        return self._parse(raw)

    def _parse(self, raw: str) -> PlannerOutput:
        """将LLM的原始输出解析为PlannerOutput，强制类型校验"""
        text = raw.removeprefix("```json").removeprefix("```")
        text = text.removesuffix("```").strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM输出不是合法JSON: {e}\n原始输出:\n{raw}") from e

        return PlannerOutput.model_validate(data)

    def plan_as_json(self, user_input: str) -> str:
        """处理用户输入，直接返回JSON字符串"""
        result = self.plan(user_input)
        return result.model_dump_json(indent=2, ensure_ascii=False)
