from release_policy import BuildEvent, BuildLedger, ReleaseOperation


def test_failed_build_cannot_be_released(tmp_path) -> None:
    ledger = BuildLedger(str(tmp_path / "ledger.db"))
    ledger.record_build(
        "developer-1",
        BuildEvent(build_id="build-104", commit_sha="a1b2c3d", status="failed"),
    )

    operation = ReleaseOperation(
        release_id="release-104", build_id="build-104", environment="production"
    )

    try:
        ledger.release("developer-1", operation)
    except PermissionError as error:
        assert str(error) == "build_not_passed"
    else:
        raise AssertionError("failed build was released")


def test_passed_build_produces_auditable_approval(tmp_path) -> None:
    ledger = BuildLedger(str(tmp_path / "ledger.db"))
    ledger.record_build(
        "developer-1",
        BuildEvent(build_id="build-105", commit_sha="f9e8d7c", status="passed"),
    )

    result = ledger.release(
        "developer-1",
        ReleaseOperation(
            release_id="release-105", build_id="build-105", environment="production"
        ),
    )

    assert result == {"release_id": "release-105", "decision": "approved"}
    assert ledger.diagnostics("developer-1") == {"build_events": 1, "release_operations": 1}
