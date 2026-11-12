---
name: auth-jwt-cookie-session
description: Authoritative blueprint for dual-token HttpOnly cookie authentication, custom DRF CookieJWTAuthentication, Redis-backed stateful Refresh Token Rotation (RTR), Next.js routing middleware, and Zustand identity store.
---

# Auth JWT & Cookie Session Management

This skill establishes the production-grade authentication pipeline combining Django REST Framework (DRF) and Next.js (App Router). It implements a secure dual-token HttpOnly cookie strategy (`pod_access_token` and `pod_refresh_token`) scoped to `Path=/`, custom `CookieJWTAuthentication` with CSRF defense, Redis-backed stateful Refresh Token Rotation (RTR) with reuse detection, dedicated cryptographic signing keys, non-premature Next.js route protection middleware, and Zustand auth state management.

---

## 1. Visual ASCII Architectural Diagram

```
[ Browser Client Context ]                 [ Next.js App Router ]                 [ Django Backend (DRF) ]
            │                                         │                                      │
            │ 1. Navigate to /dashboard               │                                      │
            ├────────────────────────────────────────►│                                      │
            │                                         │ 2. middleware.ts                     │
            │                                         │    Inspect cookies (Path=/):         │
            │                                         │    • pod_access_token                │
            │                                         │    • pod_refresh_token               │
            │                                         │    [Allows entry if either exists]   │
            │ 3. Stream Protected HTML Page           │                                      │
            │◄────────────────────────────────────────┤                                      │
            │                                                                                │
            │ 4. CSR API Request (apiClient.get('/api/v2/user/orders/'))                    │
            │    [Browser auto-attaches HttpOnly Cookie: pod_access_token]                   │
            ├───────────────────────────────────────────────────────────────────────────────►│
            │                                                                                │ 5. CookieJWTAuthentication:
            │                                                                                │    Validates dedicated JWT_SIGNING_KEY
            │                                                                                │    Verifies jti against Redis blacklist
            │                                                                                │    [Expired Signature]
            │ 6. HTTP 401 Unauthorized (code: token_refresh_required)                        │
            │◄───────────────────────────────────────────────────────────────────────────────┤
            │                                                                                │
            │ 7. apiClient Mutex Lock intercepts 401:                                        │
            │    POST /api/v2/auth/token/refresh/                                            │
            │    [Browser auto-attaches HttpOnly Cookie: pod_refresh_token]                  │
            ├───────────────────────────────────────────────────────────────────────────────►│
            │                                                                                │ 8. RefreshTokenView (RTR):
            │                                                                                │    Verifies jti (rejects reuse)
            │                                                                                │    Blacklists old jti in Redis
            │                                                                                │    Issues fresh token pair (new jtis)
            │ 9. HTTP 200 OK + Set-Cookie (Path=/): pod_access_token & pod_refresh_token     │
            │◄───────────────────────────────────────────────────────────────────────────────┤
            │                                                                                │
            │ 10. Replay queued original request with updated cookie credentials             │
            ├───────────────────────────────────────────────────────────────────────────────►│
            │ 11. HTTP 200 OK (Orders Data Payload)                                          │
            │◄───────────────────────────────────────────────────────────────────────────────┤
```

---

## 2. AI Guardrails & Architectural Anti-Patterns

- **Anti-Pattern 1: Storing JWTs in `localStorage` or `sessionStorage`**
  - *Rule*: Raw access and refresh tokens MUST NEVER touch browser web storage or JavaScript-accessible memory objects.
  - *Risk*: Complete vulnerability to Cross-Site Scripting (XSS) credential theft. Any third-party script or injected snippet can extract `localStorage.getItem('token')`.
  - *Solution*: Enforce server-managed `HttpOnly` cookies (`pod_access_token` and `pod_refresh_token`). Client-side state stores (such as Zustand) only persist non-sensitive user profile metadata (e.g., `{ id, email, fullName }`).

