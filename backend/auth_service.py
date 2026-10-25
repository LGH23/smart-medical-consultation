"""用户认证服务（API设计文档 A1~A4，数据库设计 V2.0）。
错误码：4401~4406 注册校验链 / 4410 登录失败统一文案 / 4411 凭证缺失失效。"""
import hashlib
import re
import secrets

import db

PBKDF2_ITER = 120_000
RE_USER = re.compile(r"^[A-Za-z0-9_]{3,20}$")
RE_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


class AuthError(Exception):
    """认证业务异常：code + 用户可见中文文案（与 API 文档 1.3 一致）。"""
    def __init__(self, code: int, message: str):
        self.code, self.message = code, message
        super().__init__(message)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITER)
    return f"pbkdf2_sha256${PBKDF2_ITER}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt_hex, dk_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters))
        return secrets.compare_digest(dk.hex(), dk_hex)
    except (ValueError, AttributeError):
        return False


def validate_register(username: str, email: str, password: str, confirm: str):
    """校验顺序严格按 API 文档 2.2（先格式后唯一），文案逐字一致。"""
    if not RE_USER.match(username or ""):
        raise AuthError(4403, "用户名需为 3-20 位字母、数字或下划线")
    if not (password and 6 <= len(password) <= 20):
        raise AuthError(4405, "密码需为 6-20 个字符")
    if password != confirm:
        raise AuthError(4406, "密码不一致，请重新输入")
    if not RE_EMAIL.match(email or ""):
        raise AuthError(4404, "邮箱格式不正确，请重新输入")
    if db.username_exists(username):
        raise AuthError(4401, "用户名已存在")
    if db.email_exists(email):
        raise AuthError(4402, "邮箱已被注册")


def register(username: str, email: str, password: str, confirm: str) -> str:
    validate_register(username, email, password, confirm)
    try:
        db.create_user(username, email, hash_password(password))
    except Exception as e:  # 并发注册撞唯一索引：回查具体冲突项
        if db.username_exists(username):
            raise AuthError(4401, "用户名已存在")
        if db.email_exists(email):
            raise AuthError(4402, "邮箱已被注册")
        raise e
    return username


def login(username: str, password: str) -> tuple[str, str]:
    """返回 (token, username)；失败统一 4410，不区分账号不存在/密码错误（防枚举）。"""
    user = db.get_user_by_name(username or "")
    if not user or not verify_password(password or "", user["password_hash"]):
        raise AuthError(4410, "用户名或密码错误")
    return db.create_token(user["id"]), user["username"]


def authenticate(token: str) -> dict:
    """X-Token → {user_id, username}；缺失/过期 4411。"""
    if token:
        row = db.get_token_user(token)
        if row:
            return row
    raise AuthError(4411, "登录已过期，请重新登录")


def logout(token: str):
    db.delete_token(token)  # 幂等：无效 Token 也返回成功


def seed_demo_admin():
    """首次启动播种演示账号 admin/123456（user 表为空时才执行，便于课程演示）。"""
    if db.user_count() == 0:
        db.create_user("admin", "admin@mail.com", hash_password("123456"))
