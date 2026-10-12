"""Authentication, authorization, sessions, user administration and the audit log."""

import re
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import verify_password
from app.main import create_app
from app.models import AuditEvent, User, UserSession
from scripts import manage_users
from tests.conftest import TEST_PASSWORD, create_test_user

SETUP = {"email": "Owner@Example.com", "name": "  Owner   One ", "password": "a-long-pass-phrase"}

# --- the access policy, stated explicitly -------------------------------------

PUBLIC = {
    ("GET", "/api/v1/health"),
    ("GET", "/api/v1/ready"),
    ("GET", "/api/v1/auth/status"),
    ("POST", "/api/v1/auth/setup"),
    ("POST", "/api/v1/auth/login"),
    ("GET", "/api/v1/imports/template.csv"),
}
SELF_SERVICE = {  # any signed-in user, including viewers
    ("GET", "/api/v1/auth/me"),
    ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/auth/change-password"),
}
ADMIN_ONLY = {
    ("DELETE", "/api/v1/imports/{import_id}"),
    ("PUT", "/api/v1/anomalies/settings"),
    ("POST", "/api/v1/allocation-rules"),
    ("PUT", "/api/v1/allocation-rules/{rule_id}"),
    ("DELETE", "/api/v1/allocation-rules/{rule_id}"),
    ("POST", "/api/v1/notifications/channels"),
    ("PUT", "/api/v1/notifications/channels/{channel_id}"),
    ("DELETE", "/api/v1/notifications/channels/{channel_id}"),
    ("POST", "/api/v1/notifications/channels/{channel_id}/test"),
    ("GET", "/api/v1/users"),
    ("POST", "/api/v1/users"),
    ("PATCH", "/api/v1/users/{user_id}"),
    ("POST", "/api/v1/users/{user_id}/reset-password"),
    ("GET", "/api/v1/audit-events"),
}


def required_role(method: str, path: str) -> str | None:
    """None = public. Otherwise the minimum role the policy demands."""
    if (method, path) in PUBLIC:
        return None
    if (method, path) in SELF_SERVICE:
        return "viewer"
    if (method, path) in ADMIN_ONLY:
        return "admin"
    return "viewer" if method == "GET" else "member"


def all_routes() -> list[tuple[str, str]]:
    spec = create_app().openapi()
    return sorted(
        (method.upper(), path)
        for path, operations in spec["paths"].items()
        for method in operations
    )


def call(client: TestClient, method: str, path: str):
    url = re.sub(r"\{[^}]+\}", "999999", path)
    return client.request(method, url, json={} if method in {"POST", "PUT", "PATCH"} else None)


def test_policy_covers_every_listed_route() -> None:
    routes = set(all_routes())
    for listed in PUBLIC | SELF_SERVICE | ADMIN_ONLY:
        assert listed in routes, f"policy lists a route that no longer exists: {listed}"


@pytest.mark.parametrize(("method", "path"), all_routes())
def test_every_route_enforces_the_access_policy(client_for, method: str, path: str) -> None:
    role = required_role(method, path)
    anonymous = call(client_for(None), method, path)
    if role is None:
        assert anonymous.status_code != 401, f"{method} {path} should be public"
        return
    assert anonymous.status_code == 401, f"{method} {path} must require sign-in"
    assert anonymous.json()["error"]["code"] == "not_authenticated"
    assert anonymous.headers["WWW-Authenticate"] == "Bearer"

    for actor in ("viewer", "member", "admin"):
        response = call(client_for(actor), method, path)
        allowed = ["viewer", "member", "admin"].index(actor) >= ["viewer", "member", "admin"].index(
            role
        )
        if allowed:
            assert response.status_code not in (401, 403), (actor, method, path, response.json())
        else:
            assert response.status_code == 403, (actor, method, path, response.status_code)
            assert response.json()["error"]["code"] == "forbidden"


# --- setup and login -------------------------------------------------------------


