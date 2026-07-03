"""Planner Agent CLI交互入口"""

import argparse
import sys

# 修复Windows终端中文输出乱码
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from .agent import PlannerAgent
from .config import PlannerConfig


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Planner Agent - 将长句切断为关键词并总结TODO"
    )
    parser.add_argument(
        "input",
        nargs="?",
        help="要处理的长句（省略则进入交互模式）",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="覆盖使用的模型名称",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="覆盖API基础URL",
    )
    args = parser.parse_args()

    config = PlannerConfig()
    if args.model:
        config.model = args.model
    if args.base_url:
        config.base_url = args.base_url

    try:
        agent = PlannerAgent(config)
    except ValueError as e:
        print(f"配置错误: {e}", file=sys.stderr)
        sys.exit(1)

    if args.input:
        # 单次模式：处理命令行传入的文本
        _run_once(agent, args.input)
    else:
        # 交互模式：循环读取输入
        _run_interactive(agent)


def _run_once(agent: PlannerAgent, text: str) -> None:
    print(agent.plan_as_json(text))


def _run_interactive(agent: PlannerAgent) -> None:
    print("Planner Agent 已启动（输入 exit 退出）")
    print("-" * 40)

    while True:
        try:
            user_input = input("\n你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "q"):
            print("再见！")
            break

        try:
            result = agent.plan_as_json(user_input)
            print(f"\nPlanner>\n{result}")
        except ValueError as e:
            print(f"\n解析错误: {e}", file=sys.stderr)
        except Exception as e:
            print(f"\n请求失败: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
