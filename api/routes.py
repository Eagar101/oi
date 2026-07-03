"""FastAPI路由：认证、任务、WebSocket、报告"""

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import auth, db
from .config import APIConfig
from .runner import get_runner
from .ws import ws_manager


# ---------- 请求模型 ----------
class RegisterReq(BaseModel):
    username: str
    password: str


class LoginReq(BaseModel):
    username: str
    password: str


class TaskReq(BaseModel):
    query: str
    parent_task_id: str | None = None


# ---------- 依赖注入 ----------
def get_config() -> APIConfig:
    return APIConfig()


def get_current_user(request: Request, config: APIConfig = Depends(get_config)) -> dict:
    """从Authorization头解析JWT，返回用户信息"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少认证token")
    token = auth_header[7:]
    result = auth.verify_token(token, config)
    if not result.success:
        raise HTTPException(status_code=401, detail=result.error)
    user = db.get_user_by_id(result.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user


# ---------- 路由 ----------
router = APIRouter()


@router.post("/auth/register")
def register(req: RegisterReq, config: APIConfig = Depends(get_config)):
    result = auth.register(req.username, req.password, config)
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)
    return {
        "user_id": result.user_id,
        "username": result.username,
        "token": result.error,  # register/login复用error字段传token
    }


@router.post("/auth/login")
def login(req: LoginReq, config: APIConfig = Depends(get_config)):
    result = auth.login(req.username, req.password, config)
    if not result.success:
        raise HTTPException(status_code=401, detail=result.error)
    return {
        "user_id": result.user_id,
        "username": result.username,
        "token": result.error,
    }


@router.post("/tasks")
def create_task(
    req: TaskReq,
    user: dict = Depends(get_current_user),
    config: APIConfig = Depends(get_config),
):
    """提交研究任务，返回任务ID"""
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="查询不能为空")

    # 并发控制
    user_active = db.count_active_tasks(user["id"])
    if user_active >= config.max_concurrent_per_user:
        raise HTTPException(
            status_code=429,
            detail=f"已达用户并发上限({config.max_concurrent_per_user})",
        )
    total_active = db.count_active_tasks(None)
    if total_active >= config.max_concurrent_total:
        raise HTTPException(
            status_code=429,
            detail=f"已达系统并发上限({config.max_concurrent_total})",
        )

    # 追问任务：校验父任务归属
    parent_task_id = req.parent_task_id
    if parent_task_id:
        parent = db.get_task(parent_task_id)
        if not parent or parent["user_id"] != user["id"]:
            raise HTTPException(status_code=404, detail="父任务不存在或无权访问")
        if parent["status"] != "completed":
            raise HTTPException(status_code=400, detail="父任务尚未完成，无法基于它追问")

    task_id = str(uuid.uuid4())
    db.create_task(task_id, user["id"], req.query, parent_task_id=parent_task_id)
    get_runner().submit(task_id, user["id"], req.query, parent_task_id=parent_task_id)

    return {"task_id": task_id, "status": "pending", "query": req.query,
            "parent_task_id": parent_task_id}


@router.get("/tasks")
def list_tasks(user: dict = Depends(get_current_user), parent_only: bool = False):
    """列出用户的历史任务。parent_only=true只返回主任务"""
    tasks = db.list_user_tasks(user["id"], parent_only=parent_only)
    return {"tasks": tasks}


@router.get("/tasks/{task_id}/tree")
def get_task_tree(task_id: str, user: dict = Depends(get_current_user)):
    """获取任务树（父任务+所有子任务）"""
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="无权访问")
    children = db.get_child_tasks(task_id)
    return {"root": task, "children": children}


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str, user: dict = Depends(get_current_user)):
    """删除任务（同时清理报告和摘要文件）"""
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="无权删除")
    # 递归删除子任务
    children = db.get_child_tasks(task_id)
    for child in children:
        delete_task(child["id"])
    # 删除文件
    for path_key in ("report_path", "summary_path"):
        p = task.get(path_key)
        if p:
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass
    db.delete_task(task_id)
    return {"deleted": task_id}


@router.get("/tasks/{task_id}")
def get_task(task_id: str, user: dict = Depends(get_current_user)):
    """查询任务状态"""
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="无权访问该任务")
    return task


@router.get("/tasks/{task_id}/report")
def get_report(task_id: str, user: dict = Depends(get_current_user)):
    """下载Markdown报告"""
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="无权访问")
    if task["status"] != "completed" or not task["report_path"]:
        raise HTTPException(status_code=400, detail="报告未生成")
    path = Path(task["report_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="报告文件丢失")
    return FileResponse(
        str(path),
        media_type="text/markdown",
        filename=f"{task_id}.md",
    )


@router.get("/tasks/{task_id}/summary")
def get_summary(task_id: str, user: dict = Depends(get_current_user)):
    """获取Summary Agent的JSON输出"""
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="无权访问")
    if not task["summary_path"]:
        raise HTTPException(status_code=400, detail="摘要未生成")
    path = Path(task["summary_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="摘要文件丢失")
    return JSONResponse(content=json.loads(path.read_text(encoding="utf-8")))


@router.websocket("/ws/tasks/{task_id}")
async def task_ws(websocket: WebSocket, task_id: str):
    """WebSocket推送任务进度"""
    task = db.get_task(task_id)
    if not task:
        await websocket.close(code=4004, reason="任务不存在")
        return

    await ws_manager.connect(task_id, websocket)
    try:
        # 推送当前状态（用于断线重连）
        await websocket.send_text(
            json.dumps(
                {
                    "type": "status",
                    "status": task["status"],
                    "current_step": task["current_step"],
                    "progress": task["progress"] or 0,
                },
                ensure_ascii=False,
            )
        )
        # 保持连接，直到任务结束或客户端断开
        while True:
            await websocket.receive_text()
    except Exception:
        pass
    finally:
        await ws_manager.disconnect(task_id, websocket)
