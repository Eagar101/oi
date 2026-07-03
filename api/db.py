"""SQLite数据库模型与会话管理"""

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .config import APIConfig

_lock = threading.Lock()
_config = APIConfig()


def _get_db_path() -> Path:
    url = _config.database_url
    if url.startswith("sqlite:///"):
        return Path(url.replace("sqlite:///", "", 1))
    return Path("research.db")


@contextmanager
def get_conn():
    """获取SQLite连接（线程安全）"""
    db_path = _get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """初始化数据库表"""
    with _lock, get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                query TEXT NOT NULL,
                status TEXT NOT NULL,
                current_step TEXT,
                progress INTEGER DEFAULT 0,
                error TEXT,
                report_path TEXT,
                summary_path TEXT,
                parent_task_id TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id, created_at DESC)
        """)
        # 兼容旧库：若 tasks 表已存在但缺 parent_task_id 列，则补加
        try:
            c.execute("SELECT parent_task_id FROM tasks LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE tasks ADD COLUMN parent_task_id TEXT")


def create_user(username: str, password_hash: str) -> int:
    with _lock, get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, password_hash, time.time()),
        )
        return c.lastrowid


def get_user_by_name(username: str) -> dict | None:
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = c.fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict | None:
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = c.fetchone()
        return dict(row) if row else None


def create_task(task_id: str, user_id: int, query: str, parent_task_id: str | None = None) -> None:
    with _lock, get_conn() as conn:
        c = conn.cursor()
        now = time.time()
        c.execute(
            "INSERT INTO tasks (id, user_id, query, status, parent_task_id, created_at, updated_at) "
            "VALUES (?, ?, ?, 'pending', ?, ?, ?)",
            (task_id, user_id, query, parent_task_id, now, now),
        )


def update_task(task_id: str, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = time.time()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [task_id]
    with _lock, get_conn() as conn:
        conn.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", values)


def get_task(task_id: str) -> dict | None:
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = c.fetchone()
        return dict(row) if row else None


def list_user_tasks(user_id: int, limit: int = 50, parent_only: bool = False) -> list[dict]:
    """列出用户的任务。parent_only=True时只返回主任务（无父任务）"""
    with get_conn() as conn:
        c = conn.cursor()
        if parent_only:
            c.execute(
                "SELECT * FROM tasks WHERE user_id = ? AND parent_task_id IS NULL "
                "ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            )
        else:
            c.execute(
                "SELECT * FROM tasks WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            )
        return [dict(r) for r in c.fetchall()]


def get_child_tasks(parent_task_id: str) -> list[dict]:
    """获取某父任务的所有子任务（追问任务）"""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT * FROM tasks WHERE parent_task_id = ? ORDER BY created_at ASC",
            (parent_task_id,),
        )
        return [dict(r) for r in c.fetchall()]


def delete_task(task_id: str) -> dict | None:
    """删除任务记录（返回被删的任务，用于清理文件）"""
    with _lock, get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = c.fetchone()
        if not row:
            return None
        task = dict(row)
        c.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return task


def count_active_tasks(user_id: int | None = None) -> int:
    """统计运行中的任务数。user_id为None时统计全局"""
    with get_conn() as conn:
        c = conn.cursor()
        if user_id is None:
            c.execute(
                "SELECT COUNT(*) FROM tasks WHERE status IN ('pending', 'running')"
            )
        else:
            c.execute(
                "SELECT COUNT(*) FROM tasks WHERE user_id = ? AND status IN ('pending', 'running')",
                (user_id,),
            )
        return c.fetchone()[0]
