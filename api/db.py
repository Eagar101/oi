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
        # 兼容旧库：tasks 表补加 document_ids 列（RAG 文档关联）
        try:
            c.execute("SELECT document_ids FROM tasks LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE tasks ADD COLUMN document_ids TEXT")
        # 文档表
        c.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                char_count INTEGER NOT NULL,
                summary TEXT,
                created_at REAL NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_user
            ON documents(user_id, created_at DESC)
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_hash
            ON documents(user_id, content_hash)
        """)
        # 切片表（embedding 以 BLOB 存储）
        c.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                seq INTEGER NOT NULL,
                content TEXT NOT NULL,
                embedding BLOB NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY (document_id) REFERENCES documents(id)
            )
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(document_id)
        """)


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


def create_task(task_id: str, user_id: int, query: str,
                parent_task_id: str | None = None,
                document_ids: str | None = None) -> None:
    with _lock, get_conn() as conn:
        c = conn.cursor()
        now = time.time()
        c.execute(
            "INSERT INTO tasks (id, user_id, query, status, parent_task_id, "
            "document_ids, created_at, updated_at) "
            "VALUES (?, ?, ?, 'pending', ?, ?, ?, ?)",
            (task_id, user_id, query, parent_task_id, document_ids, now, now),
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


# ==================== 文档与切片（RAG）====================

def create_document(user_id: int, filename: str, content: str,
                    content_hash: str) -> int:
    """新建文档记录，返回 doc_id"""
    with _lock, get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO documents (user_id, filename, content, content_hash, "
            "char_count, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, filename, content, content_hash, len(content), time.time()),
        )
        return c.lastrowid


def add_chunks(doc_id: int, chunks: list[tuple[int, str, bytes]]) -> None:
    """批量写入切片。chunks = [(seq, content, embedding_bytes), ...]"""
    if not chunks:
        return
    now = time.time()
    rows = [(doc_id, seq, content, emb, now) for seq, content, emb in chunks]
    with _lock, get_conn() as conn:
        conn.executemany(
            "INSERT INTO chunks (document_id, seq, content, embedding, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )


def find_document_by_hash(user_id: int, content_hash: str) -> dict | None:
    """按用户+内容哈希查找文档（去重用）"""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT * FROM documents WHERE user_id = ? AND content_hash = ?",
            (user_id, content_hash),
        )
        row = c.fetchone()
        return dict(row) if row else None


def get_document(doc_id: int) -> dict | None:
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM documents WHERE id = ?", (doc_id,))
        row = c.fetchone()
        return dict(row) if row else None


def update_document_summary(doc_id: int, summary: str) -> None:
    with _lock, get_conn() as conn:
        conn.execute(
            "UPDATE documents SET summary = ? WHERE id = ?", (summary, doc_id)
        )


def list_user_documents(user_id: int) -> list[dict]:
    """列出用户文档（不含 content 全文，避免大字段）"""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, user_id, filename, content_hash, char_count, "
            "summary, created_at FROM documents WHERE user_id = ? "
            "ORDER BY created_at DESC",
            (user_id,),
        )
        return [dict(r) for r in c.fetchall()]


def count_chunks(doc_id: int) -> int:
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM chunks WHERE document_id = ?", (doc_id,))
        return c.fetchone()[0]


def delete_document(doc_id: int) -> dict | None:
    """删除文档及其所有切片，返回被删文档"""
    with _lock, get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM documents WHERE id = ?", (doc_id,))
        row = c.fetchone()
        if not row:
            return None
        doc = dict(row)
        c.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))
        c.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        return doc


def search_similar(user_id: int, query_vec, top_k: int = 5,
                   doc_ids: list[int] | None = None) -> list[dict]:
    """向量检索：拉取该用户所有切片向量，numpy 余弦相似度，返回 top_k

    返回 [{document_id, content, score}, ...]，已按相似度降序
    """
    import numpy as np

    with get_conn() as conn:
        c = conn.cursor()
        if doc_ids:
            placeholders = ",".join("?" * len(doc_ids))
            c.execute(
                f"SELECT id, document_id, content, embedding FROM chunks "
                f"WHERE document_id IN ({placeholders})",
                doc_ids,
            )
        else:
            c.execute(
                "SELECT ch.id, ch.document_id, ch.content, ch.embedding "
                "FROM chunks ch JOIN documents d ON ch.document_id = d.id "
                "WHERE d.user_id = ?",
                (user_id,),
            )
        rows = c.fetchall()

    if not rows:
        return []

    q = np.asarray(query_vec, dtype=np.float32)
    q_norm = np.linalg.norm(q)
    if q_norm > 0:
        q = q / q_norm

    scored = []
    for r in rows:
        emb = np.frombuffer(r["embedding"], dtype=np.float32)
        # 长度不一致跳过（模型不一致导致）
        if emb.shape != q.shape:
            continue
        score = float(np.dot(q, emb))  # 向量已归一化，点积即余弦
        scored.append({
            "chunk_id": r["id"],
            "document_id": r["document_id"],
            "content": r["content"],
            "score": score,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]
