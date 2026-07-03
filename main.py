"""Planner + Search + Summary + Write Agent 串联入口"""

import argparse
import json
import sys

from planner_agent import PlannerAgent, PlannerOutput
from search_agent import SearchAgent
from summary_agent import SummaryAgent, SummaryOutput
from write_agent import WriteAgent, WriteInput

# 修复Windows终端中文输出乱码
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def run_pipeline(user_input: str, step: bool = False) -> None:
    """串联执行：planner -> search -> summary -> write"""
    # Step 1: Planner Agent
    print("=" * 50)
    print("[1/4] Planner Agent 处理中...")
    planner = PlannerAgent()
    planner_json = planner.plan_as_json(user_input)
    print(f"\n--- Planner 输出 ---\n{planner_json}")
    planner_output = PlannerOutput.model_validate_json(planner_json)

    if step:
        if input("\n继续搜索? (Y/n) ").strip().lower() == "n":
            return

    # Step 2: Search Agent（多轮深度搜索）
    print("\n" + "=" * 50)
    print("[2/4] Search Agent 搜索中...")
    searcher = SearchAgent()
    search_json = searcher.run_as_json(planner_json)
    search_data = json.loads(search_json)
    search_summary = search_data.get("summary", "")
    rounds_info = search_data.get("search_rounds", [])
    print(f"\n--- 搜索轮次 ---")
    for r in rounds_info:
        tag = "[深度]" if r.get("is_deep_dive") else "[基础]"
        print(f"  {tag} {r.get('query')} → {r.get('results_count')}条结果")
    print(f"\n--- Search 摘要 ---\n{search_summary}")

    if step:
        if input("\n继续归纳? (Y/n) ").strip().lower() == "n":
            return

    # Step 3: Summary Agent
    print("\n" + "=" * 50)
    print("[3/4] Summary Agent 归纳总结中...")
    summarizer = SummaryAgent()
    summary_output, summary_path = summarizer.run_and_save(search_json, query=user_input)
    summary_json = summary_output.model_dump_json(indent=2, ensure_ascii=False)
    print(f"\n--- Summary 输出 ---\n{summary_json}")
    print(f"\n已持久化至: {summary_path}")

    if step:
        if input("\n继续生成报告? (Y/n) ").strip().lower() == "n":
            return

    # Step 4: Write Agent
    print("\n" + "=" * 50)
    print("[4/4] Write Agent 生成报告中...")
    writer = WriteAgent()
    write_input = WriteInput(
        planner=planner_output,
        search_summary=search_summary,
        summary=summary_output,
    )
    report_content, report_path = writer.generate_and_save(write_input, title=user_input[:30])
    print(f"\n--- 报告生成完成 ---")
    print(f"报告已保存至: {report_path}")
    print(f"\n报告预览（前500字符）:\n{report_content[:500]}...")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="自动化深度研究智能体"
    )
    parser.add_argument(
        "input", nargs="?", help="要研究的问题（省略则进入交互模式）",
    )
    parser.add_argument(
        "--step", action="store_true",
        help="逐步确认模式（每个Agent执行前暂停确认）",
    )
    parser.add_argument(
        "--no-deep", action="store_true",
        help="禁用深度搜索（仅单轮搜索）",
    )
    args = parser.parse_args()

    if args.no_deep:
        from search_agent.config import SearchConfig
        import os
        os.environ["SEARCH_DEEP_SEARCH"] = "false"

    if args.input:
        run_pipeline(args.input, step=args.step)
    else:
        mode = "逐步确认" if args.step else "全自动"
        print(f"自动化深度研究智能体 已启动（{mode}模式，输入 exit 退出）")
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
                run_pipeline(user_input, step=args.step)
            except Exception as e:
                print(f"\n错误: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
