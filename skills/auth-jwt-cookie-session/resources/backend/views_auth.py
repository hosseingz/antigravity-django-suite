"""
Authentication Views & Secure Cookie Management for Django REST Framework.

Implements:
1. Two-token HttpOnly cookie strategy ('pod_access_token' & 'pod_refresh_token').
2. Zero token exposure to client JavaScript (no tokens in JSON response bodies).
3. Session eviction helper via Max-Age=0 cookie headers.
4. Redis-backed SMS OTP verification workflow with cooldown and lockout rate-limiting.
"""

from __future__ import annotations

import datetime
import hmac
import logging
import secrets
import string
from typing import Any, Optional

import jwt
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import AbstractBaseUser
from django.core.cache import cache
from rest_framework import exceptions, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)
User = get_user_model()

# Configuration Defaults
ACCESS_COOKIE_NAME = "pod_access_token"
REFRESH_COOKIE_NAME = "pod_refresh_token"
ACCESS_TOKEN_LIFETIME = getattr(settings, "AUTH_ACCESS_TOKEN_LIFETIME_SECONDS", 900)  # 15 minutes
REFRESH_TOKEN_LIFETIME = getattr(settings, "AUTH_REFRESH_TOKEN_LIFETIME_SECONDS", 604800)  # 7 days
JWT_ALGORITHM = getattr(settings, "JWT_ALGORITHM", "HS256")


def get_jwt_signing_key() -> str:
    """
    Retrieves the dedicated JWT signing key. Reusing SECRET_KEY is strictly prohibited.
    """
    key = getattr(settings, "JWT_SIGNING_KEY", "")
    if not key:
        logger.critical("FATAL: JWT_SIGNING_KEY is unconfigured. Never use Django core SECRET_KEY.")
        raise exceptions.AuthenticationFailed(
            detail={"detail": "Server security configuration error.", "code": "server_misconfigured"},
            code="server_misconfigured",
        )
    return key


# ---------------------------------------------------------------------------
# Cryptographic Token Generators
# ---------------------------------------------------------------------------

