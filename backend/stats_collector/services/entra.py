"""Sign-in with Microsoft 365 (Entra ID) via OpenID Connect: authorization code flow with PKCE.

Roles come from Microsoft 365, read at every sign-in. The simplest way is app roles: the app
registration defines the roles in APP_ROLES (fixed values, so nothing has to be looked up) and
users or groups are assigned to them; Entra puts the values in the `roles` claim. Entra group
object IDs (or other app role values) can also be mapped per role under Roles & sign-in.
When a user is in more than ~200 groups Entra leaves the `groups` claim out ("group overage");
the groups are then read from Microsoft Graph with the user's token.
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
import time
import uuid
from typing import Any

import httpx
import jwt

from ..models import ROLES

SCOPES = "openid profile email User.Read"
LOGIN_HOST = "https://login.microsoftonline.com"
GRAPH = "https://graph.microsoft.com/v1.0"
_GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

# The app roles to create in the app registration. The values are what Entra sends in the `roles`
# claim; the ids are fixed so that pasting the manifest twice does not create duplicates.
APP_ROLES = {
    "admin": ("StatsCollector.Admin", "Stats Collector admin", "Everything, including settings and users."),
    "editor_in_chief": (
        "StatsCollector.EditorInChief",
        "Stats Collector editor-in-chief",
        "All numbers including per editor; dashboards, reports and goals.",
    ),
    "editor": ("StatsCollector.Editor", "Stats Collector editor", "All numbers plus their own editor numbers."),
    "staff": ("StatsCollector.Staff", "Stats Collector staff", "Views numbers without editor names."),
}


def app_roles() -> list[dict]:
    """The app roles in the shape of the app registration manifest (`appRoles`), plus our role key."""
    return [
        {
            "role": role,
            "allowedMemberTypes": ["User"],
            "description": description,
            "displayName": name,
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://stats-collector/app-role/{role}")),
            "isEnabled": True,
            "value": value,
        }
        for role, (value, name, description) in APP_ROLES.items()
    ]


_discovery_cache: dict[str, tuple[float, dict]] = {}
_jwks_clients: dict[str, jwt.PyJWKClient] = {}


class EntraError(Exception):
    pass


def check_config(cfg: dict, client_secret: str | None) -> None:
    tenant = (cfg.get("tenant_id") or "").strip()
    if not cfg.get("enabled"):
        raise EntraError("sso_disabled")
    if not tenant or tenant.lower() in ("common", "organizations", "consumers"):
        raise EntraError("sso_tenant_required")
    if not (cfg.get("client_id") or "").strip() or not client_secret:
        raise EntraError("sso_not_configured")


def discovery(tenant: str) -> dict:
    hit = _discovery_cache.get(tenant)
    if hit and hit[0] > time.time():
        return hit[1]
    url = f"{LOGIN_HOST}/{tenant}/v2.0/.well-known/openid-configuration"
    try:
        resp = httpx.get(url, timeout=10)
        resp.raise_for_status()
        doc = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise EntraError("sso_discovery_failed") from exc
    _discovery_cache[tenant] = (time.time() + 3600, doc)
    return doc


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(
    cfg: dict, redirect_uri: str, state: str, nonce: str, challenge: str, login_hint: str | None = None
) -> str:
    doc = discovery(cfg["tenant_id"].strip())
    params = {
        "client_id": cfg["client_id"].strip(),
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": SCOPES,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if login_hint:
        params["login_hint"] = login_hint
    return str(httpx.URL(doc["authorization_endpoint"], params=params))


def exchange_code(cfg: dict, client_secret: str, code: str, verifier: str, redirect_uri: str) -> dict:
    doc = discovery(cfg["tenant_id"].strip())
    data = {
        "client_id": cfg["client_id"].strip(),
        "client_secret": client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
        "scope": SCOPES,
    }
    try:
        resp = httpx.post(doc["token_endpoint"], data=data, timeout=15)
    except httpx.HTTPError as exc:
        raise EntraError("sso_token_failed") from exc
    if resp.status_code != 200:
        try:
            err = resp.json().get("error_codes") or resp.json().get("error")
        except ValueError:
            err = resp.status_code
        raise EntraError(f"sso_token_failed: {err}")
    return resp.json()


def _signing_key(jwks_uri: str, token: str):
    client = _jwks_clients.get(jwks_uri)
    if client is None:
        client = _jwks_clients[jwks_uri] = jwt.PyJWKClient(jwks_uri, cache_keys=True, lifespan=3600)
    try:
        return client.get_signing_key_from_jwt(token).key
    except jwt.PyJWTError as exc:
        raise EntraError("sso_invalid_token") from exc


def validate_id_token(cfg: dict, id_token: str, nonce: str) -> dict:
    doc = discovery(cfg["tenant_id"].strip())
    key = _signing_key(doc["jwks_uri"], id_token)
    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=cfg["client_id"].strip(),
            issuer=doc["issuer"],
            options={"require": ["exp", "iat", "aud", "iss", "sub"]},
            leeway=60,
        )
    except jwt.PyJWTError as exc:
        raise EntraError("sso_invalid_token") from exc
    if not secrets.compare_digest(str(claims.get("nonce") or ""), nonce):
        raise EntraError("sso_invalid_token")
    tenant = cfg["tenant_id"].strip()
    if _GUID.match(tenant) and str(claims.get("tid", "")).lower() != tenant.lower():
        raise EntraError("sso_wrong_tenant")
    return claims


def group_ids(claims: dict, access_token: str | None) -> list[str]:
    groups = [str(g) for g in claims.get("groups") or []]
    overage = "groups" in (claims.get("_claim_names") or {}) or claims.get("hasgroups")
    if overage and access_token:
        try:
            resp = httpx.post(
                f"{GRAPH}/me/getMemberGroups",
                json={"securityEnabledOnly": False},
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15,
            )
            if resp.status_code == 200:
                groups = [str(g) for g in resp.json().get("value", [])]
        except (httpx.HTTPError, ValueError):
            pass
    return groups


def resolve_role(cfg: dict, groups: list[str], app_roles: list[str]) -> str:
    """Highest role wins (Admin > Editor-in-chief > Editor > Staff); otherwise the default role.

    A role is matched by its fixed app role value (APP_ROLES) or by a group ID or value mapped to it.
    """
    have = {g.lower() for g in groups} | {r.lower() for r in app_roles}
    mapping: dict[str, Any] = cfg.get("group_roles") or {}
    for role in ROLES:
        wanted = [w.strip().lower() for w in re.split(r"[,\s;]+", str(mapping.get(role) or "")) if w.strip()]
        wanted.append(APP_ROLES[role][0].lower())
        if any(w in have for w in wanted):
            return role
    default = cfg.get("default_role") or "staff"
    return default if default in ROLES else "staff"


def identity(claims: dict) -> dict:
    email = claims.get("email") or claims.get("preferred_username") or claims.get("upn") or ""
    return {
        "external_id": f"{claims.get('tid')}:{claims.get('oid') or claims.get('sub')}",
        "email": str(email).lower(),
        "name": claims.get("name") or str(email).split("@")[0],
    }
