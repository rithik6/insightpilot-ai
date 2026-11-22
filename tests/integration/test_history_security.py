from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine

from app.core.config import Settings
from app.db.models import AnalysisRun, AnonymousSession, Conversation, Message, Report
from app.main import create_app

TRUSTED = {"Origin": "http://testserver"}
FOREIGN = {"Origin": "https://other.example"}
PDF = b"%PDF-1.4 test history"


def bootstrap(browser: TestClient) -> str:
    response = browser.post("/api/v1/session", headers=TRUSTED)
    assert response.status_code == 201
    return response.json()["csrf_token"]


def stored_digest(browser: TestClient) -> bytes:
    return sha256(browser.cookies["insightpilot_session"].encode("ascii")).digest()


def seed_history(
    engine: Engine, browser: TestClient, *, status: str = "ANSWERED"
) -> tuple[str, str, str]:
    with engine.begin() as connection:
        session_id = connection.execute(
            select(AnonymousSession.id).where(
                AnonymousSession.token_hash == stored_digest(browser)
            )
        ).scalar_one()
        conversation_id = connection.execute(
            insert(Conversation)
            .values(session_id=session_id, title="Owned history")
            .returning(Conversation.id)
        ).scalar_one()
        run_id = connection.execute(
            insert(AnalysisRun)
            .values(
                conversation_id=conversation_id,
                status=status,
                request_json={"schema_version": 1},
            )
            .returning(AnalysisRun.id)
        ).scalar_one()
        connection.execute(
            insert(Message).values(
                conversation_id=conversation_id,
                analysis_run_id=run_id,
                role="assistant",
                content="Private conversation",
            )
        )
        report_id = connection.execute(
            insert(Report)
            .values(
                analysis_run_id=run_id,
                title="Owned report",
                pdf_data=PDF,
                checksum_sha256=sha256(PDF).digest(),
            )
            .returning(Report.id)
        ).scalar_one()
    return str(conversation_id), str(run_id), str(report_id)


def test_history_run_and_report_are_session_owned(
    database_settings: Settings, postgres_engine: Engine
) -> None:
    with (
        TestClient(create_app(database_settings)) as owner,
        TestClient(create_app(database_settings)) as other,
    ):
        assert other.get("/api/v1/history").status_code == 401
        bootstrap(owner)
        bootstrap(other)
        conversation, run, report = seed_history(postgres_engine, owner)

        history = owner.get("/api/v1/history")
        assert (
            history.status_code == 200
            and history.headers["cache-control"] == "no-store"
        )
        assert [row["id"] for row in history.json()["conversations"]] == [conversation]
        assert [row["id"] for row in history.json()["reports"]] == [report]
        assert "pdf_data" not in history.json()["reports"][0]
        assert other.get("/api/v1/history").json() == {
            "conversations": [],
            "reports": [],
        }

        for path in (
            f"/conversations/{conversation}",
            f"/analyses/{run}",
            f"/reports/{report}/download",
        ):
            assert owner.get(f"/api/v1{path}").status_code == 200
            assert other.get(f"/api/v1{path}").status_code == 404

        download = owner.get(f"/api/v1/reports/{report}/download")
        assert download.content == PDF
        assert download.headers["content-type"] == "application/pdf"
        assert download.headers["cache-control"] == "no-store"
        assert (
            owner.get(f"/api/v1/conversations/{conversation}").json()["messages"][0][
                "content"
            ]
            == "Private conversation"
        )


def test_expired_cookie_cannot_read_history_and_can_bootstrap_again(
    database_settings: Settings, postgres_engine: Engine
) -> None:
    with TestClient(create_app(database_settings)) as browser:
        first_csrf = bootstrap(browser)
        conversation, _, _ = seed_history(postgres_engine, browser)
        now = datetime.now(UTC)
        with postgres_engine.begin() as connection:
            connection.execute(
                update(AnonymousSession)
                .where(AnonymousSession.token_hash == stored_digest(browser))
                .values(
                    created_at=now - timedelta(days=2),
                    expires_at=now - timedelta(days=1),
                )
            )

        assert browser.get(f"/api/v1/conversations/{conversation}").status_code == 401
        assert browser.get("/api/v1/history").status_code == 401
        assert bootstrap(browser) != first_csrf
        assert browser.get("/api/v1/history").json() == {
            "conversations": [],
            "reports": [],
        }


def test_deletion_requires_origin_csrf_and_ownership(
    database_settings: Settings, postgres_engine: Engine
) -> None:
    with (
        TestClient(create_app(database_settings)) as owner,
        TestClient(create_app(database_settings)) as other,
    ):
        token, other_token = bootstrap(owner), bootstrap(other)
        conversation, _, report = seed_history(postgres_engine, owner)
        target = f"/api/v1/history/{conversation}"

        for headers in (
            {"X-CSRF-Token": token},
            {**FOREIGN, "X-CSRF-Token": token},
            TRUSTED,
            {**TRUSTED, "X-CSRF-Token": other_token},
        ):
            assert owner.delete(target, headers=headers).status_code == 403
        assert (
            other.delete(
                target, headers={**TRUSTED, "X-CSRF-Token": other_token}
            ).status_code
            == 404
        )
        assert owner.get(f"/api/v1/reports/{report}/download").status_code == 200
        deleted = owner.delete(target, headers={**TRUSTED, "X-CSRF-Token": token})
        assert deleted.status_code == 204 and not deleted.content
        assert owner.get(f"/api/v1/reports/{report}/download").status_code == 404


def test_active_analysis_prevents_history_deletion(
    database_settings: Settings, postgres_engine: Engine
) -> None:
    with TestClient(create_app(database_settings)) as owner:
        token = bootstrap(owner)
        conversation, _, _ = seed_history(postgres_engine, owner, status="RUNNING")
        response = owner.delete(
            f"/api/v1/history/{conversation}",
            headers={**TRUSTED, "X-CSRF-Token": token},
        )
        assert response.status_code == 409
        assert owner.get(f"/api/v1/conversations/{conversation}").status_code == 200


def test_corrupt_report_is_never_returned(
    database_settings: Settings, postgres_engine: Engine
) -> None:
    with TestClient(create_app(database_settings)) as owner:
        bootstrap(owner)
        _, _, report = seed_history(postgres_engine, owner)
        with postgres_engine.begin() as connection:
            connection.execute(
                update(Report)
                .where(Report.id == UUID(report))
                .values(checksum_sha256=b"x" * 32)
            )

        response = owner.get(f"/api/v1/reports/{report}/download")
        assert response.status_code == 500
        assert response.json() == {"detail": "Internal server error."}


def test_bootstrap_rejects_untrusted_and_missing_origins(client: TestClient) -> None:
    for headers in ({}, FOREIGN):
        response = client.post("/api/v1/session", headers=headers)
        assert response.status_code == 403
        assert "set-cookie" not in response.headers


def test_cors_only_grants_credentialed_access_to_trusted_origins(
    client: TestClient,
) -> None:
    local = "http://127.0.0.1:8000"
    preflight = {
        "Access-Control-Request-Method": "DELETE",
        "Access-Control-Request-Headers": "x-csrf-token",
    }
    allowed = client.options(
        "/api/v1/history/example", headers={**preflight, "Origin": local}
    )
    denied = client.options("/api/v1/history/example", headers={**preflight, **FOREIGN})

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == local
    assert allowed.headers["access-control-allow-credentials"] == "true"
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers
