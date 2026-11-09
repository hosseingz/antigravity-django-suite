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

---

## 3. Suite Integration & Component Architecture

### 3.1 Backend Components (`resources/backend/`)
- [`authentication.py`](./resources/backend/authentication.py):
  - Extends DRF `BaseAuthentication`.
  - Prioritizes `Authorization: Bearer <token>` header (for external/mobile clients), falling back to `pod_access_token` HttpOnly cookie.
  - Decodes and validates tokens against dedicated `settings.JWT_SIGNING_KEY` (never `SECRET_KEY`).
  - Verifies token `jti` against the Redis blacklist (`jwt:blacklist:<jti>`).
  - Enforces DRF `CSRFCheck` on cookie-authenticated mutating requests.
  - Implements anti-silent-degradation logic for seamless token refresh.
- [`views_auth.py`](./resources/backend/views_auth.py):
  - `set_auth_cookies()` & `clear_auth_cookies()`: Encapsulates cookie generation with `HttpOnly`, `SameSite=Lax`, `Path=/`, and environment-aware `Secure` flags. Deterministic logout issues `Max-Age=0` and past expiration headers.
  - `LoginAPIView`: Authenticates credentials and writes dual cookies without leaking tokens into response JSON.
  - `RefreshTokenView`: Verifies `pod_refresh_token`, enforces Refresh Token Rotation (RTR) via Redis blacklist, and detects token reuse.
  - `LogoutAPIView`: Blacklists active `jti` in Redis cache for its remaining TTL and purges cookies deterministically.
  - `SendOtpView` & `VerifyOtpView`: Redis-backed passwordless SMS verification with 120s cooldowns and 5-attempt brute-force lockouts.

### 3.2 Frontend Components (`resources/frontend/`)
- [`middleware.ts`](./resources/frontend/middleware.ts):
  - Next.js edge route guard checking protected routes (`/dashboard`, `/checkout`, `/profile`).
  - Guards against premature eviction by recognizing valid refresh cookies on `Path=/`.
  - Automatically redirects authenticated users away from guest pages (`/auth/login`, `/auth/register`).
- [`useAuthStore.ts`](./resources/frontend/useAuthStore.ts):
  - Zustand auth store tracking `user`, `isAuthenticated`, and `isLoading`.
  - Safely hydrates from non-sensitive profile metadata in `localStorage`.
  - Connects with [`apiClient.ts`](../nextjs-api-sync/resources/apiClient.ts) and listens for `auth:session-expired` events.

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
    LoginAPIView,
    RefreshTokenView,
    LogoutAPIView,
    SendOtpView,
    VerifyOtpView,
)

urlpatterns = [
    path("api/v2/auth/login/", LoginAPIView.as_view(), name="auth-login"),
    path("api/v2/auth/token/refresh/", RefreshTokenView.as_view(), name="auth-refresh"),
    path("api/v2/auth/logout/", LogoutAPIView.as_view(), name="auth-logout"),
    path("api/v2/auth/otp/send/", SendOtpView.as_view(), name="auth-otp-send"),
    path("api/v2/auth/otp/verify/", VerifyOtpView.as_view(), name="auth-otp-verify"),
]
```

### Step 3: Deploy Frontend Middleware & Store
1. Copy [`resources/frontend/middleware.ts`](./resources/frontend/middleware.ts) into the root of your Next.js application (`frontend/middleware.ts`).
2. Copy [`resources/frontend/useAuthStore.ts`](./resources/frontend/useAuthStore.ts) into `frontend/stores/useAuthStore.ts`.
3. In your root React layout or auth provider, invoke `hydrateAuth()`:
```typescript
'use client';
import { useEffect } from 'react';
import { useAuthStore } from '@/stores/useAuthStore';

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const hydrateAuth = useAuthStore((state) => state.hydrateAuth);

  useEffect(() => {
    hydrateAuth();
  }, [hydrateAuth]);

  return <>{children}</>;
}
```
