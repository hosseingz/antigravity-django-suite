"""
Custom Cookie & Header JWT Authentication Backend for Django REST Framework.

Supports dual-token authentication flow:
1. Inspects 'Authorization: Bearer <token>' header first (for mobile/API clients).
2. Falls back to the 'pod_access_token' HttpOnly cookie (for web browser clients).
3. Enforces explicit 401 exceptions on expired tokens and refresh-available states
   to prevent silent degradation and trigger the client-side single-refresh mutex.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Tuple

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request

logger = logging.getLogger(__name__)
User = get_user_model()


class CookieJWTAuthentication(BaseAuthentication):
    """
    Production-grade JWT authentication backend inspecting both headers and HttpOnly cookies.

    Authentication Strategy:
    1. Authorization Header: `Bearer <jwt_token>`
    2. HttpOnly Cookie: `pod_access_token`

    AI Guardrail & Anti-Silent-Degradation Rules:
    - If an access token is expired, MUST raise `exceptions.AuthenticationFailed` with code `token_expired`.
    - If `pod_access_token` is missing or expired, but `pod_refresh_token` is present in cookies,
      MUST raise `exceptions.AuthenticationFailed` with code `token_refresh_required` (HTTP 401).
      This signals the client-side Axios interceptor to execute a background token refresh.
    - If neither token is provided at all, returns `None` so unauthenticated/public endpoints
      remain accessible while protected endpoints fail gracefully at the permission level.
    """

    ACCESS_COOKIE_NAME: str = "pod_access_token"
    REFRESH_COOKIE_NAME: str = "pod_refresh_token"
    ALGORITHM: str = "HS256"

    def authenticate(self, request: Request) -> Optional[Tuple[AbstractBaseUser, dict[str, Any]]]:
        """
        Authenticates the incoming request, returning (user, token_payload) or None.
        """
        raw_token: Optional[str] = self._extract_token(request)
        has_refresh_cookie: bool = self.REFRESH_COOKIE_NAME in request.COOKIES

        if raw_token is None:
            # If access cookie is missing but refresh cookie exists, trigger silent refresh
            if has_refresh_cookie:
                logger.debug("Access cookie missing while refresh cookie is present. Triggering refresh.")
                raise exceptions.AuthenticationFailed(
                    detail={"detail": "Access token missing; refresh required.", "code": "token_refresh_required"},
                    code="token_refresh_required",
                )
            # Anonymous / unauthenticated request
            return None

        return self._authenticate_credentials(raw_token, has_refresh_cookie)

    def _extract_token(self, request: Request) -> Optional[str]:
        """
        Extracts the JWT from either the Authorization header or HttpOnly cookie.
        Header takes precedence for API clients / mobile apps.
        """
        # 1. Header lookup: Authorization: Bearer <token>
        auth_header = request.headers.get("Authorization") or request.META.get("HTTP_AUTHORIZATION")
        if auth_header:
            parts = auth_header.split()
            if len(parts) == 2 and parts[0].lower() == "bearer":
                return parts[1]

        # 2. HttpOnly Cookie fallback: pod_access_token
        return request.COOKIES.get(self.ACCESS_COOKIE_NAME)

    def _authenticate_credentials(
        self, raw_token: str, has_refresh_cookie: bool
    ) -> Tuple[AbstractBaseUser, dict[str, Any]]:
        """
        Decodes and verifies the JWT payload against Django settings.SECRET_KEY.
        """
        secret_key: str = getattr(settings, "SECRET_KEY", "")
        if not secret_key:
            logger.critical("SECRET_KEY is empty or unconfigured during JWT validation.")
            raise exceptions.AuthenticationFailed(
                detail={"detail": "Server security configuration error.", "code": "server_misconfigured"},
                code="server_misconfigured",
            )

        try:
            payload: dict[str, Any] = jwt.decode(
                raw_token,
                secret_key,
                algorithms=[self.ALGORITHM],
                options={"verify_exp": True, "verify_signature": True},
            )
        except jwt.ExpiredSignatureError:
            logger.info("Access token signature has expired.")
            code = "token_refresh_required" if has_refresh_cookie else "token_expired"
            raise exceptions.AuthenticationFailed(
                detail={"detail": "Access token has expired.", "code": code},
                code=code,
            )
        except jwt.InvalidTokenError as exc:
            logger.warning("Invalid JWT encountered: %s", str(exc))
            raise exceptions.AuthenticationFailed(
                detail={"detail": "Invalid or malformed authentication token.", "code": "token_invalid"},
                code="token_invalid",
            )

        # Enforce token type validation (reject refresh tokens presented as access tokens)
        token_type = payload.get("type", "access")
        if token_type != "access":
            logger.warning("Disallowed token type '%s' passed for access authentication.", token_type)
            raise exceptions.AuthenticationFailed(
                detail={"detail": "Invalid token type.", "code": "invalid_token_type"},
                code="invalid_token_type",
            )

        user_id = payload.get("user_id") or payload.get("sub")
        if not user_id:
            logger.warning("JWT payload lacks user identification claim ('user_id' or 'sub').")
            raise exceptions.AuthenticationFailed(
                detail={"detail": "Malformed token payload.", "code": "token_malformed"},
                code="token_malformed",
            )

        user = User.objects.filter(pk=user_id).first()
        if user is None:
            logger.warning("Token user ID %s not found in database.", user_id)
            raise exceptions.AuthenticationFailed(
                detail={"detail": "User not found.", "code": "user_not_found"},
                code="user_not_found",
            )

        if not user.is_active:
            logger.warning("Inactive user account ID %s attempted token authentication.", user_id)
            raise exceptions.AuthenticationFailed(
                detail={"detail": "User account is disabled or deactivated.", "code": "user_inactive"},
                code="user_inactive",
            )

        return (user, payload)

    def authenticate_header(self, request: Request) -> str:
        """
        Returns the WWW-Authenticate header challenge value for 401 Unauthorized responses.
        """
        return 'Bearer realm="api"'
