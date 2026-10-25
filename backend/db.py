"""SQLite 数据访问层（V2.0：user/auth_token + 业务表 user_id 归属）。
注意：每个连接必须开启 PRAGMA foreign_keys（级联删除依赖它）。"""
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

from config import DB_PATH, TOKEN_TTL_DAYS, ZOMBIE_MINUTES


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def now() -> datetime:
    return datetime.now()


# ---------- user ----------

def create_user(username: str, email: str, password_hash: str) -> int:
    with get_conn() as c:
        cur = c.execute("INSERT INTO user (username, email, password_hash) VALUES (?,?,?)",
                        (username, email, password_hash))
        return cur.lastrowid


def user_count() -> int:
    with get_conn() as c:
        return c.execute("SELECT COUNT(*) FROM user").fetchone()[0]


def username_exists(username: str) -> bool:
    with get_conn() as c:
        return c.execute("SELECT 1 FROM user WHERE username=?", (username,)).fetchone() is not None


def email_exists(email: str) -> bool:
    with get_conn() as c:
        return c.execute("SELECT 1 FROM user WHERE email=?", (email,)).fetchone() is not None


def get_user_by_name(username: str) -> dict | None:
    with get_conn() as c:
        row = c.execute("SELECT * FROM user WHERE username=?", (username,)).fetchone()
    return dict(row) if row else None


