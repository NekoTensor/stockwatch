"""Getting back in, proving the address, and getting everyone else out.

Email delivery is off in the suite, so codes are read from the database. That
is also what makes these assertions about the *rules* rather than about Resend
being reachable.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.config import settings
from app.database.base import utcnow
from app.models import AuthToken, User
from app.services import auth_tokens
from app.services.security import hash_password


def latest_code_hash(db, purpose: str) -> AuthToken:
    return db.scalars(
        select(AuthToken).where(AuthToken.purpose == purpose).order_by(AuthToken.id.desc())
    ).first()


def issue_reset(db, email="shopper@example.com") -> str:
    """Mint a reset code directly, since the emailed one is never stored."""
    user = db.scalars(select(User).where(User.email == email)).first()
    code = auth_tokens.issue(db, user, auth_tokens.PASSWORD_RESET)
    db.commit()
    return code


# -------------------------------------------------------- forgot password ----


def test_forgot_password_says_the_same_thing_either_way(client, auth_headers, db):
    """Confirming which addresses have accounts is a list worth stealing."""
    known = client.post("/api/auth/password/forgot", json={"email": "shopper@example.com"})
    unknown = client.post("/api/auth/password/forgot", json={"email": "nobody@example.com"})

    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()

    # But only the real account got a code.
    assert latest_code_hash(db, auth_tokens.PASSWORD_RESET) is not None


def test_a_code_is_never_stored_in_the_clear(client, auth_headers, db):
    client.post("/api/auth/password/forgot", json={"email": "shopper@example.com"})

    entry = latest_code_hash(db, auth_tokens.PASSWORD_RESET)
    assert len(entry.token_hash) == 64
    assert entry.token_hash.isalnum()


# ----------------------------------------------------------------- reset ----


def test_a_reset_sets_the_new_password(client, auth_headers, db):
    code = issue_reset(db)

    reset = client.post(
        "/api/auth/password/reset", json={"code": code, "password": "brand-new-pw-7"}
    )
    assert reset.status_code == 200

    assert (
        client.post(
            "/api/auth/login",
            json={"email": "shopper@example.com", "password": "brand-new-pw-7"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/auth/login",
            json={"email": "shopper@example.com", "password": "correct-horse-9"},
        ).status_code
        == 401
    )


def test_a_reset_signs_every_other_session_out(client, auth_headers, db):
    """Someone resetting is locked out or worried; the sessions they cannot
    see are the ones that matter."""
    assert client.get("/api/auth/me", headers=auth_headers).status_code == 200

    code = issue_reset(db)
    client.post("/api/auth/password/reset", json={"code": code, "password": "brand-new-pw-7"})

    assert client.get("/api/auth/me", headers=auth_headers).status_code == 401


def test_a_reset_code_works_once(client, auth_headers, db):
    code = issue_reset(db)
    client.post("/api/auth/password/reset", json={"code": code, "password": "brand-new-pw-7"})

    again = client.post(
        "/api/auth/password/reset", json={"code": code, "password": "another-new-pw-8"}
    )
    assert again.status_code == 400


def test_asking_again_retires_the_earlier_code(client, auth_headers, db):
    first = issue_reset(db)
    issue_reset(db)

    assert (
        client.post(
            "/api/auth/password/reset", json={"code": first, "password": "brand-new-pw-7"}
        ).status_code
        == 400
    )


def test_an_expired_code_is_refused(client, auth_headers, db):
    code = issue_reset(db)
    entry = latest_code_hash(db, auth_tokens.PASSWORD_RESET)
    entry.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()

    assert (
        client.post(
            "/api/auth/password/reset", json={"code": code, "password": "brand-new-pw-7"}
        ).status_code
        == 400
    )


def test_a_reset_cannot_set_a_weak_password(client, auth_headers, db):
    """Otherwise reset is a way around the rule rather than a second opinion."""
    code = issue_reset(db)

    assert (
        client.post("/api/auth/password/reset", json={"code": code, "password": "short"}).status_code
        == 422
    )


def test_an_unknown_code_is_refused(client):
    assert (
        client.post(
            "/api/auth/password/reset", json={"code": "ZZZZZZZZZZ", "password": "brand-new-pw-7"}
        ).status_code
        == 400
    )


# -------------------------------------------------------------- revocation ----


def test_logout_everywhere_invalidates_other_sessions(client, auth_headers):
    second = client.post(
        "/api/auth/login", json={"email": "shopper@example.com", "password": "correct-horse-9"}
    ).json()
    other = {"Authorization": f"Bearer {second['access_token']}"}

    fresh = client.post("/api/auth/logout-all", headers=auth_headers)
    assert fresh.status_code == 200

    # The session that asked keeps working, with its new token.
    assert (
        client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {fresh.json()['access_token']}"},
        ).status_code
        == 200
    )
    assert client.get("/api/auth/me", headers=other).status_code == 401


def test_a_revoked_refresh_token_cannot_mint_a_new_session(client, auth_headers):
    """Otherwise signing out everywhere lasts until the access token expires."""
    login = client.post(
        "/api/auth/login", json={"email": "shopper@example.com", "password": "correct-horse-9"}
    ).json()

    client.post("/api/auth/logout-all", headers=auth_headers)

    assert (
        client.post(
            "/api/auth/refresh", json={"refresh_token": login["refresh_token"]}
        ).status_code
        == 401
    )


# ------------------------------------------------------------ verification ----


def test_a_new_account_is_unverified(client, auth_headers):
    assert client.get("/api/auth/me", headers=auth_headers).json()["email_verified"] is False


def test_verifying_marks_the_address(client, auth_headers, db):
    client.post("/api/auth/email/verify/request", headers=auth_headers)

    user = db.scalars(select(User).where(User.email == "shopper@example.com")).first()
    code = auth_tokens.issue(db, user, auth_tokens.EMAIL_VERIFY)
    db.commit()

    response = client.post("/api/auth/email/verify", json={"code": code}, headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["email_verified"] is True


def test_a_verification_code_belongs_to_one_account(client, auth_headers, db):
    """Holding a session is not the same as holding the address."""
    other = client.post(
        "/api/auth/register", json={"email": "other@example.com", "password": "correct-horse-9"}
    ).json()
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}

    victim = db.scalars(select(User).where(User.email == "shopper@example.com")).first()
    code = auth_tokens.issue(db, victim, auth_tokens.EMAIL_VERIFY)
    db.commit()

    assert (
        client.post("/api/auth/email/verify", json={"code": code}, headers=other_headers).status_code
        == 400
    )


def test_resetting_a_password_also_proves_the_address(client, auth_headers, db):
    """The code arrived in the inbox, which is what verification asks for."""
    code = issue_reset(db)
    tokens = client.post(
        "/api/auth/password/reset", json={"code": code, "password": "brand-new-pw-7"}
    ).json()

    me = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    ).json()
    assert me["email_verified"] is True


def test_tracking_can_require_a_verified_address(client, auth_headers, monkeypatch):
    from tests.test_api import TRACK_PAYLOAD

    monkeypatch.setattr(settings, "require_email_verification", True)

    blocked = client.post("/api/products/track", json=TRACK_PAYLOAD, headers=auth_headers)
    assert blocked.status_code == 403


def test_tracking_is_open_when_verification_is_not_required(client, auth_headers):
    """The default, so a deployment without email configured still works."""
    from tests.test_api import TRACK_PAYLOAD

    assert client.post(
        "/api/products/track", json=TRACK_PAYLOAD, headers=auth_headers
    ).status_code in (200, 201)


# ------------------------------------------------------------------ hygiene ----


def test_codes_are_unambiguous_and_unique(db):
    # Each test gets a clean schema, so the user has to be made here - a lookup
    # would find nothing and skip, which is a test that never runs.
    user = User(email="codes@example.com", hashed_password=hash_password("correct-horse-9"))
    db.add(user)
    db.commit()

    codes = {auth_tokens.issue(db, user, auth_tokens.EMAIL_VERIFY) for _ in range(20)}

    assert len(codes) == 20
    for code in codes:
        assert len(code) == 10
        assert not set(code) & set("IO01")