- **Anti-Pattern 2: Silent Degradation in `CookieJWTAuthentication`**
  - *Rule*: When an access token is expired, or when `pod_access_token` is missing while `pod_refresh_token` exists, `CookieJWTAuthentication` MUST raise an explicit `exceptions.AuthenticationFailed` (HTTP 401) with code `token_refresh_required`.
  - *Risk*: Silently falling back to `AnonymousUser` causes protected endpoints to return generic permission denied errors (403), breaking the client's ability to trigger background token refresh.
  - *Solution*: Explicit 401 exceptions coordinate directly with the Axios single-refresh mutex lock in [`apiClient.ts`](../nextjs-api-sync/resources/apiClient.ts).

- **Anti-Pattern 3: Premature Route Eviction in Next.js Middleware**
  - *Rule*: Middleware protecting routes (`/dashboard`, `/checkout`) MUST check for EITHER `pod_access_token` OR `pod_refresh_token`.
  - *Risk*: Access tokens are short-lived (e.g., 15 minutes). If middleware redirects to `/auth/login` the moment the access cookie expires, users are aggressively evicted from sessions even though they possess a valid 7-day refresh token.
  - *Solution*: Allow requests through when `pod_refresh_token` is present. Client hydration and Axios interceptors execute the silent background refresh seamlessly.

- **Anti-Pattern 4: Subpath Cookie Scoping (`Path=/api/auth/`)**
  - *Rule*: All authentication cookies (`pod_access_token` and `pod_refresh_token`) MUST be explicitly configured with `Path=/`.
  - *Risk*: Scoping the refresh cookie to an auth endpoint subpath prevents the browser from sending `pod_refresh_token` to frontend page routes (like `/dashboard`), breaking Next.js edge route guards and causing immediate premature eviction.
  - *Solution*: Always set `path="/"` across all environments in both `set_auth_cookies` and `clear_auth_cookies`.

- **Anti-Pattern 5: Purely Stateless Refresh Tokens & Missing `jti`**
  - *Rule*: Refresh tokens must never be purely stateless. Every JWT must include a unique `jti` claim, and refresh tokens must be tracked in a persistent cache (Redis) with Refresh Token Rotation (RTR).
  - *Risk*: Stateless refresh tokens cannot be invalidated upon user logout or session termination. Intercepted tokens can be replayed indefinitely until expiration.
  - *Solution*: Upon refresh, blacklist the presented `jti` in Redis for its remaining TTL and issue a new pair. If an already-rotated token is reused, trigger immediate automatic revocation of the entire session family.

- **Anti-Pattern 6: Signing JWTs with Framework `SECRET_KEY`**
  - *Rule*: Signing tokens using Django's core `settings.SECRET_KEY` is strictly prohibited.
  - *Risk*: Leaking or rotating the JWT signing key compromises the core cryptographic foundation of Django (sessions, CSRF, password resets). Sharing `SECRET_KEY` with edge services or microservices exposes the entire backend.
  - *Solution*: Mandate a dedicated `JWT_SIGNING_KEY` (or asymmetric keypair `RS256`/`EdDSA`). Fail startup closed if missing.

- **Anti-Pattern 7: Omitting CSRF Countermeasures on Cookie Authentication**
  - *Rule*: Mutating HTTP requests (POST, PUT, PATCH, DELETE) authenticated via cookies must undergo CSRF verification.
  - *Risk*: Cookie-based authentication is inherently subject to Cross-Site Request Forgery if browsers send credentials automatically.
  - *Solution*: In `CookieJWTAuthentication`, enforce CSRF verification (via DRF `CSRFCheck`) whenever credentials originate from cookies.

- **Anti-Pattern 8: Treating `authentication_classes = []` as a CSRF Exemption**
  - *Rule*: Every cookie-consuming or cookie-minting endpoint (`login`, `register`, `token/refresh`, `logout`) MUST explicitly verify CSRF via `CSRFCheck` (e.g. `CookieCSRFProtectedMixin`).
  - *Risk*: DRF's `APIView.as_view()` is marked `csrf_exempt`. If an auth view sets `authentication_classes = []` or `permission_classes = [AllowAny]`, DRF completely skips Django's CSRF middleware and never re-introduces `CSRFCheck`. This leaves endpoints open to Login-CSRF, Logout-CSRF (forced DoS), and cross-origin refresh rotation.
  - *Solution*: Apply `CookieCSRFProtectedMixin` which invokes `CSRFCheck` in `initial()`, pair it with a bootstrap `GET /api/v1/auth/csrf/` endpoint, and enforce `X-CSRFToken` injection in `apiClient` for all mutating calls including refresh.

