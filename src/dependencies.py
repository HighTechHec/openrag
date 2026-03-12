"""
FastAPI dependency injection module.

All service dependencies and authentication dependencies live here.
Import and use these in route handlers via FastAPI's Depends() mechanism.

Usage:
    from dependencies import get_current_user, get_session_manager
    from fastapi import Depends

    async def my_endpoint(
        user = Depends(get_current_user),
        session_manager = Depends(get_session_manager),
    ):
        ...
"""
import dataclasses
from typing import Optional

from fastapi import Depends, HTTPException, Request

from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)


# ─────────────────────────────────────────────
# Service dependencies
# ─────────────────────────────────────────────

def get_services(request: Request) -> dict:
    return request.app.state.services


def get_session_manager(services: dict = Depends(get_services)):
    return services["session_manager"]


def get_auth_service(services: dict = Depends(get_services)):
    return services["auth_service"]


def get_chat_service(services: dict = Depends(get_services)):
    return services["chat_service"]


def get_search_service(services: dict = Depends(get_services)):
    return services["search_service"]


def get_document_service(services: dict = Depends(get_services)):
    return services["document_service"]


def get_task_service(services: dict = Depends(get_services)):
    return services["task_service"]


def get_knowledge_filter_service(services: dict = Depends(get_services)):
    return services["knowledge_filter_service"]


def get_monitor_service(services: dict = Depends(get_services)):
    return services["monitor_service"]


def get_connector_service(services: dict = Depends(get_services)):
    return services["connector_service"]


def get_langflow_file_service(services: dict = Depends(get_services)):
    return services["langflow_file_service"]


def get_models_service(services: dict = Depends(get_services)):
    return services["models_service"]


def get_api_key_service(services: dict = Depends(get_services)):
    return services["api_key_service"]


def get_flows_service(services: dict = Depends(get_services)):
    return services["flows_service"]


# ─────────────────────────────────────────────
# IBM AMS authentication helper
# ─────────────────────────────────────────────

def _get_ibm_user(request: Request, required: bool) -> Optional["User"]:
    """Authenticate via IBM AMS — cookie-first, Basic Auth fallback.

    1. ibm-lh-console-session cookie: JWT validated with IBM's public key.
    2. Authorization: Basic header: decoded for user identity; Traefik has
       already validated the credentials, so we trust the header as-is and
       store the full header value to forward to OpenSearch.

    If *required* is True, raises HTTP 401 when neither is present/valid.
    If *required* is False, returns None instead of raising.
    """
    import base64
    import auth.ibm_auth as ibm_auth
    from config.settings import IBM_JWT_PUBLIC_KEY_URL

    # ── Option 1: cookie-based JWT ──────────────────────────────────────
    # Cookie name may include an instance UUID suffix, e.g.
    # ibm-lh-console-session-cd4fcbaf-6a3a-4a05-80af-92df02f64c54
    logger.info("IBM auth: cookies received by backend", cookie_keys=list(request.cookies.keys()))
    ibm_token = next(
        (v for k, v in request.cookies.items() if k.startswith("ibm-lh-console-session")),
        None,
    )
    logger.info("IBM auth: ibm_token found", found=ibm_token is not None)
    if ibm_token:
        claims = ibm_auth.validate_ibm_jwt(ibm_token, ibm_auth._cached_public_key)
        logger.info("IBM auth: JWT validation result", claims_found=claims is not None, public_key_loaded=ibm_auth._cached_public_key is not None)

        # On validation failure, try re-fetching the public key once (key rotation)
        if claims is None and IBM_JWT_PUBLIC_KEY_URL:
            try:
                import httpx
                from cryptography.hazmat.primitives.serialization import load_pem_public_key
                with httpx.Client(timeout=10.0) as client:
                    resp = client.get(IBM_JWT_PUBLIC_KEY_URL)
                    resp.raise_for_status()
                    pem = resp.json().get("public_key", "")
                    if isinstance(pem, str):
                        pem = pem.encode("utf-8")
                    ibm_auth._cached_public_key = load_pem_public_key(pem)
                logger.info("IBM public key refreshed (key rotation detected)")
                claims = ibm_auth.validate_ibm_jwt(ibm_token, ibm_auth._cached_public_key)
            except Exception as exc:
                logger.warning("Failed to refresh IBM public key", error=str(exc))

        if claims is not None:
            user = User(
                user_id=claims.get("uid") or claims["sub"],
                email=claims.get("username", claims["sub"]),
                name=claims.get("display_name", claims.get("username", claims["sub"])),
                picture=None,
                provider="ibm_ams",
                jwt_token=ibm_token,  # raw IBM JWT forwarded to OpenSearch as Bearer
            )
            request.state.user = user
            return user

    # ── Option 2: Basic Auth header or ibm-auth-basic cookie ────────────
    # The cookie is set by our ibm_login endpoint when Traefik is not present (local dev).
    auth_header = request.headers.get("Authorization", "") or request.cookies.get("ibm-auth-basic", "")
    if auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            username = decoded.split(":", 1)[0]
        except Exception:
            username = "unknown"

        user = User(
            user_id=username,
            email=username,
            name=username,
            picture=None,
            provider="ibm_ams_basic",
            jwt_token=auth_header,  # full "Basic <value>" forwarded to OpenSearch
        )
        request.state.user = user
        return user

    # ── Neither present ──────────────────────────────────────────────────
    if required:
        raise HTTPException(status_code=401, detail="IBM authentication required")
    request.state.user = None
    return None


