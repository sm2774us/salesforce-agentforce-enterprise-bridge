"""RFC 7523 JWT-bearer assertions signed with an RSA private key.

Salesforce verifies the signature against the certificate uploaded to the
External Client App, so no client secret ever leaves the integration host.
"""

from __future__ import annotations

import base64
import json

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

JWT_BEARER_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"


def _b64url(data: bytes) -> str:
    """Returns unpadded URL-safe base64."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def load_private_key(pem: str, passphrase: str = "") -> rsa.RSAPrivateKey:
    """Parses a PEM RSA private key (PKCS#1 or PKCS#8, optionally encrypted).

    Args:
      pem: PEM text.
      passphrase: Passphrase for an encrypted key; empty if unencrypted.

    Returns:
      The RSA private key.

    Raises:
      ValueError: If the PEM is invalid, the passphrase is wrong/missing, or
        the key is not RSA.
    """
    try:
        key = serialization.load_pem_private_key(
            pem.encode("utf-8"), password=passphrase.encode("utf-8") or None
        )
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid private key or passphrase") from exc
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError("private key must be an RSA key")
    return key


def build_assertion(
    client_id: str,
    username: str,
    audience: str,
    key: rsa.RSAPrivateKey,
    now: float,
    lifetime_seconds: int = 180,
) -> str:
    """Builds and signs (RS256) a short-lived JWT assertion.

    Args:
      client_id: External Client App consumer key (``iss``).
      username: Salesforce username to act as (``sub``).
      audience: ``https://login.salesforce.com`` or the sandbox/community URL.
      key: RSA private key matching the uploaded certificate.
      now: Current epoch seconds.
      lifetime_seconds: Validity window (Salesforce allows <= 3 minutes).

    Returns:
      The compact serialised JWT.
    """

    def part(obj: dict[str, object]) -> str:
        return _b64url(json.dumps(obj, separators=(",", ":")).encode("utf-8"))

    signing_input = (
        part({"alg": "RS256", "typ": "JWT"})
        + "."
        + part(
            {
                "iss": client_id,
                "sub": username,
                "aud": audience,
                "exp": int(now) + lifetime_seconds,
            }
        )
    )
    signature = key.sign(
        signing_input.encode("ascii"), padding.PKCS1v15(), hashes.SHA256()
    )
    return f"{signing_input}.{_b64url(signature)}"