def test_first_run_setup_creates_admin_once(anon_client: TestClient, db: Session) -> None:
    assert anon_client.get("/api/v1/auth/status").json() == {"setup_required": True}
    response = anon_client.post("/api/v1/auth/setup", json=SETUP)
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["user"]["email"] == "owner@example.com"  # normalized
    assert body["user"]["name"] == "Owner One"
    assert body["user"]["role"] == "admin"
    assert body["token_type"] == "bearer" and len(body["token"]) >= 40

    assert anon_client.get("/api/v1/auth/status").json() == {"setup_required": False}
    again = anon_client.post("/api/v1/auth/setup", json={**SETUP, "email": "x@example.com"})
    assert again.status_code == 409

    # Only the token's hash is stored.
    stored = db.scalars(select(UserSession.token_hash)).one()
    assert stored != body["token"] and len(stored) == 64


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({**SETUP, "password": "short"}, "weak_password"),
        ({**SETUP, "password": "aaaaaaaaaaaa"}, "weak_password"),
        ({**SETUP, "password": " padded-password "}, "weak_password"),
        ({**SETUP, "email": "not-an-email"}, "validation_error"),
        ({**SETUP, "name": "   "}, "validation_error"),
    ],
)
def test_setup_validates_input(anon_client: TestClient, payload: dict, code: str) -> None:
    response = anon_client.post("/api/v1/auth/setup", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code


def test_login_me_and_generic_failure_message(anon_client: TestClient, db: Session) -> None:
    create_test_user(db, "member", email="member@example.com")
    ok = anon_client.post(
        "/api/v1/auth/login", json={"email": " MEMBER@example.com", "password": TEST_PASSWORD}
    )
    assert ok.status_code == 200, ok.json()
    token = ok.json()["token"]
    me = anon_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["email"] == "member@example.com" and me.json()["role"] == "member"

    wrong = anon_client.post(
        "/api/v1/auth/login", json={"email": "member@example.com", "password": "wrong-password"}
    )
    unknown = anon_client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong-password"}
    )
    # Same status and message: responses do not reveal whether an account exists.
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_repeated_failures_lock_the_account(anon_client: TestClient, db: Session) -> None:
    user, _ = create_test_user(db, "viewer", email="v@example.com")
    bad = {"email": "v@example.com", "password": "not-the-password"}
    for _ in range(5):
        assert anon_client.post("/api/v1/auth/login", json=bad).status_code == 401
    good = {"email": "v@example.com", "password": TEST_PASSWORD}
    locked = anon_client.post("/api/v1/auth/login", json=good)
    assert locked.status_code == 429
    assert locked.json()["error"]["code"] == "account_locked"
    assert int(locked.headers["Retry-After"]) > 0

    db.execute(
        update(User)
        .where(User.id == user.id)
        .values(locked_until=datetime.now(UTC) - timedelta(seconds=1))
    )
    db.commit()
    assert anon_client.post("/api/v1/auth/login", json=good).status_code == 200


def test_logout_revokes_the_token(client: TestClient) -> None:
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.post("/api/v1/auth/logout").status_code == 204
    after = client.get("/api/v1/auth/me")
    assert after.status_code == 401
    assert after.json()["error"]["code"] == "invalid_token"


def test_expired_session_and_deactivated_user_are_rejected(
    anon_client: TestClient, db: Session
) -> None:
    user, token = create_test_user(db, "member")
    headers = {"Authorization": f"Bearer {token}"}
    assert anon_client.get("/api/v1/costs/data-status", headers=headers).status_code == 200

    db.execute(update(User).where(User.id == user.id).values(is_active=False))
    db.commit()
    assert anon_client.get("/api/v1/costs/data-status", headers=headers).status_code == 401
    login = anon_client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    assert login.status_code == 401

    db.execute(update(User).where(User.id == user.id).values(is_active=True))
    db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id)
        .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    db.commit()
    assert anon_client.get("/api/v1/costs/data-status", headers=headers).status_code == 401
    malformed = anon_client.get("/api/v1/costs/data-status", headers={"Authorization": "Basic abc"})
    assert malformed.status_code == 401


def test_change_password_revokes_other_sessions(client_for, anon_client: TestClient) -> None:
    first = client_for("member")
    me = first.get("/api/v1/auth/me").json()
    second = anon_client.post(
        "/api/v1/auth/login", json={"email": me["email"], "password": TEST_PASSWORD}
    ).json()["token"]

    wrong = first.post(
        "/api/v1/auth/change-password",
        json={"current_password": "nope-nope-nope", "new_password": "another-long-pass"},
    )
    assert wrong.status_code == 400
    weak = first.post(
        "/api/v1/auth/change-password",
        json={"current_password": TEST_PASSWORD, "new_password": "short"},
    )
    assert weak.status_code == 422
    ok = first.post(
        "/api/v1/auth/change-password",
        json={"current_password": TEST_PASSWORD, "new_password": "another-long-pass"},
    )
    assert ok.status_code == 204
    assert first.get("/api/v1/auth/me").status_code == 200  # this session survives
    other = anon_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {second}"})
    assert other.status_code == 401  # the other session was revoked
    relogin = anon_client.post(
        "/api/v1/auth/login", json={"email": me["email"], "password": "another-long-pass"}
    )
    assert relogin.status_code == 200


# --- user administration ------------------------------------------------------------