def get_user(user_id: int) -> dict | None:
    with get_conn() as c:
        row = c.execute("SELECT id, username, email, created_at FROM user WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None


# ---------- auth_token ----------

def create_token(user_id: int) -> str:
    token = secrets.token_hex(32)
    expires = (now() + timedelta(days=TOKEN_TTL_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as c:
        c.execute("INSERT INTO auth_token (token, user_id, expires_at) VALUES (?,?,?)", (token, user_id, expires))
    return token


def get_token_user(token: str) -> dict | None:
    """有效则返回 {user_id, username}，过期/不存在返回 None。"""
    with get_conn() as c:
        row = c.execute(
            """SELECT t.user_id, u.username FROM auth_token t JOIN user u ON u.id = t.user_id
               WHERE t.token = ? AND t.expires_at > datetime('now','localtime')""", (token,)).fetchone()
    return dict(row) if row else None


def delete_token(token: str):
    with get_conn() as c:
        c.execute("DELETE FROM auth_token WHERE token = ?", (token,))


def cleanup_expired_tokens():
    with get_conn() as c:
        c.execute("DELETE FROM auth_token WHERE expires_at <= datetime('now','localtime')")


# ---------- conversation / message（user_id 归属） ----------

def create_conversation(user_id: int, title: str, scene: str = "chat",
                        related_analysis_id: int | None = None) -> int:
    with get_conn() as c:
        cur = c.execute(
            "INSERT INTO conversation (user_id, title, scene, related_analysis_id) VALUES (?,?,?,?)",
            (user_id, title[:30], scene, related_analysis_id))
        return cur.lastrowid


def touch_conversation(conv_id: int):
    with get_conn() as c:
        c.execute("UPDATE conversation SET updated_at = datetime('now','localtime') WHERE id=?", (conv_id,))


def add_message(conv_id: int, role: str, content: str) -> int:
    with get_conn() as c:
        cur = c.execute("INSERT INTO message (conversation_id, role, content) VALUES (?,?,?)",
                        (conv_id, role, content))
        return cur.lastrowid


def get_recent_messages(conv_id: int, limit: int) -> list[dict]:
    """API文档5.4：取最近 N 条后反转（上下文截断在应用层）。"""
    with get_conn() as c:
        rows = c.execute("SELECT role, content FROM message WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
                         (conv_id, limit)).fetchall()
    return [dict(r) for r in reversed(rows)]


def get_conversation(user_id: int, conv_id: int) -> dict | None:
    with get_conn() as c:
        row = c.execute("SELECT * FROM conversation WHERE id=? AND user_id=?", (conv_id, user_id)).fetchone()
    return dict(row) if row else None


def list_conversations(user_id: int, page: int, size: int) -> dict:
    with get_conn() as c:
        total = c.execute("SELECT COUNT(*) FROM conversation WHERE user_id=?", (user_id,)).fetchone()[0]
        rows = c.execute(
            """SELECT cv.id, cv.title, cv.scene, cv.updated_at,
                      (SELECT COUNT(*) FROM message m WHERE m.conversation_id=cv.id) AS message_count
               FROM conversation cv WHERE cv.user_id=?
               ORDER BY cv.updated_at DESC LIMIT ? OFFSET ?""",
            (user_id, size, (page - 1) * size)).fetchall()
    return {"total": total, "list": [dict(r) for r in rows]}


def get_conversation_messages(user_id: int, conv_id: int) -> list[dict] | None:
    with get_conn() as c:
        if not c.execute("SELECT 1 FROM conversation WHERE id=? AND user_id=?", (conv_id, user_id)).fetchone():
            return None
        rows = c.execute("SELECT id, role, content, created_at FROM message WHERE conversation_id=? ORDER BY id",
                         (conv_id,)).fetchall()
    return [dict(r) for r in rows]


def delete_conversation(user_id: int, conv_id: int) -> bool:
    with get_conn() as c:
        cur = c.execute("DELETE FROM conversation WHERE id=? AND user_id=?", (conv_id, user_id))
        return cur.rowcount > 0


# ---------- report_analysis（user_id 归属） ----------

def insert_report(user_id: int, file_name: str, file_size: int) -> int:
    with get_conn() as c:
        cur = c.execute(
            "INSERT INTO report_analysis (user_id, file_name, file_size, status) VALUES (?,?,?,'processing')",
            (user_id, file_name, file_size))
        return cur.lastrowid


def has_processing(user_id: int) -> bool:
    with get_conn() as c:
        return c.execute("SELECT 1 FROM report_analysis WHERE user_id=? AND status='processing'",
                         (user_id,)).fetchone() is not None


def finish_report(report_id: int, result: dict | None, error: tuple | None):
    """result: 四段式 dict（成功）；error: (code, message)（失败）。"""
    with get_conn() as c:
        if error:
            c.execute("UPDATE report_analysis SET status='failed', error_message=? WHERE id=?",
                      (f"{error[0]}|{error[1]}", report_id))  # 存储格式：错误码|用户文案
        else:
            bi, items, advice, prec = (result["basic_info"], result["abnormal_items"],
                                       result["overall_advice"], result["precautions"])
            c.execute(
                """UPDATE report_analysis SET status='success', basic_info=?, abnormal_items=?,
                          overall_advice=?, precautions=?, has_critical=? WHERE id=?""",
                (json.dumps(bi, ensure_ascii=False), json.dumps(items, ensure_ascii=False),
                 advice, prec, 1 if any(i["critical"] for i in items) else 0, report_id))


def get_report(user_id: int, report_id: int) -> dict | None:
    with get_conn() as c:
        row = c.execute("SELECT * FROM report_analysis WHERE id=? AND user_id=?", (report_id, user_id)).fetchone()
    if not row:
        return None
    d = dict(row)
    for jf in ("basic_info", "abnormal_items"):
        d[jf] = json.loads(d[jf]) if d[jf] else None
    return d


def list_reports(user_id: int, page: int, size: int) -> dict:
    """仅 success 记录（US-304：失败不进历史列表）。"""
    with get_conn() as c:
        total = c.execute("SELECT COUNT(*) FROM report_analysis WHERE user_id=? AND status='success'",
                          (user_id,)).fetchone()[0]
        rows = c.execute(
            """SELECT id, file_name, abnormal_items, has_critical, overall_advice, created_at
               FROM report_analysis WHERE user_id=? AND status='success'
               ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            (user_id, size, (page - 1) * size)).fetchall()
    lst = []
    for r in rows:
        items = json.loads(r["abnormal_items"] or "[]")
        first = (r["overall_advice"] or "").replace("\n", " ")
        lst.append({"id": r["id"], "file_name": r["file_name"], "abnormal_count": len(items),
                    "has_critical": bool(r["has_critical"]),
                    "summary": first[:40] + ("…" if len(first) > 40 else ""),
                    "created_at": r["created_at"]})
    return {"total": total, "list": lst}


def delete_report(user_id: int, report_id: int) -> bool:
    with get_conn() as c:
        cur = c.execute("DELETE FROM report_analysis WHERE id=? AND user_id=?", (report_id, user_id))
        return cur.rowcount > 0


def cleanup_zombies():
    """启动时清理僵尸 processing 记录（业务术语表·僵尸记录）。"""
    with get_conn() as c:
        c.execute(
            """UPDATE report_analysis SET status='failed', error_message='4202|服务响应超时，请稍后重试'
               WHERE status='processing' AND created_at < datetime('now','localtime', ?)""",
            (f"-{ZOMBIE_MINUTES} minutes",))