def create_jwt_token(user: AbstractBaseUser, token_type: str, lifetime_seconds: int) -> str:
    """
    Creates a signed JWT with unique jti, claims for user identification, and dedicated signing key.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    signing_key = get_jwt_signing_key()
    payload = {
        "user_id": user.pk,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + datetime.timedelta(seconds=lifetime_seconds)).timestamp()),
        "jti": secrets.token_hex(16),
    }
    return jwt.encode(payload, signing_key, algorithm=JWT_ALGORITHM)


def issue_token_pair(user: AbstractBaseUser) -> tuple[str, str]:
    """
    Generates an (access_token, refresh_token) pair for the authenticated user.
    """
    access_token = create_jwt_token(user, "access", ACCESS_TOKEN_LIFETIME)
    refresh_token = create_jwt_token(user, "refresh", REFRESH_TOKEN_LIFETIME)
    return access_token, refresh_token


# ---------------------------------------------------------------------------
# Cookie Utilities
# ---------------------------------------------------------------------------

def set_auth_cookies(
    response: Response,
    access_token: str,
    refresh_token: Optional[str] = None,
) -> Response:
    """
    Attaches secure HttpOnly cookies to the outgoing DRF Response.
    Mandatory Alignment: Both cookies MUST use path="/" for Next.js route guard compatibility.
    """
    secure_flag = not getattr(settings, "DEBUG", False)

    # 1. Access Token Cookie (Short-lived, Path=/)
    response.set_cookie(
        key=ACCESS_COOKIE_NAME,
        value=access_token,
        max_age=ACCESS_TOKEN_LIFETIME,
        httponly=True,
        secure=secure_flag,
        samesite="Lax",
        path="/",
    )

    # 2. Refresh Token Cookie (Long-lived, Path=/)
    if refresh_token is not None:
        response.set_cookie(
            key=REFRESH_COOKIE_NAME,
            value=refresh_token,
            max_age=REFRESH_TOKEN_LIFETIME,
            httponly=True,
            secure=secure_flag,
            samesite="Lax",
            path="/",
        )

    return response


def clear_auth_cookies(response: Response) -> Response:
    """
    Evicts authentication state deterministically on Path=/ using Max-Age=0 and past Expires.
    """
    secure_flag = not getattr(settings, "DEBUG", False)

    for cookie_name in (ACCESS_COOKIE_NAME, REFRESH_COOKIE_NAME):
        response.delete_cookie(
            key=cookie_name,
            path="/",
            samesite="Lax",
        )
        # Deterministic past-expiration header safeguard
        response.set_cookie(
            key=cookie_name,
            value="",
            max_age=0,
            expires="Thu, 01 Jan 1970 00:00:00 GMT",
            httponly=True,
            secure=secure_flag,
            samesite="Lax",
            path="/",
        )

    return response


def serialize_user_profile(user: AbstractBaseUser) -> dict[str, Any]:
    """
    Serializes safe, non-sensitive user metadata for client-side Zustand hydration.
    Tokens must NEVER be included in this payload.
    """
    return {
        "id": user.pk,
        "email": getattr(user, "email", ""),
        "username": getattr(user, "username", ""),
        "first_name": getattr(user, "first_name", ""),
        "last_name": getattr(user, "last_name", ""),
        "is_active": user.is_active,
    }


# ---------------------------------------------------------------------------
# Authentication Views
# ---------------------------------------------------------------------------

class LoginAPIView(APIView):
    """
    Authenticates username/email credentials and sets dual HttpOnly cookies.
    Response body contains user profile metadata only — tokens never touch JavaScript.
    """
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        username = request.data.get("username") or request.data.get("email")
        password = request.data.get("password")

        if not username or not password:
            return Response(
                {"detail": "Username/email and password are required.", "code": "missing_credentials"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(request, username=username, password=password)
        if user is None:
            return Response(
                {"detail": "Invalid credentials provided.", "code": "invalid_credentials"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not user.is_active:
            return Response(
                {"detail": "Account is disabled.", "code": "account_disabled"},
                status=status.HTTP_403_FORBIDDEN,
            )

        access_token, refresh_token = issue_token_pair(user)
        response = Response(
            {
                "detail": "Login successful.",
                "user": serialize_user_profile(user),
            },
            status=status.HTTP_200_OK,
        )

        return set_auth_cookies(response, access_token, refresh_token)


class RefreshTokenView(APIView):
    """
    Performs silent background token refresh with stateful Refresh Token Rotation (RTR).
    Reads `pod_refresh_token` from HttpOnly cookies, verifies signature against dedicated
    JWT_SIGNING_KEY, validates unique `jti`, detects token reuse, blacklists the old token
    in Redis, and issues a freshly rotated token pair on Path=/.
    """
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        refresh_raw = request.COOKIES.get(REFRESH_COOKIE_NAME)

        if not refresh_raw:
            response = Response(
                {"detail": "Refresh cookie missing.", "code": "refresh_cookie_missing"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            return clear_auth_cookies(response)

        signing_key = get_jwt_signing_key()

        try:
            payload = jwt.decode(
                refresh_raw,
                signing_key,
                algorithms=[JWT_ALGORITHM],
                options={"verify_exp": True, "verify_signature": True},
            )
        except jwt.ExpiredSignatureError:
            logger.info("Provided refresh token has expired.")
            response = Response(
                {"detail": "Session expired; please log in again.", "code": "session_expired"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            return clear_auth_cookies(response)
        except jwt.InvalidTokenError:
            logger.warning("Invalid refresh token signature presented.")
            response = Response(
                {"detail": "Invalid refresh token.", "code": "invalid_token"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            return clear_auth_cookies(response)

        if payload.get("type") != "refresh":
            response = Response(
                {"detail": "Provided token is not a refresh token.", "code": "invalid_token_type"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            return clear_auth_cookies(response)

        jti = payload.get("jti")
        if not jti:
            logger.warning("Refresh token lacks required 'jti' identifier.")
            response = Response(
                {"detail": "Malformed token payload.", "code": "token_malformed"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            return clear_auth_cookies(response)

        user_id = payload.get("user_id") or payload.get("sub")

        # Refresh Token Rotation (RTR): Check if this token was already rotated/revoked
        if cache.get(f"jwt:blacklist:{jti}"):
            logger.critical(
                "SECURITY ALERT: Refresh token reuse detected! jti=%s for user_id=%s. Revoking session family.",
                jti,
                user_id,
            )
            # Evict entire token lineage for this user
            cache.set(f"jwt:user_revoked:{user_id}", True, timeout=REFRESH_TOKEN_LIFETIME)
            response = Response(
                {"detail": "Token reuse detected. All active sessions invalidated.", "code": "token_reuse_detected"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            return clear_auth_cookies(response)

        if cache.get(f"jwt:user_revoked:{user_id}"):
            logger.warning("Revoked user session attempted token refresh: user_id=%s", user_id)
            response = Response(
                {"detail": "Session has been terminated. Please log in again.", "code": "session_terminated"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            return clear_auth_cookies(response)

        user = User.objects.filter(pk=user_id, is_active=True).first()
        if user is None:
            response = Response(
                {"detail": "User associated with token is invalid or inactive.", "code": "user_inactive"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            return clear_auth_cookies(response)

        # Blacklist the consumed refresh token jti for its remaining TTL in Redis
        now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
        exp_ts = payload.get("exp", now_ts + REFRESH_TOKEN_LIFETIME)
        remaining_ttl = max(int(exp_ts - now_ts), 60)
        cache.set(f"jwt:blacklist:{jti}", "rotated", timeout=remaining_ttl)

        # Issue fresh token pair (Rotation on refresh with new jtis)
        new_access_token, new_refresh_token = issue_token_pair(user)

        response = Response(
            {
                "detail": "Session refreshed successfully.",
                "user": serialize_user_profile(user),
            },
            status=status.HTTP_200_OK,
        )
        return set_auth_cookies(response, new_access_token, new_refresh_token)


class LogoutAPIView(APIView):
    """
    Clears HttpOnly authentication cookies deterministically and blacklists
    the presented refresh token in Redis for its remaining TTL.
    """
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        refresh_raw = request.COOKIES.get(REFRESH_COOKIE_NAME)
        if refresh_raw:
            signing_key = getattr(settings, "JWT_SIGNING_KEY", "")
            try:
                payload = jwt.decode(
                    refresh_raw,
                    signing_key,
                    algorithms=[JWT_ALGORITHM],
                    options={"verify_exp": False, "verify_signature": True},
                )
                jti = payload.get("jti")
                if jti:
                    now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
                    exp_ts = payload.get("exp", now_ts + REFRESH_TOKEN_LIFETIME)
                    remaining_ttl = max(int(exp_ts - now_ts), 60)
                    cache.set(f"jwt:blacklist:{jti}", "logout", timeout=remaining_ttl)
                    logger.info("Blacklisted refresh token jti=%s on logout.", jti)
            except Exception as exc:
                logger.debug("Could not decode refresh token during logout blacklisting: %s", exc)

        response = Response(
            {"detail": "Logged out successfully."},
            status=status.HTTP_200_OK,
        )
        return clear_auth_cookies(response)


# ---------------------------------------------------------------------------
# Redis-Backed SMS OTP Verification Views
# ---------------------------------------------------------------------------

OTP_TTL_SECONDS = 120  # 2 minutes valid window & resend cooldown
OTP_MAX_ATTEMPTS = 5
LOCKOUT_TTL_SECONDS = 900  # 15 minutes lockout after 5 failures


def get_otp_redis_keys(phone: str) -> tuple[str, str, str, str]:
    sanitized = "".join(filter(str.isdigit, phone))
    return (
        f"otp:code:{sanitized}",
        f"otp:cooldown:{sanitized}",
        f"otp:attempts:{sanitized}",
        f"otp:locked:{sanitized}",
    )


class SendOtpView(APIView):
    """
    Issues a cryptographically secure 6-digit SMS OTP with Redis rate-limiting:
    - Enforces 120-second cooldown per phone number.
    - Prevents dispatch if the phone is currently locked out from brute-force attempts.
    - Returns `retry_after` parameter to synchronize frontend countdown timers.
    """
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        phone = request.data.get("phone", "").strip()
        if not phone or len(phone) < 10:
            return Response(
                {"detail": "A valid phone number is required.", "code": "invalid_phone"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        code_key, cooldown_key, attempts_key, lockout_key = get_otp_redis_keys(phone)

        # 1. Check Lockout State
        if cache.get(lockout_key):
            return Response(
                {
                    "detail": "Account temporarily locked due to excessive failed attempts. Try again later.",
                    "code": "phone_locked",
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        # 2. Check Resend Cooldown
        if cache.get(cooldown_key):
            # Best effort to inspect remaining TTL
            return Response(
                {
                    "detail": "Please wait before requesting a new OTP.",
                    "code": "cooldown_active",
                    "retry_after": OTP_TTL_SECONDS,
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        # 3. Generate Cryptographic 6-Digit Code
        otp_code = "".join(secrets.choice(string.digits) for _ in range(6))

        # 4. Store in Redis
        cache.set(code_key, otp_code, timeout=OTP_TTL_SECONDS)
        cache.set(cooldown_key, "1", timeout=OTP_TTL_SECONDS)
        cache.set(attempts_key, 0, timeout=OTP_TTL_SECONDS)

        # 5. Dispatch via SMS Gateway (Simulated / Service Hook)
        logger.info("[SMS-OTP-GATEWAY] Dispatched OTP code to phone %s: %s", phone[-4:], otp_code)

        return Response(
            {
                "detail": "OTP sent successfully.",
                "retry_after": OTP_TTL_SECONDS,
            },
            status=status.HTTP_200_OK,
        )


class VerifyOtpView(APIView):
    """
    Verifies SMS OTP with brute-force protection:
    - Purges OTP and locks account for 15 minutes after 5 consecutive failures.
    - Uses constant-time string comparison (`hmac.compare_digest`) against timing attacks.
    - On success: provisions or fetches the user, sets HttpOnly cookies, and returns user data.
    """
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        phone = request.data.get("phone", "").strip()
        code = request.data.get("code", "").strip()

        if not phone or not code:
            return Response(
                {"detail": "Phone and OTP code are required.", "code": "missing_fields"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        code_key, cooldown_key, attempts_key, lockout_key = get_otp_redis_keys(phone)

        # 1. Check Lockout
        if cache.get(lockout_key):
            return Response(
                {
                    "detail": "Account temporarily locked. Please try again in 15 minutes.",
                    "code": "account_locked",
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        stored_code = cache.get(code_key)
        if not stored_code:
            return Response(
                {"detail": "OTP has expired or was never requested.", "code": "otp_expired"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 2. Track & Verify Attempts
        current_attempts = cache.get(attempts_key, 0)
        try:
            current_attempts = int(current_attempts)
        except (ValueError, TypeError):
            current_attempts = 0

        # Check Code via Constant-Time Comparison
        if not hmac.compare_digest(stored_code, code):
            current_attempts += 1
            if current_attempts >= OTP_MAX_ATTEMPTS:
                # Purge code and enforce 15-minute lock
                cache.delete(code_key)
                cache.delete(cooldown_key)
                cache.delete(attempts_key)
                cache.set(lockout_key, "1", timeout=LOCKOUT_TTL_SECONDS)
                logger.warning("Phone %s exceeded maximum OTP attempts. Lockout applied.", phone[-4:])
                return Response(
                    {
                        "detail": "Too many failed attempts. Phone locked for 15 minutes.",
                        "code": "max_attempts_exceeded",
                    },
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )

            cache.set(attempts_key, current_attempts, timeout=OTP_TTL_SECONDS)
            attempts_remaining = OTP_MAX_ATTEMPTS - current_attempts
            return Response(
                {
                    "detail": f"Invalid OTP code. {attempts_remaining} attempts remaining.",
                    "code": "invalid_otp",
                    "attempts_remaining": attempts_remaining,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 3. Successful Verification: Purge Redis State
        cache.delete(code_key)
        cache.delete(cooldown_key)
        cache.delete(attempts_key)

        # 4. Resolve or Provision User
        user, _ = User.objects.get_or_create(
            username=phone,
            defaults={"is_active": True},
        )

        access_token, refresh_token = issue_token_pair(user)
        response = Response(
            {
                "detail": "OTP verified successfully.",
                "user": serialize_user_profile(user),
            },
            status=status.HTTP_200_OK,
        )

        return set_auth_cookies(response, access_token, refresh_token)
