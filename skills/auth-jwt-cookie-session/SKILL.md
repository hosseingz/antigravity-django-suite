---
name: auth-jwt-cookie-session
description: Authoritative blueprint for dual-token HttpOnly cookie authentication, custom DRF CookieJWTAuthentication, Redis-backed SMS OTP lifecycle, Next.js routing middleware, and Zustand identity store.
---

# Auth JWT & Cookie Session Management

This skill establishes the production-grade authentication pipeline combining Django REST Framework (DRF) and Next.js (App Router). It implements a secure dual-token HttpOnly cookie strategy (`pod_access_token` and `pod_refresh_token`), custom `CookieJWTAuthentication`, Redis-backed SMS OTP verification, non-premature Next.js route protection middleware, and Zustand auth state management.

---

## 1. Visual ASCII Architectural Diagram

```
[ Browser Client Context ]                 [ Next.js App Router ]                 [ Django Backend (DRF) ]
            │                                         │                                      │
            │ 1. Navigate to /dashboard               │                                      │
            ├────────────────────────────────────────►│                                      │
            │                                         │ 2. middleware.ts                     │
            │                                         │    Inspect cookies:                  │
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
            │                                                                                │    Decodes pod_access_token
            │                                                                                │    [Expired Signature]
            │ 6. HTTP 401 Unauthorized (code: token_refresh_required)                        │
            │◄───────────────────────────────────────────────────────────────────────────────┤
            │                                                                                │
            │ 7. apiClient Mutex Lock intercepts 401:                                        │
            │    POST /api/v2/auth/token/refresh/                                            │
            │    [Browser auto-attaches HttpOnly Cookie: pod_refresh_token]                  │
            ├───────────────────────────────────────────────────────────────────────────────►│
            │                                                                                │ 8. RefreshTokenView:
            │                                                                                │    Decodes pod_refresh_token
            │                                                                                │    Issues fresh token pair
            │ 9. HTTP 200 OK + Set-Cookie: pod_access_token & pod_refresh_token              │
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

---

## 3. Suite Integration & Component Architecture

### 3.1 Backend Components (`resources/backend/`)
- [`authentication.py`](./resources/backend/authentication.py):
  - Extends DRF `BaseAuthentication`.
  - Prioritizes `Authorization: Bearer <token>` header (for external/mobile clients), falling back to `pod_access_token` HttpOnly cookie.
  - Decodes and validates tokens against Django's `settings.SECRET_KEY` using HS256.
  - Implements anti-silent-degradation logic for seamless token refresh.
- [`views_auth.py`](./resources/backend/views_auth.py):
  - `set_auth_cookies()` & `clear_auth_cookies()`: Encapsulates cookie generation with `HttpOnly`, `SameSite=Lax`, and environment-aware `Secure` flags.
  - `LoginAPIView`: Authenticates credentials and writes dual cookies without leaking tokens into response JSON.
  - `RefreshTokenView`: Verifies `pod_refresh_token` and performs automated token rotation.
  - `LogoutAPIView`: Emits `Max-Age=0` eviction headers to wipe session cookies.
  - `SendOtpView` & `VerifyOtpView`: Redis-backed passwordless SMS verification with 120s cooldowns and 5-attempt brute-force lockouts.

### 3.2 Frontend Components (`resources/frontend/`)
- [`middleware.ts`](./resources/frontend/middleware.ts):
  - Next.js edge route guard checking protected routes (`/dashboard`, `/checkout`, `/profile`).
  - Guards against premature eviction by recognizing valid refresh cookies.
  - Automatically redirects authenticated users away from guest pages (`/auth/login`, `/auth/register`).
- [`useAuthStore.ts`](./resources/frontend/useAuthStore.ts):
  - Zustand auth store tracking `user`, `isAuthenticated`, and `isLoading`.
  - Safely hydrates from non-sensitive profile metadata in `localStorage`.
  - Connects with [`apiClient.ts`](../nextjs-api-sync/resources/apiClient.ts) and listens for `auth:session-expired` events.

### 3.3 Deep-Dive Technical References
- [`references/cookie-lifecycle.md`](./references/cookie-lifecycle.md): Detailed analysis of HttpOnly, Secure, and SameSite flags, development vs. production policies, and session eviction.
- [`references/sms-otp-workflow.md`](./references/sms-otp-workflow.md): Redis key lifecycle (`otp:code`, `otp:cooldown`, `otp:attempts`, `otp:locked`), timing attack mitigations, and `retry_after` frontend synchronization.

---

## 4. Scaffolding & Setup Procedure

### Step 1: Configure Backend Authentication
In `backend/config/settings.py` (referencing [`django-core-architecture`](../django-core-architecture/resources/settings.py)):
```python
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "users.authentication.CookieJWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

# Cookie Configuration
AUTH_ACCESS_TOKEN_LIFETIME_SECONDS = 900       # 15 minutes
AUTH_REFRESH_TOKEN_LIFETIME_SECONDS = 604800   # 7 days
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