# ─────────────────────────────────────────────
# Authentication dependencies
# ─────────────────────────────────────────────

def get_current_user(
    request: Request,
    session_manager=Depends(get_session_manager),
) -> User:
    """
    Require JWT cookie authentication.

    Sets request.state.user.
    Raises HTTP 401 if the user is not authenticated.
    """
    from config.settings import IBM_AUTH_ENABLED, is_no_auth_mode
    from session_manager import AnonymousUser

    # IBM AMS cookie auth takes priority when enabled
    if IBM_AUTH_ENABLED:
        return _get_ibm_user(request, required=True)

    if is_no_auth_mode():
        user = AnonymousUser()
        request.state.user = user
        effective_token = session_manager.get_effective_jwt_token(None, None)
        user_with_token = dataclasses.replace(user, jwt_token=effective_token)
        return user_with_token

    auth_token = request.cookies.get("auth_token")
    if not auth_token:
        raise HTTPException(status_code=401, detail="Authentication required")

    user = session_manager.get_user_from_token(auth_token)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    # get_effective_jwt_token handles anonymous JWT creation if needed
    effective_token = session_manager.get_effective_jwt_token(user.user_id, auth_token)
    user_with_token = dataclasses.replace(user, jwt_token=effective_token)

    request.state.user = user_with_token
    return user_with_token


def get_optional_user(
    request: Request,
    session_manager=Depends(get_session_manager),
) -> Optional[User]:
    """
    Optionally extract JWT cookie user.

    Sets request.state.user (may be None).
    Never raises — returns None if unauthenticated.
    """
    from config.settings import IBM_AUTH_ENABLED, is_no_auth_mode
    from session_manager import AnonymousUser

    # IBM AMS cookie auth takes priority when enabled
    if IBM_AUTH_ENABLED:
        return _get_ibm_user(request, required=False)

    if is_no_auth_mode():
        user = AnonymousUser()
        request.state.user = user
        effective_token = session_manager.get_effective_jwt_token(None, None)
        user_with_token = dataclasses.replace(user, jwt_token=effective_token)
        return user_with_token

    auth_token = request.cookies.get("auth_token")
    if not auth_token:
        request.state.user = None
        return None

    user = session_manager.get_user_from_token(auth_token)
    # get_effective_jwt_token handles anonymous JWT creation if needed
    effective_token = session_manager.get_effective_jwt_token(user.user_id, auth_token) if user else None
    user_with_token = dataclasses.replace(user, jwt_token=effective_token) if user else None

    request.state.user = user_with_token
    return user_with_token


async def get_api_key_user_async(
    request: Request,
    api_key_service=Depends(get_api_key_service),
) -> User:
    """
    Async dependency: require API key authentication.

    Accepts:
      - X-API-Key: orag_... header
      - Authorization: Bearer orag_... header

    Raises HTTP 401 if no valid key is provided.
    """
    # Extract key from headers
    api_key = request.headers.get("X-API-Key")
    if not api_key or not api_key.startswith("orag_"):
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if token.startswith("orag_"):
                api_key = token

    if not api_key:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "API key required",
                "message": "Provide API key via X-API-Key header or Authorization: Bearer header",
            },
        )

    user_info = await api_key_service.validate_key(api_key)
    if not user_info:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "Invalid API key",
                "message": "The provided API key is invalid or has been revoked",
            },
        )

    user = User(
        user_id=user_info["user_id"],
        email=user_info["user_email"],
        name=user_info.get("name", "API User"),
        picture=None,
        provider="api_key",
    )

    # API Key users don't typically have a JWT for OpenSearch OIDC, 
    # but we can try to get an effective one if needed
    user_with_token = dataclasses.replace(user, jwt_token=None)

    request.state.user = user_with_token
    request.state.api_key_id = user_info["key_id"]

    return user_with_token
