from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class BuildEvent:
    build_id: str
    commit_sha: str
    status: str


@dataclass(frozen=True)
class ReleaseOperation:
    release_id: str
    build_id: str
    environment: str


class BuildLedger:
    def __init__(self, database_path: str) -> None:
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS builds (
                build_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, commit_sha TEXT NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS releases (
                release_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, build_id TEXT NOT NULL,
                environment TEXT NOT NULL
            );
            """
        )

    def record_build(self, user_id: str, event: BuildEvent) -> dict[str, str]:
        self._connection.execute(
            "INSERT INTO builds VALUES (?, ?, ?, ?)",
            (event.build_id, user_id, event.commit_sha, event.status),
        )
        self._connection.commit()
        return {"build_id": event.build_id, "status": event.status}

    def release(self, user_id: str, operation: ReleaseOperation) -> dict[str, str]:
        build = self._connection.execute(
            "SELECT status FROM builds WHERE build_id = ? AND user_id = ?",
            (operation.build_id, user_id),
        ).fetchone()
        if build is None:
            raise ValueError("build_not_found")
        if build["status"] != "passed":
            raise PermissionError("build_not_passed")
        self._connection.execute(
            "INSERT INTO releases VALUES (?, ?, ?, ?)",
            (operation.release_id, user_id, operation.build_id, operation.environment),
        )
        self._connection.commit()
        return {"release_id": operation.release_id, "decision": "approved"}

    def diagnostics(self, user_id: str) -> dict[str, int]:
        builds = self._connection.execute(
            "SELECT COUNT(*) AS count FROM builds WHERE user_id = ?", (user_id,)
        ).fetchone()["count"]
        releases = self._connection.execute(
            "SELECT COUNT(*) AS count FROM releases WHERE user_id = ?", (user_id,)
        ).fetchone()["count"]
        return {"build_events": builds, "release_operations": releases}

