"""Inbound Cognito M2M: Bearer token required, CRUD scope checked.

Hub HTTP CRUD (public catalog, admin, report-packet) accepts only
``Authorization: Bearer <access_token>``.

* Prod/dev: RS256 via ``HUB_M2M_ISSUER`` JWKS.
* Tests: HS256 via ``HUB_M2M_TEST_SECRET`` (never set in AWS).

Token ``scope`` must include ``{HUB_M2M_RESOURCE}/{resource}.{crud}``
(default ``hub/catalog.read``). ``{server}/{resource}.*`` and
``{server}/{resource}.write`` (non-read) are also accepted. Each service
owns its own Cognito resource server; Hub only accepts ``hub/…``.

WordPress HMAC and S3→Lambda are not handled here.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import jwt
from fastapi import HTTPException, Request
from jwt import PyJWKClient

from config import Settings

log = logging.getLogger(__name__)

_METHOD_TO_CRUD = {
    "GET": "read",
    "HEAD": "read",
    "OPTIONS": "read",
    "POST": "create",
    "PUT": "update",
    "PATCH": "update",
    "DELETE": "delete",
}


def crud_for_method(method: str) -> str:
    return _METHOD_TO_CRUD.get((method or "GET").upper(), "read")


def required_scope(resource: str, method: str, *, server: str = "hub") -> str:
    ident = (server or "hub").strip().strip("/")
    return f"{ident}/{resource}.{crud_for_method(method)}"


def token_scopes(payload: dict[str, Any]) -> set[str]:
    raw = payload.get("scope") or payload.get("scp") or ""
    if isinstance(raw, list):
        return {str(item) for item in raw if item}
    return {part for part in str(raw).split() if part}


def has_required_scope(scopes: set[str], needed: str) -> bool:
    if needed in scopes:
        return True
    if "." not in needed:
        return False
    prefix, verb = needed.rsplit(".", 1)
    if f"{prefix}.*" in scopes:
        return True
    if verb != "read" and f"{prefix}.write" in scopes:
        return True
    return False


@lru_cache(maxsize=8)
def _jwks_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=3600)


def jwks_url_for(settings: Settings) -> str:
    if settings.hub_m2m_jwks_url:
        return settings.hub_m2m_jwks_url.rstrip("/")
    issuer = (settings.hub_m2m_issuer or "").rstrip("/")
    return f"{issuer}/.well-known/jwks.json"


def cognito_issuer_aliases(issuer: str) -> list[str]:
    """Accept both Cognito iss hosts (cognito-idp and issuer-cognito-idp)."""
    value = (issuer or "").strip().rstrip("/")
    if not value:
        return []
    aliases = {value}
    if "://issuer-cognito-idp." in value:
        aliases.add(value.replace("://issuer-cognito-idp.", "://cognito-idp.", 1))
    elif "://cognito-idp." in value:
        aliases.add(value.replace("://cognito-idp.", "://issuer-cognito-idp.", 1))
    return sorted(aliases)


def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
    issuer = (settings.hub_m2m_issuer or "").strip()
    test_secret = (settings.hub_m2m_test_secret or "").strip()
    try:
        if test_secret:
            decode_kwargs: dict[str, Any] = {
                "algorithms": ["HS256"],
                "options": {"require": ["exp"]},
            }
            if issuer:
                decode_kwargs["issuer"] = issuer
            payload = jwt.decode(token, test_secret, **decode_kwargs)
        else:
            if not issuer:
                raise HTTPException(
                    status_code=401, detail="M2M issuer is not configured"
                )
            signing_key = _jwks_client(jwks_url_for(settings)).get_signing_key_from_jwt(
                token
            )
            decode_kwargs = {
                "algorithms": ["RS256"],
                "issuer": cognito_issuer_aliases(issuer),
                "options": {
                    "verify_aud": bool(settings.hub_m2m_audience),
                    "require": ["exp", "iss"],
                },
            }
            if settings.hub_m2m_audience:
                decode_kwargs["audience"] = settings.hub_m2m_audience
            payload = jwt.decode(token, signing_key.key, **decode_kwargs)
    except HTTPException:
        raise
    except Exception as exc:
        log.info("M2M token rejected: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid bearer token") from exc

    token_use = payload.get("token_use")
    if token_use is not None and token_use != "access":
        raise HTTPException(status_code=401, detail="Invalid bearer token")
    audience = (settings.hub_m2m_audience or "").strip()
    if audience and not test_secret:
        aud = payload.get("aud")
        client_id = str(payload.get("client_id") or "")
        aud_ok = audience == client_id or audience == aud or (
            isinstance(aud, list) and audience in aud
        )
        if not aud_ok:
            raise HTTPException(status_code=401, detail="Invalid bearer token")
    return payload


def require_m2m_token(
    request: Request,
    settings: Settings,
    *,
    resource: str,
    authorization: str | None,
) -> str:
    header = (authorization or "").strip()
    if not header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = header[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    payload = decode_access_token(token, settings)
    needed = required_scope(
        resource, request.method, server=settings.hub_m2m_resource
    )
    if not has_required_scope(token_scopes(payload), needed):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return f"m2m:{payload.get('client_id') or payload.get('sub') or 'ok'}"
