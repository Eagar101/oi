"""JWT认证与密码哈希"""

import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from .config import APIConfig
from . import db


def _hash_password(password: str) -> str:
    """SHA256哈希（演示用，生产应换bcrypt）"""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _verify_password(password: str, password_hash: str) -> bool:
    expected = _hash_password(password)
    return hmac.compare_digest(expected, password_hash)


def _encode_jwt(payload: dict, config: APIConfig) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    segments = [
        _b64(json.dumps(header, separators=(",", ":"))),
        _b64(json.dumps(payload, separators=(",", ":"))),
    ]
    signing_input = ".".join(segments).encode("utf-8")
    sig = hmac.new(config.jwt_secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    segments.append(_b64(sig))
    return ".".join(segments)


def _decode_jwt(token: str, config: APIConfig) -> dict | None:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        signing_input = f"{parts[0]}.{parts[1]}".encode("utf-8")
        expected_sig = hmac.new(
            config.jwt_secret.encode("utf-8"), signing_input, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(_b64decode(parts[2]), expected_sig):
            return None
        payload = json.loads(_b64decode(parts[1]))
        if payload.get("exp") and payload["exp"] < time.time():
            return None
        return payload
    except Exception:
        return None


def _b64(data: bytes | str) -> str:
    import base64
    if isinstance(data, str):
        data = data.encode("utf-8")
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def _b64decode(s: str) -> bytes:
    import base64
    padding = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + padding)


@dataclass
class AuthResult:
    success: bool
    user_id: int | None = None
    username: str | None = None
    error: str | None = None


def register(username: str, password: str, config: APIConfig) -> AuthResult:
    if not username or not password:
        return AuthResult(success=False, error="用户名和密码不能为空")
    if len(password) < 6:
        return AuthResult(success=False, error="密码长度至少6位")
    if db.get_user_by_name(username):
        return AuthResult(success=False, error="用户名已存在")
    user_id = db.create_user(username, _hash_password(password))
    token = _create_token(user_id, username, config)
    return AuthResult(success=True, user_id=user_id, username=username, error=token)


def login(username: str, password: str, config: APIConfig) -> AuthResult:
    user = db.get_user_by_name(username)
    if not user or not _verify_password(password, user["password_hash"]):
        return AuthResult(success=False, error="用户名或密码错误")
    token = _create_token(user["id"], username, config)
    return AuthResult(success=True, user_id=user["id"], username=username, error=token)


def verify_token(token: str, config: APIConfig) -> AuthResult:
    payload = _decode_jwt(token, config)
    if not payload:
        return AuthResult(success=False, error="无效或过期的token")
    return AuthResult(
        success=True,
        user_id=payload.get("uid"),
        username=payload.get("username"),
    )


def _create_token(user_id: int, username: str, config: APIConfig) -> str:
    payload = {
        "uid": user_id,
        "username": username,
        "exp": int(time.time()) + config.jwt_expire_minutes * 60,
    }
    return _encode_jwt(payload, config)
