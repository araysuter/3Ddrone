from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from fastapi import Cookie, Depends, Header, HTTPException, Request, Response, status

from .config import settings
from .db import one, transaction, utcnow

hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
SESSION_COOKIE = "mapper_session"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def setup_complete() -> bool:
    return one("SELECT id FROM admins WHERE id=1") is not None


def create_admin(username: str, password: str) -> None:
    if setup_complete():
        raise HTTPException(status_code=409, detail="Administrator setup is already complete")
    if len(username.strip()) < 3 or len(password) < 12:
        raise HTTPException(status_code=422, detail="Use a username of 3+ characters and password of 12+ characters")
    with transaction() as db:
        db.execute(
            "INSERT INTO admins(id,username,password_hash,created_at) VALUES(1,?,?,?)",
            (username.strip(), hasher.hash(password), utcnow()),
        )


def check_login_throttle(address: str) -> None:
    row = one("SELECT * FROM login_attempts WHERE address=?", (address,))
    if not row or not row["blocked_until"]:
        return
    if datetime.fromisoformat(row["blocked_until"]) > datetime.now(timezone.utc):
        raise HTTPException(status_code=429, detail="Too many login attempts; try again later")


def record_login(address: str, succeeded: bool) -> None:
    now = datetime.now(timezone.utc)
    existing = one("SELECT failures FROM login_attempts WHERE address=?", (address,))
    failures = 0 if succeeded else int(existing["failures"] if existing else 0) + 1
    blocked = (now + timedelta(minutes=15)).isoformat() if failures >= 5 else None
    with transaction() as db:
        db.execute(
            """
            INSERT INTO login_attempts(address,failures,blocked_until,updated_at)
            VALUES(?,?,?,?)
            ON CONFLICT(address) DO UPDATE SET
              failures=excluded.failures,
              blocked_until=excluded.blocked_until,
              updated_at=excluded.updated_at
            """,
            (address, failures, blocked, now.isoformat()),
        )


def verify_admin(username: str, password: str) -> bool:
    admin = one("SELECT * FROM admins WHERE id=1")
    if not admin or not secrets.compare_digest(admin["username"], username.strip()):
        return False
    try:
        return hasher.verify(admin["password_hash"], password)
    except Exception:
        return False


def start_session(response: Response) -> str:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    expires = datetime.now(timezone.utc) + timedelta(hours=settings.session_hours)
    with transaction() as db:
        db.execute(
            "INSERT INTO sessions(token_hash,csrf_token,expires_at,created_at) VALUES(?,?,?,?)",
            (token_hash(token), csrf, expires.isoformat(), utcnow()),
        )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        max_age=settings.session_hours * 3600,
        path="/",
    )
    return csrf


def end_session(response: Response, token: str | None) -> None:
    if token:
        with transaction() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(token),))
    response.delete_cookie(SESSION_COOKIE, path="/")


def require_session(mapper_session: str | None = Cookie(default=None)) -> dict:
    if not mapper_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required")
    session = one("SELECT * FROM sessions WHERE token_hash=?", (token_hash(mapper_session),))
    if not session or datetime.fromisoformat(session["expires_at"]) <= datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    return session


def require_csrf(
    request: Request,
    session: dict = Depends(require_session),
    x_csrf_token: str | None = Header(default=None),
) -> dict:
    if request.method not in {"GET", "HEAD", "OPTIONS"} and not secrets.compare_digest(
        x_csrf_token or "", session["csrf_token"]
    ):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    return session
