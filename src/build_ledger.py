from __future__ import annotations

import os
import json
import sqlite3
from dataclasses import dataclass

from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field

from developer_auth import InfraiAuthClient, InfraiError, SessionStore
from release_policy import BuildEvent, BuildLedger, ReleaseOperation


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12)
    name: str = Field(min_length=1, max_length=100)
    captcha_token: str = Field(min_length=1)
    request_id: str = Field(min_length=8, max_length=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class BuildEventRequest(BaseModel):
    build_id: str = Field(min_length=3, max_length=80)
    commit_sha: str = Field(pattern=r"^[0-9a-f]{7,40}$")
    status: str = Field(pattern=r"^(passed|failed)$")


class ReleaseRequest(BaseModel):
    release_id: str = Field(min_length=3, max_length=80)
    build_id: str = Field(min_length=3, max_length=80)
    environment: str = Field(pattern=r"^(staging|production)$")


@dataclass
class Services:
    auth: InfraiAuthClient
    sessions: SessionStore
    ledger: "BuildLedger"


def create_app(services: Services | None = None) -> FastAPI:
    if services is None:
        database_path = os.environ.get("LEDGER_DB", "build-ledger.db")
        services = Services(
            auth=InfraiAuthClient(),
            sessions=SessionStore(database_path),
            ledger=BuildLedger(database_path),
        )
    api = FastAPI(title="Developer Session Build Ledger")

    def current_user(session: str | None = Cookie(default=None)) -> str:
        user_id = services.sessions.resolve_session(session or "")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        return user_id

    @api.exception_handler(InfraiError)
    async def infrai_rejection(_: Request, error: InfraiError) -> Response:
        status = error.status_code if 400 <= error.status_code < 500 else 502
        return Response(
            content=json.dumps({"detail": error.detail}),
            status_code=status,
            media_type="application/json",
        )

    @api.post("/signup", status_code=201)
    def signup(body: SignupRequest, request: Request) -> dict[str, str]:
        services.auth.verify_captcha(body.captcha_token, request.client.host if request.client else None)
        services.auth.create_user(str(body.email), body.name, body.request_id)
        try:
            user_id = services.sessions.create_user(str(body.email), body.name, body.password)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Email already registered") from exc
        return {"user_id": user_id, "state": "registered"}

    @api.post("/login")
    def login(body: LoginRequest, response: Response) -> dict[str, str]:
        user_id = services.sessions.authenticate(str(body.email), body.password)
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        session = services.sessions.issue_session(user_id)
        secure_cookie = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
        response.set_cookie(
            "session", session, httponly=True, secure=secure_cookie, samesite="strict"
        )
        return {"state": "authenticated"}

    @api.post("/build-events", status_code=201)
    def record_build(body: BuildEventRequest, user_id: str = Depends(current_user)) -> dict[str, str]:
        return services.ledger.record_build(user_id, BuildEvent(**body.model_dump()))

    @api.post("/releases", status_code=201)
    def create_release(body: ReleaseRequest, user_id: str = Depends(current_user)) -> dict[str, str]:
        try:
            return services.ledger.release(user_id, ReleaseOperation(**body.model_dump()))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Build not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail="A passed build is required") from exc

    @api.get("/diagnostics")
    def diagnostics(user_id: str = Depends(current_user)) -> dict[str, int]:
        return services.ledger.diagnostics(user_id)

    return api