def test_admin_manages_users_with_safeguards(client: TestClient, anon_client: TestClient) -> None:
    created = client.post(
        "/api/v1/users",
        json={
            "email": "new@example.com",
            "name": "New Person",
            "role": "viewer",
            "password": "initial-password-1",
        },
    )
    assert created.status_code == 201, created.json()
    user_id = created.json()["id"]
    duplicate = client.post(
        "/api/v1/users",
        json={
            "email": "NEW@example.com",
            "name": "Dup",
            "role": "viewer",
            "password": "initial-password-1",
        },
    )
    assert duplicate.status_code == 409

    promoted = client.patch(f"/api/v1/users/{user_id}", json={"role": "member"})
    assert promoted.json()["role"] == "member"
    assert len(client.get("/api/v1/users").json()) == 2

    me = client.get("/api/v1/auth/me").json()
    demote_self = client.patch(f"/api/v1/users/{me['id']}", json={"role": "viewer"})
    assert demote_self.status_code == 409
    deactivate_self = client.patch(f"/api/v1/users/{me['id']}", json={"is_active": False})
    assert deactivate_self.status_code == 409

    login = anon_client.post(
        "/api/v1/auth/login", json={"email": "new@example.com", "password": "initial-password-1"}
    )
    token = login.json()["token"]
    reset = client.post(
        f"/api/v1/users/{user_id}/reset-password", json={"password": "reset-password-22"}
    )
    assert reset.status_code == 204
    revoked = anon_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert revoked.status_code == 401

    deactivated = client.patch(f"/api/v1/users/{user_id}", json={"is_active": False})
    assert deactivated.json()["is_active"] is False
    assert client.patch("/api/v1/users/999999", json={"name": "x"}).status_code == 404


def test_last_active_admin_cannot_be_removed(client_for, db: Session) -> None:
    admin = client_for("admin")
    other_admin, _ = create_test_user(db, "admin", email="second-admin@example.com")
    assert (
        admin.patch(f"/api/v1/users/{other_admin.id}", json={"role": "member"}).status_code == 200
    )
    # Now only the caller is an admin; demoting it is blocked by the self rule above,
    # and no other admin can be demoted below one active admin either.
    me = admin.get("/api/v1/auth/me").json()
    assert admin.patch(f"/api/v1/users/{me['id']}", json={"role": "member"}).status_code == 409


def test_audit_log_records_security_and_admin_actions(
    client: TestClient, anon_client: TestClient, db: Session
) -> None:
    anon_client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": "bad-password-x"}
    )
    client.post(
        "/api/v1/users",
        json={
            "email": "a2@example.com",
            "name": "A Two",
            "role": "viewer",
            "password": "initial-password-1",
        },
    )
    client.post(
        "/api/v1/imports",
        files={
            "file": (
                "b.csv",
                b"usage_date,provider,service,currency,cost\n2026-10-01,aws,EC2,USD,1\n",
                "text/csv",
            )
        },
    )
    events = client.get("/api/v1/audit-events?limit=50").json()["items"]
    actions = [e["action"] for e in events]
    assert {"auth.login_failed", "user.created", "import.uploaded"} <= set(actions)
    failed = next(e for e in events if e["action"] == "auth.login_failed")
    assert failed["actor_user_id"] is None and failed["actor_email"] == "admin@example.com"
    upload = next(e for e in events if e["action"] == "import.uploaded")
    assert upload["actor_email"] == "admin@example.com"
    assert upload["details"]["rows_inserted"] == 1
    assert upload["request_id"]
    filtered = client.get("/api/v1/audit-events?action=user.created").json()
    assert filtered["total"] == 1
    assert db.scalar(select(AuditEvent.action).where(AuditEvent.action == "auth.login_failed"))


# --- request ids and unexpected errors ----------------------------------------------


def test_request_id_is_generated_or_propagated(anon_client: TestClient) -> None:
    generated = anon_client.get("/api/v1/health")
    assert re.fullmatch(r"[0-9a-f]{32}", generated.headers["X-Request-ID"])
    echoed = anon_client.get("/api/v1/health", headers={"X-Request-ID": "trace-123"})
    assert echoed.headers["X-Request-ID"] == "trace-123"
    unsafe = anon_client.get("/api/v1/health", headers={"X-Request-ID": "bad value\nwith newline"})
    assert unsafe.headers["X-Request-ID"] != "bad value\nwith newline"


def test_unhandled_errors_return_envelope_with_request_id() -> None:
    app = create_app()

    @app.get("/api/v1/_boom")
    def boom() -> None:
        raise RuntimeError("internal detail that must not leak")

    with TestClient(app) as test_client:
        response = test_client.get("/api/v1/_boom", headers={"X-Request-ID": "req-500"})
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["details"] == {"request_id": "req-500"}
    assert "internal detail" not in response.text


def test_cli_creates_admin_and_resets_password(monkeypatch, db: Session) -> None:
    """The account-recovery CLI creates admins and resets passwords."""
    test_sessions = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(manage_users, "get_sessionmaker", lambda: test_sessions)

    monkeypatch.setenv("CLOUDPULSE_PASSWORD", "cli-created-password")
    monkeypatch.setattr(
        "sys.argv", ["manage_users", "create-admin", "--email", "Ops@Example.com", "--name", "Ops"]
    )
    manage_users.main()
    user = db.scalars(select(User).where(User.email == "ops@example.com")).one()
    assert user.role == "admin"

    monkeypatch.setenv("CLOUDPULSE_PASSWORD", "cli-reset-password-2")
    monkeypatch.setattr(
        "sys.argv", ["manage_users", "reset-password", "--email", "ops@example.com"]
    )
    manage_users.main()
    db.expire_all()
    assert verify_password("cli-reset-password-2", db.get(User, user.id).password_hash)