- **Anti-Pattern 9: Basing Cookie Security Flags on `secure = not DEBUG`**
  - *Rule*: Secure flags derive strictly from an explicit transport/environment setting (`COOKIE_SECURE`), never from `DEBUG`.
  - *Risk*: In Docker or staging environments running with `DEBUG=0` over plain HTTP (`http://localhost:8080`), setting `secure=True` causes modern browsers to silently discard all auth cookies. The login returns 200, but no session is established, and the subsequent request immediately throws `CSRF Failed: CSRF cookie not set`.
  - *Solution*: Use `COOKIE_SECURE = env.bool("COOKIE_SECURE", default=ENVIRONMENT not in ["development", "local"])` as the single source of truth across all cookie operations.

- **Anti-Pattern 10: Unthrottled Credential Endpoints**
  - *Rule*: Authentication endpoints (`login/`, `register/`, `token/refresh/`, `otp/*`) must declare explicit DRF throttle scopes.
  - *Risk*: Line-rate credential brute force and denial of service attacks against cryptographic token hashing functions.
  - *Solution*: Enforce `ScopedRateThrottle` with scoped limits (e.g., `10/min` for login, `30/min` for refresh) backed by Redis.

---

## 3. Suite Integration & Component Architecture

### 3.1 Backend Components (`resources/backend/`)
- [`authentication.py`](./resources/backend/authentication.py):
  - Extends DRF `BaseAuthentication`.
  - Prioritizes `Authorization: Bearer <token>` header (for external/mobile clients), falling back to `pod_access_token` HttpOnly cookie.
  - Decodes and validates tokens against dedicated `settings.JWT_SIGNING_KEY` (never `SECRET_KEY`).
  - Verifies token `jti` against the Redis blacklist (`jwt:blacklist:<jti>`).
  - Enforces DRF `CSRFCheck` on cookie-authenticated mutating requests.
  - Implements scoped anti-silent-degradation logic: public safe requests (`GET`, `HEAD`) proceed anonymously; protected or mutating requests return `token_refresh_required` (HTTP 401).
- [`views_auth.py`](./resources/backend/views_auth.py):
  - `CookieCSRFProtectedMixin`: Injects explicit `CSRFCheck` verification for cookie-consuming endpoints.
  - `CsrfTokenAPIView`: Provides `GET /api/v1/auth/csrf/` (`@ensure_csrf_cookie`) to bootstrap the CSRF cookie on initial SPA hydration.
  - `set_auth_cookies()` & `clear_auth_cookies()`: Encapsulates cookie generation with `HttpOnly`, `SameSite=Lax`, `Path=/`, and centralized `settings.COOKIE_SECURE` flag.
  - `LoginAPIView`: Authenticates credentials with throttling (`throttle_scope = "auth"`) and sets dual cookies.
  - `RefreshTokenView`: Verifies `pod_refresh_token` with CSRF protection, enforces Refresh Token Rotation (RTR), and detects token reuse.
  - `LogoutAPIView`: Blacklists active `jti` in Redis cache for its remaining TTL, clears cookies, and validates CSRF.
  - `SendOtpView` & `VerifyOtpView`: Redis-backed passwordless SMS verification with 120s cooldowns and 5-attempt brute-force lockouts.

### 3.2 Frontend Components (`resources/frontend/`)
- [`middleware.ts`](./resources/frontend/middleware.ts):
  - Next.js edge route guard checking protected routes (`/dashboard`, `/checkout`, `/profile`).
  - Route matchers MUST correspond to routes that actually exist in the application.
  - Guards against premature eviction by recognizing valid refresh cookies on `Path=/`.
  - Automatically redirects authenticated users away from guest pages (`/auth/login`, `/auth/register`).
