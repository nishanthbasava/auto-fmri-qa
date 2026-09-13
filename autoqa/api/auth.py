"""Users, passwords, sessions, roles.

- Passwords are hashed with argon2id (memory-hard; the current OWASP default).
- A login returns a short-lived JWT (HS256, JWT_SECRET). The API is stateless:
  every request re-validates the token; there is no server-side session table.
- Roles are a hierarchy -- viewer < reviewer < admin -- enforced with
  `require_role("reviewer")` as a FastAPI dependency on each mutating endpoint.
- Bootstrap: `autoqa users add <name> --role admin`. For compatibility with the
  original single-password deployment, a bearer token equal to APP_PASSWORD is
  accepted as the built-in admin "lab" until real users exist.
"""
from __future__ import annotations

import datetime as dt
import os
import secrets
from dataclasses import dataclass

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import ROLES, User
from ..db.session import get_session

_ph = PasswordHasher()
TOKEN_TTL_HOURS = float(os.environ.get("AFQ_TOKEN_TTL_HOURS", "12"))


def _secret() -> str:
    s = os.environ.get("JWT_SECRET")
    if not s:
        # dev fallback: random per process -> tokens die on restart; log once
        s = os.environ["JWT_SECRET"] = secrets.token_urlsafe(32)
        print("WARNING: JWT_SECRET not set; using a per-process secret (tokens expire on restart)")
    return s


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, pw_hash: str) -> bool:
    try:
        return _ph.verify(pw_hash, pw)
    except VerifyMismatchError:
        return False


def create_token(user: User) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    return jwt.encode({"sub": user.username, "role": user.role, "uid": user.id,
                       "iat": now, "exp": now + dt.timedelta(hours=TOKEN_TTL_HOURS)},
                      _secret(), algorithm="HS256")


@dataclass
class Principal:
    id: int | None
    username: str
    role: str

    def can(self, role: str) -> bool:
        return ROLES.index(self.role) >= ROLES.index(role)


LEGACY_ADMIN = Principal(id=None, username="lab", role="admin")


def current_user(request: Request, db: Session = Depends(get_session)) -> Principal:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    token = header[7:].strip()
    legacy = os.environ.get("APP_PASSWORD")
    if legacy and secrets.compare_digest(token, legacy):
        return LEGACY_ADMIN
    try:
        claims = jwt.decode(token, _secret(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "token expired") from None
    except jwt.InvalidTokenError:
        raise HTTPException(401, "bad token") from None
    user = db.get(User, claims.get("uid"))
    if not user or not user.active or user.username != claims.get("sub"):
        raise HTTPException(401, "unknown or deactivated user")
    return Principal(id=user.id, username=user.username, role=user.role)


def require_role(role: str):
    if role not in ROLES:
        raise ValueError(f"unknown role {role}")

    def _dep(user: Principal = Depends(current_user)) -> Principal:
        if not user.can(role):
            raise HTTPException(403, f"requires role {role} (you are {user.role})")
        return user
    return _dep


def authenticate(db: Session, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == username))
    if user and user.active and verify_password(password, user.password_hash):
        return user
    return None


def create_user(db: Session, username: str, password: str, role: str = "viewer") -> User:
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    if db.scalar(select(User).where(User.username == username)):
        raise ValueError(f"user {username!r} already exists")
    u = User(username=username, password_hash=hash_password(password), role=role)
    db.add(u)
    db.flush()
    return u
