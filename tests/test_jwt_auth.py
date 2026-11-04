import base64
import json
import urllib.parse

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

from bridge import cli
from bridge.config import Settings, load_dotenv
from bridge.jwt_auth import JWT_BEARER_GRANT, build_assertion, load_private_key
from bridge.salesforce import SalesforceClient, SalesforceError
from tests.conftest import no_sleep

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def pem(key=KEY, password=None):
    enc = (
        serialization.BestAvailableEncryption(password.encode())
        if password
        else serialization.NoEncryption()
    )
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        enc,
    ).decode()


def b64d(part):
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def test_assertion_signature_and_claims():
    token = build_assertion(
        "cid", "u@x.com", "https://login.salesforce.com", KEY, 1000.9
    )
    head, claims, sig = token.split(".")
    assert json.loads(b64d(head)) == {"alg": "RS256", "typ": "JWT"}
    assert json.loads(b64d(claims)) == {
        "iss": "cid",
        "sub": "u@x.com",
        "aud": "https://login.salesforce.com",
        "exp": 1180,
    }
    KEY.public_key().verify(
        b64d(sig),
        f"{head}.{claims}".encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    assert "=" not in token


def test_load_private_key_variants():
    assert load_private_key(pem()).key_size == 2048
    assert load_private_key(pem(password="pw"), "pw").key_size == 2048
    with pytest.raises(ValueError):
        load_private_key(pem(password="pw"))  # passphrase missing
    with pytest.raises(ValueError):
        load_private_key(pem(password="pw"), "wrong")
    with pytest.raises(ValueError):
        load_private_key("not a pem")
    ec_pem = pem(ec.generate_private_key(ec.SECP256R1()))
    with pytest.raises(ValueError, match="RSA"):
        load_private_key(ec_pem)


JWT_SETTINGS = Settings(
    sf_login_url="https://login.test",
    sf_client_id="cid",
    sf_username="u@x.com",
    sf_private_key=pem(),
)
TOKEN = {"access_token": "T", "instance_url": "https://inst.test"}


def make_client(handler, settings=JWT_SETTINGS):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SalesforceClient(
        settings, http=http, sleep=no_sleep, rng=lambda: 0, clock=lambda: 5000.0
    )


async def test_jwt_flow_sends_assertion_without_secret_and_caches_key():
    forms = []

    def handler(req: httpx.Request):
        if req.url.path == "/services/oauth2/token":
            forms.append(dict(urllib.parse.parse_qsl(req.content.decode())))
            return httpx.Response(200, json=TOKEN)
        if req.method == "POST":
            return (
                httpx.Response(401)
                if len(forms) < 2
                else httpx.Response(201, json={"id": "X"})
            )
        return httpx.Response(
            200, json={"DailyApiRequests": {"Max": 15000, "Remaining": 14990}}
        )

    c = make_client(handler)
    assert await c.create_record("Case", {}) == "X"  # 401 -> re-auth -> ok
    assert len(forms) == 2
    for form in forms:
        assert form["grant_type"] == JWT_BEARER_GRANT
        assert "client_secret" not in form and "client_id" not in form
        _, claims, _ = form["assertion"].split(".")
        assert json.loads(b64d(claims))["exp"] == 5180
    info = await c.verify()
    assert info == {
        "auth_mode": "jwt",
        "instance_url": "https://inst.test",
        "daily_api_remaining": 14990,
    }


async def test_verify_client_credentials_mode():
    s = Settings(
        sf_login_url="https://login.test",
        sf_client_id="i",
        sf_client_secret="s",
    )

    def handler(req):
        if req.url.path == "/services/oauth2/token":
            return httpx.Response(200, json=TOKEN)
        return httpx.Response(200, json={})

    info = await make_client(handler, s).verify()
    assert info["auth_mode"] == "client_credentials"
    assert info["daily_api_remaining"] is None


async def test_bad_key_is_not_retried_and_oauth_detail_surfaces():
    bad = Settings(sf_client_id="c", sf_username="u", sf_private_key="garbage")
    with pytest.raises(ValueError):
        await make_client(
            lambda r: httpx.Response(200, json=TOKEN), bad
        ).verify()

    body = {
        "error": "invalid_grant",
        "error_description": "user hasn't approved this consumer",
    }
    with pytest.raises(SalesforceError, match="invalid_grant"):
        await make_client(lambda r: httpx.Response(400, json=body)).verify()
    with pytest.raises(SalesforceError) as e:
        await make_client(lambda r: httpx.Response(400, json=["x"])).verify()
    assert str(e.value) == "OAuth failed: HTTP 400"


def test_settings_jwt_and_key_sources(tmp_path):
    f = tmp_path / "k.pem"
    f.write_text(pem())
    base = {"SF_CLIENT_ID": "c", "SF_USERNAME": "u@x.com"}
    s = Settings.from_env({**base, "SF_PRIVATE_KEY_PATH": str(f)})
    assert s.uses_jwt and s.salesforce_enabled and "BEGIN" in s.sf_private_key
    assert "BEGIN" not in repr(s)
    inline = pem().replace("\n", "\\n")
    s = Settings.from_env(
        {**base, "SF_PRIVATE_KEY": inline, "SF_PRIVATE_KEY_PATH": "/nope"}
    )
    assert s.sf_private_key == pem().strip()
    assert not Settings.from_env(base).salesforce_enabled  # no key, no secret
    assert Settings.from_env(
        {**base, "SF_CLIENT_SECRET": "s"}
    ).salesforce_enabled
    assert not Settings.from_env(
        {"SF_USERNAME": "u", "SF_PRIVATE_KEY": pem()}
    ).salesforce_enabled
    with pytest.raises(ValueError, match="SF_PRIVATE_KEY_PATH"):
        Settings.from_env(
            {**base, "SF_PRIVATE_KEY_PATH": str(tmp_path / "missing")}
        )


def test_load_dotenv(tmp_path):
    f = tmp_path / ".env"
    f.write_text(
        "# comment\n\nexport A=1\nB = 'two words'\nC=\"q\"\nD=x=y\nNOEQ\n=bad\nA=override\nE=''\nF=\"\n"
    )
    env = {"B": "keep"}
    assert load_dotenv(f, env) == 5
    assert env == {
        "B": "keep",
        "A": "1",
        "C": "q",
        "D": "x=y",
        "E": "",
        "F": '"',
    }
    assert load_dotenv(tmp_path / "absent", env) == 0


def test_cli_auth_check_and_env_file(tmp_path, monkeypatch):
    import io
    import os

    for k in (
        "SF_CLIENT_ID",
        "SF_CLIENT_SECRET",
        "SF_USERNAME",
        "SF_PRIVATE_KEY",
        "SF_PRIVATE_KEY_PATH",
    ):
        monkeypatch.delenv(k, raising=False)
    missing = tmp_path / "none.env"
    buf = io.StringIO()
    assert cli.main(["--env-file", str(missing), "auth-check"], buf) == 2
    assert "not configured" in buf.getvalue()

    class Fake:
        fail = False

        def __init__(self, settings):
            assert settings.uses_jwt

        async def verify(self):
            if Fake.fail:
                raise RuntimeError("boom")
            return {"auth_mode": "jwt"}

        async def aclose(self):
            return None

    monkeypatch.setattr(cli, "SalesforceClient", Fake)
    key = tmp_path / "k.pem"
    key.write_text(pem())
    env = tmp_path / ".env"
    env.write_text(
        f"SF_CLIENT_ID=cid\nSF_USERNAME=u@x.com\nSF_PRIVATE_KEY_PATH={key}\n"
    )
    try:
        buf = io.StringIO()
        assert cli.main(["--env-file", str(env), "auth-check"], buf) == 0
        assert 'OK: {"auth_mode": "jwt"}' in buf.getvalue()
        Fake.fail = True
        buf = io.StringIO()
        assert cli.main(["--env-file", str(env), "auth-check"], buf) == 1
        assert "FAILED: RuntimeError: boom" in buf.getvalue()
    finally:
        for k in ("SF_CLIENT_ID", "SF_USERNAME", "SF_PRIVATE_KEY_PATH"):
            os.environ.pop(k, None)