- [`useAuthStore.ts`](./resources/frontend/useAuthStore.ts):
  - Zustand auth store tracking `user`, `isAuthenticated`, and `isLoading`.
  - Safely hydrates from non-sensitive profile metadata in `localStorage`.
  - Routes refresh requests through `apiClient.ts` to ensure `X-CSRFToken` is attached.
  - Listens for `auth:session-expired` events.

### 3.3 Deep-Dive Technical References
- [`references/cookie-lifecycle.md`](./references/cookie-lifecycle.md): Detailed analysis of HttpOnly, Secure, and SameSite flags, `Path=/` alignment, Redis RTR, deterministic logout eviction, and CSRF defense.
- [`references/sms-otp-workflow.md`](./references/sms-otp-workflow.md): Redis key lifecycle (`otp:code`, `otp:cooldown`, `otp:attempts`, `otp:locked`), timing attack mitigations, and `retry_after` frontend synchronization.

---

## 4. Scaffolding & Setup Procedure

### Step 1: Configure Backend Authentication & Signing Keys
In `backend/config/settings.py` (referencing [`django-core-architecture`](../django-core-architecture/resources/settings.py)):
```python
# Dedicated JWT Signing Key (Never reuse SECRET_KEY)
JWT_SIGNING_KEY = env("JWT_SIGNING_KEY")
if not JWT_SIGNING_KEY and not DEBUG:
    raise ValueError("FATAL: JWT_SIGNING_KEY environment variable must be set in non-debug environments.")
elif not JWT_SIGNING_KEY:
    JWT_SIGNING_KEY = "django-insecure-dev-jwt-key-never-use-in-production"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "users.authentication.CookieJWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

# Cookie Configuration (Mandatory Path=/)
AUTH_ACCESS_TOKEN_LIFETIME_SECONDS = 900       # 15 minutes
AUTH_REFRESH_TOKEN_LIFETIME_SECONDS = 604800   # 7 days
AUTH_COOKIE_PATH = "/"
```
```

### Step 2: Register URLs in Django
In `backend/config/urls.py`:
```python
from django.urls import path
from apps.authentication.views import (
    CsrfTokenAPIView,
    LoginAPIView,
    RefreshTokenView,
    LogoutAPIView,
    SendOtpView,
    VerifyOtpView,
)

urlpatterns = [
    path("api/v2/auth/csrf/", CsrfTokenAPIView.as_view(), name="auth-csrf"),
    path("api/v2/auth/login/", LoginAPIView.as_view(), name="auth-login"),
    path("api/v2/auth/token/refresh/", RefreshTokenView.as_view(), name="auth-refresh"),
    path("api/v2/auth/logout/", LogoutAPIView.as_view(), name="auth-logout"),
    path("api/v2/auth/otp/send/", SendOtpView.as_view(), name="auth-otp-send"),
    path("api/v2/auth/otp/verify/", VerifyOtpView.as_view(), name="auth-otp-verify"),
]
```

### Step 3: Deploy Frontend Middleware, API Client & Store
1. Copy [`resources/frontend/middleware.ts`](./resources/frontend/middleware.ts) into the root of your Next.js application (`frontend/middleware.ts`). Ensure route matchers correspond to routes that actually exist in the application.
2. Deploy [`apiClient.ts`](../nextjs-api-sync/resources/apiClient.ts) into `frontend/lib/api/apiClient.ts` to ensure automatic `csrftoken` reading and `X-CSRFToken` header injection on mutating requests (and within the refresh mutex lock).
3. Copy [`resources/frontend/useAuthStore.ts`](./resources/frontend/useAuthStore.ts) into `frontend/stores/useAuthStore.ts`.
4. In your root React layout or auth provider, bootstrap CSRF and invoke `hydrateAuth()`:
```typescript
'use client';
import { useEffect } from 'react';
import { useAuthStore } from '@/stores/useAuthStore';
import { apiClient } from '@/lib/api/apiClient';

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const hydrateAuth = useAuthStore((state) => state.hydrateAuth);

  useEffect(() => {
    // Bootstrap CSRF cookie on initial mount
    apiClient.get('/api/v2/auth/csrf/').catch(() => {});
    hydrateAuth();
  }, [hydrateAuth]);

  return <>{children}</>;
}
```
