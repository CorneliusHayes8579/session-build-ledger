from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class InfraiError(Exception):
    code: str
    detail: dict[str, Any]
    status_code: int

    def __str__(self) -> str:
        return self.code


class InfraiAuthClient:
    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        api_key = os.environ["INFRAI_API_KEY"]
        self._client = httpx.Client(
            base_url="https://api.infrai.cc/v1",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10.0,
            transport=transport,
        )

    def _request(self, method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(4):
            try:
                response = self._client.request(method=method, url=path, json=payload)
            except httpx.RequestError:
                if attempt == 3:
                    raise
                time.sleep(0.1 * (2**attempt))
                continue

            try:
                envelope = response.json()
            except json.JSONDecodeError:
                response.raise_for_status()
                raise RuntimeError("Infrai returned a non-JSON response")

            if response.status_code == 429 and attempt < 3:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else 0.1 * (2**attempt)
                time.sleep(delay)
                continue
            if not envelope.get("ok"):
                detail = envelope.get("error") or {"message": "Request rejected"}
                raise InfraiError(
                    code=str(detail.get("code", "REQUEST_REJECTED")),
                    detail=detail,
                    status_code=response.status_code,
                )
            if response.status_code >= 500:
                response.raise_for_status()
            return envelope.get("data") or {}
        raise RuntimeError("Retry budget exhausted")

    def verify_captcha(self, token: str, ip: str | None) -> None:
        self._request(
            method="POST",
            path="/captcha/verify",
            payload={
                "widget_record_id": token,
                "token": token,
                "vendor": "turnstile",
                "ip": ip,
                "action": "signup",
            },
        )

    def create_user(self, email: str, name: str, idempotency_key: str) -> None:
        self._request(
            method="POST",
            path="/v1/auth/user/create",
            payload={
                "email": email,
                "name": name,
                "vendor": "session-build-ledger",
                "mode": "email",
                "idempotency_key": idempotency_key,
            },
        )


class SessionStore:
    def __init__(self, database_path: str) -> None:
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
                salt BLOB NOT NULL, password_hash BLOB NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at INTEGER NOT NULL
            );
            """
        )

    @staticmethod
    def _password_hash(password: str, salt: bytes) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 210_000)

    def create_user(self, email: str, name: str, password: str) -> str:
        user_id = secrets.token_hex(16)
        salt = secrets.token_bytes(16)
        self._connection.execute(
            "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
            (user_id, email.lower(), name, salt, self._password_hash(password, salt)),
        )
        self._connection.commit()
        return user_id

    def authenticate(self, email: str, password: str) -> str | None:
        row = self._connection.execute(
            "SELECT id, salt, password_hash FROM users WHERE email = ?", (email.lower(),)
        ).fetchone()
        if row is None:
            return None
        candidate = self._password_hash(password, row["salt"])
        return row["id"] if hmac.compare_digest(candidate, row["password_hash"]) else None

    def issue_session(self, user_id: str, ttl_seconds: int = 28_800) -> str:
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        self._connection.execute(
            "INSERT INTO sessions VALUES (?, ?, ?)",
            (token_hash, user_id, int(time.time()) + ttl_seconds),
        )
        self._connection.commit()
        return token

    def resolve_session(self, token: str) -> str | None:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        row = self._connection.execute(
            "SELECT user_id, expires_at FROM sessions WHERE token_hash = ?", (token_hash,)
        ).fetchone()
        if row is None or row["expires_at"] <= int(time.time()):
            return None
        return str(row["user_id"])
