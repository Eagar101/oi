"""任务运行器：后台线程执行4个Agent，通过WebSocket推送进度"""

import asyncio
import json
import threading
import traceback
import uuid
from datetime import datetime

from planner_agent import PlannerAgent, PlannerOutput
from search_agent import SearchAgent
from summary_agent import SummaryAgent, SummaryOutput
from write_agent import WriteAgent, WriteInput

from . import db
from .config import APIConfig
from .ws import ws_manager


class TaskRunner:
    """异步任务运行器，管理后台Agent执行"""

    def __init__(self, config: APIConfig) -> None:
        self.config = config
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._loop.run_forever, daemon=True
        )
        self._loop_thread.start()

    def submit(self, task_id: str, user_id: int, query: str,
               parent_task_id: str | None = None,
               document_ids: list[int] | None = None) -> None:
        """提交任务到后台线程执行"""
        threading.Thread(
            target=self._run_in_thread,
            args=(task_id, user_id, query, parent_task_id, document_ids),
            daemon=True,
        ).start()

    def _run_in_thread(self, task_id: str, user_id: int, query: str,
                       parent_task_id: str | None,
                       document_ids: list[int] | None) -> None:
        """在独立线程中执行Agent流水线"""
        asyncio.run(self._run_pipeline(
            task_id, user_id, query, parent_task_id, document_ids
        ))

    async def _run_pipeline(self, task_id: str, user_id: int, query: str,
                            parent_task_id: str | None,
                            document_ids: list[int] | None = None) -> None:
        """执行4个Agent流水线。追问任务(parent_task_id)会在父报告基础上追加章节；
        document_ids 非空时，把文档摘要作为上下文注入 Planner。"""
        loop = asyncio.get_running_loop()
        is_followup = parent_task_id is not None

        try:
            step_label = "追问研究" if is_followup else "Planner Agent 处理中"
            db.update_task(task_id, status="running", current_step="planner", progress=0)
            await ws_manager.broadcast(task_id, {
                "type": "step", "step": "planner", "message": step_label,
                "progress": 0,
            })

            # 追问模式：把父任务的summary作为上下文注入
            parent_context = ""
            if is_followup:
                parent_task = db.get_task(parent_task_id)
                if parent_task and parent_task.get("summary_path"):
                    from pathlib import Path as _P
                    p = _P(parent_task["summary_path"])
                    if p.exists():
                        parent_context = (
                            f"\n\n[父任务上下文 - 之前已研究的内容]\n"
                            f"{p.read_text(encoding='utf-8')[:3000]}\n"
                        )

            # 文档上下文：对用户上传文档生成摘要，注入 Planner
            doc_context = ""
            if document_ids:
                from rag_agent import RAGAgent
                rag = RAGAgent()
                doc_context = rag.build_doc_context(document_ids)

            # Step 1: Planner
            planner = PlannerAgent()
            enriched_query = (
                f"{query}{parent_context}{doc_context}"
                if (parent_context or doc_context) else query
            )
            planner_json = await loop.run_in_executor(
                None, planner.plan_as_json, enriched_query
            )
            planner_output = PlannerOutput.model_validate_json(planner_json)

            await ws_manager.broadcast(task_id, {
                "type": "data", "step": "planner", "data": json.loads(planner_json),
            })

            # Step 2: Search
            db.update_task(task_id, current_step="search", progress=25)
            await ws_manager.broadcast(task_id, {
                "type": "step", "step": "search",
                "message": "Search Agent 多轮搜索中...", "progress": 25,
            })
            searcher = SearchAgent()
            search_json = await loop.run_in_executor(
                None, searcher.run_as_json, planner_json
            )
            search_data = json.loads(search_json)
            rounds = search_data.get("search_rounds", [])
            for r in rounds:
                tag = "[深度]" if r.get("is_deep_dive") else "[基础]"
                await ws_manager.broadcast(task_id, {
                    "type": "search_round",
                    "query": r.get("query"),
                    "count": r.get("results_count"),
                    "is_deep": r.get("is_deep_dive", False),
                })

            # Step 3: Summary
            db.update_task(task_id, current_step="summary", progress=50)
            await ws_manager.broadcast(task_id, {
                "type": "step", "step": "summary",
                "message": "Summary Agent CoT清洗+总结中...", "progress": 50,
            })
            summarizer = SummaryAgent()
            summary_output, summary_path = await loop.run_in_executor(
                None, summarizer.run_and_save, search_json, query
            )
            db.update_task(task_id, summary_path=summary_path)

            await ws_manager.broadcast(task_id, {
                "type": "data", "step": "summary",
                "data": json.loads(
                    summary_output.model_dump_json(indent=2, ensure_ascii=False)
                ),
            })

            # Step 4: Write
            db.update_task(task_id, current_step="write", progress=75)
            await ws_manager.broadcast(task_id, {
                "type": "step", "step": "write",
                "message": "Write Agent 生成报告中...", "progress": 75,
            })
            writer = WriteAgent()
            write_input = WriteInput(
                planner=planner_output,
                search_summary=search_data.get("summary", ""),
                summary=summary_output,
            )

            # 追问模式：读取父报告，生成追加章节
            parent_report = ""
            followup_query = ""
            if is_followup:
                parent_task = db.get_task(parent_task_id)
                if parent_task and parent_task.get("report_path"):
                    from pathlib import Path as _P
                    p = _P(parent_task["report_path"])
                    if p.exists():
                        parent_report = p.read_text(encoding="utf-8")
                        followup_query = query

            report_content, report_path = await loop.run_in_executor(
                None, lambda: writer.generate_and_save(
                    write_input, query[:30],
                    parent_report=parent_report,
                    followup_query=followup_query,
                )
            )
            db.update_task(task_id, report_path=report_path)

            # 完成
            db.update_task(
                task_id, status="completed", current_step="done", progress=100
            )
            await ws_manager.broadcast(task_id, {
                "type": "complete",
                "message": "研究完成",
                "progress": 100,
                "report_path": report_path,
            })

        except Exception as e:
            err = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            db.update_task(task_id, status="failed", error=str(e))
            await ws_manager.broadcast(task_id, {
                "type": "error", "message": f"任务失败: {e}",
            })


# 全局单例
_runner: TaskRunner | None = None


def get_runner() -> TaskRunner:
    global _runner
    if _runner is None:
        _runner = TaskRunner(APIConfig())
    return _runner
