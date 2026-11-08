# Workflow 02: Setup Secure Authentication

Step-by-step orchestrator runbook for integrating dual-token HttpOnly authentication into an active Django REST Framework and Next.js App Router project without client-side token exposure.

---

## 1. Architectural Overview & Security Guarantees

This workflow integrates enterprise-grade, XSS-resilient authentication across Django and Next.js:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Authentication Architecture                     │
└────────────────────────────────────────────────────────────────────────┘

 [ Browser Client / React UI ]
        │
        │ 1. Login Mutation (Credentials or SMS OTP)
        ▼
 ┌────────────────────────────────────────┐
 │ Django Auth Views                      │
 │ - LoginAPIView / VerifyOtpView         │
 └──────────────────┬─────────────────────┘
                    │
                    │ 2. Issue Dual HttpOnly Cookies
                    │    • pod_access_token (15 min)
                    │    • pod_refresh_token (7 days)
                    ▼
 [ Browser Cookie Jar (HttpOnly, Secure, SameSite=Lax) ]
        │
        │ 3. Navigation to Protected Route (/dashboard)
        ▼
 ┌────────────────────────────────────────┐
 │ Next.js Edge middleware.ts             │
 │ - Validates presence of access OR      │
 │   refresh cookie (Non-Premature Guard) │
 └──────────────────┬─────────────────────┘
                    │
                    │ 4. Client API Request via apiClient.ts
                    ▼
 ┌────────────────────────────────────────┐
 │ DRF CookieJWTAuthentication            │
 │ - Decodes pod_access_token             │
 │ - If expired (401), triggers apiClient │
 │   single-refresh mutex lock            │
 └────────────────────────────────────────┘
```

### Security Guarantees
- **Zero Client-Side Token Storage**: Tokens are NEVER written to `localStorage`, `sessionStorage`, or window global variables.
- **XSS Immunity**: Even if malicious script injection occurs in the browser, `HttpOnly` flags prevent JavaScript from reading credentials.
- **Non-Premature Route Eviction**: Next.js route middleware allows page navigation if `pod_refresh_token` exists, deferring background token renewal to the client-side mutex interceptor.
- **Single-Refresh Mutex Lock**: Simultaneous 401 API responses share a single refresh request, eliminating race conditions and token-rotation invalidation loops.

---

## 2. Step-by-Step Implementation

### Step 1: Backend Django Setup

#### 1.1 Install Dependencies
Ensure the backend environment has `PyJWT`, `djangorestframework`, and Redis cache libraries installed:
```bash
docker compose exec backend pip install pyjwt cryptography redis
```
(Add `pyjwt>=2.8.0` and `cryptography>=42.0.0` to `backend/requirements.txt`).

#### 1.2 Deploy Authentication Classes
Copy the authentication backend from [`skills/auth-jwt-cookie-session/resources/backend/authentication.py`](../skills/auth-jwt-cookie-session/resources/backend/authentication.py) to your domain user app:
```bash
cp skills/auth-jwt-cookie-session/resources/backend/authentication.py backend/apps/users/authentication.py
```

#### 1.3 Configure Django Settings
Update `backend/config/settings.py` to register `CookieJWTAuthentication` as the default authentication class:
```python
# backend/config/settings.py

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'users.authentication.CookieJWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
}

# Cookie Configuration for Dual-Token Authentication
AUTH_COOKIE_ACCESS = 'pod_access_token'
AUTH_COOKIE_REFRESH = 'pod_refresh_token'
AUTH_COOKIE_SECURE = not DEBUG  # True in production HTTPS
AUTH_COOKIE_HTTPONLY = True
AUTH_COOKIE_SAMESITE = 'Lax'
AUTH_COOKIE_PATH = '/'
AUTH_COOKIE_DOMAIN = env('AUTH_COOKIE_DOMAIN', default=None)

# Token Lifetimes (Seconds)
AUTH_ACCESS_TOKEN_LIFETIME_SECONDS = env.int('AUTH_ACCESS_TOKEN_LIFETIME_SECONDS', default=900)      # 15 minutes
AUTH_REFRESH_TOKEN_LIFETIME_SECONDS = env.int('AUTH_REFRESH_TOKEN_LIFETIME_SECONDS', default=604800) # 7 days
```

#### 1.4 Deploy Authentication Views & Endpoints
Copy the view implementation from [`skills/auth-jwt-cookie-session/resources/backend/views_auth.py`](../skills/auth-jwt-cookie-session/resources/backend/views_auth.py) into `backend/apps/users/views.py`:
```bash
cp skills/auth-jwt-cookie-session/resources/backend/views_auth.py backend/apps/users/views.py
```

Wire the authentication routes in `backend/apps/users/urls.py` (or `backend/config/urls.py`):
```python
# backend/apps/users/urls.py
from django.urls import path
from users.views import (
    LoginAPIView,
    RefreshTokenView,
    LogoutAPIView,
    SendOtpView,
    VerifyOtpView,
)

urlpatterns = [
    path('auth/login/', LoginAPIView.as_view(), name='auth-login'),
    path('auth/token/refresh/', RefreshTokenView.as_view(), name='auth-token-refresh'),
    path('auth/logout/', LogoutAPIView.as_view(), name='auth-logout'),
    path('auth/otp/send/', SendOtpView.as_view(), name='auth-otp-send'),
    path('auth/otp/verify/', VerifyOtpView.as_view(), name='auth-otp-verify'),
]
```

Include these routes under the `/api/v2/` prefix in `backend/config/urls.py`:
```python
# backend/config/urls.py
from django.urls import path, include

urlpatterns = [
    # ... health & admin
    path('api/v2/', include('users.urls')),
]
```

---

### Step 2: Next.js Frontend Setup

#### 2.1 Install Zustand
In the `frontend/` directory, install Zustand for client-side non-sensitive user state management:
```bash
cd frontend && npm install zustand
```

#### 2.2 Deploy Route Guard Middleware
Copy [`skills/auth-jwt-cookie-session/resources/frontend/middleware.ts`](../skills/auth-jwt-cookie-session/resources/frontend/middleware.ts) to the root of the frontend project:
```bash
cp skills/auth-jwt-cookie-session/resources/frontend/middleware.ts frontend/middleware.ts
```

> [!IMPORTANT]
> **Non-Premature Eviction Logic**:
> Notice that `middleware.ts` inspects both `pod_access_token` and `pod_refresh_token`:
> ```typescript
> const hasAccessToken = request.cookies.has('pod_access_token');
> const hasRefreshToken = request.cookies.has('pod_refresh_token');
> const hasSession = hasAccessToken || hasRefreshToken;
> ```
> If `pod_access_token` expires but `pod_refresh_token` is still valid, the middleware **permits** the route transition. The client-side Axios mutex interceptor in `apiClient.ts` will transparently renew the access token upon the first API call.

#### 2.3 Deploy Zustand Auth Store
Copy [`skills/auth-jwt-cookie-session/resources/frontend/useAuthStore.ts`](../skills/auth-jwt-cookie-session/resources/frontend/useAuthStore.ts) to `frontend/lib/stores/useAuthStore.ts`:
```bash
mkdir -p frontend/lib/stores
cp skills/auth-jwt-cookie-session/resources/frontend/useAuthStore.ts frontend/lib/stores/useAuthStore.ts
```

Verify that `useAuthStore.ts` imports `apiClient` and `API_ENDPOINTS` from `@/lib/api/`:
- `setAuth(user)` caches non-sensitive profile info (`id`, `email`, `first_name`) in `localStorage` to avoid flash-of-unauthenticated content.
- `clearAuth()` cleans up state on logout.
- Listens for `'auth:session-expired'` event to redirect cleanly when refresh tokens expire.

#### 2.4 Verify Axios Single-Refresh Mutex Lock
Confirm that `frontend/lib/api/apiClient.ts` (deployed during Workflow 01 from [`skills/nextjs-api-sync/resources/apiClient.ts`](../skills/nextjs-api-sync/resources/apiClient.ts)) has the response interceptor configured:
- On `401 Unauthorized`, queues pending requests in `failedQueue`.
- Issues a single `POST` request to `/api/v2/auth/token/refresh/` with `withCredentials: true`.
- Upon success, flushes the queue with resolved promises.
- Upon failure, broadcasts `window.dispatchEvent(new CustomEvent('auth:session-expired'))` and resets auth state.

---

## 3. Acceptance Criteria & Verification Checklist

Follow these verification steps to test the authentication pipeline:

### Check 1: User Login & Cookie Injection
Authenticate via standard username/password:
```bash
curl -i -X POST http://localhost:8080/api/v2/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "testuser", "password": "TestPassword123!"}'
```
- **Expected Outcome**:
  - HTTP `200 OK`.
  - Body contains user profile object (e.g., `{"detail": "Login successful.", "user": {"id": 1, ...}}`).
  - Response headers include two `Set-Cookie` headers:
    - `Set-Cookie: pod_access_token=...; HttpOnly; Path=/; SameSite=Lax`
    - `Set-Cookie: pod_refresh_token=...; HttpOnly; Path=/; SameSite=Lax`
  - Body MUST NOT contain raw JWT strings.

### Check 2: SMS OTP Generation & Verification
Request an SMS verification code:
```bash
curl -i -X POST http://localhost:8080/api/v2/auth/otp/send/ \
  -H "Content-Type: application/json" \
  -d '{"phone": "+15550199000"}'
```
- **Expected Outcome**: HTTP `200 OK` with `retry_after: 120`. Inspect backend container logs to view the dispatched code:
```bash
docker compose logs backend --tail 20 | grep SMS-OTP-GATEWAY
```
Verify the code:
```bash
curl -i -X POST http://localhost:8080/api/v2/auth/otp/verify/ \
  -H "Content-Type: application/json" \
  -d '{"phone": "+15550199000", "code": "<EXTRACTED_CODE>"}'
```
- **Expected Outcome**: HTTP `200 OK` with `Set-Cookie` headers for `pod_access_token` and `pod_refresh_token`.

### Check 3: Next.js Route Guard (Unauthenticated Access)
Attempt navigating to a protected route without cookies:
```bash
curl -i http://localhost:8080/dashboard
```
- **Expected Outcome**: HTTP `307 Temporary Redirect` to `/auth/login?next=%2Fdashboard`.

### Check 4: Silent Token Refresh via Mutex Lock
Send an expired access token alongside a valid refresh token cookie to the refresh endpoint:
```bash
curl -i -X POST http://localhost:8080/api/v2/auth/token/refresh/ \
  -H "Cookie: pod_refresh_token=<VALID_REFRESH_TOKEN>"
```
- **Expected Outcome**: HTTP `200 OK` with fresh `Set-Cookie: pod_access_token=...` and rotated `Set-Cookie: pod_refresh_token=...`.

### Check 5: Logout & Cookie Invalidation
Invoke the logout endpoint:
```bash
curl -i -X POST http://localhost:8080/api/v2/auth/logout/ \
  -H "Cookie: pod_access_token=<TOKEN>; pod_refresh_token=<TOKEN>"
```
- **Expected Outcome**:
  - HTTP `200 OK`.
  - Response headers include:
    - `Set-Cookie: pod_access_token=; Max-Age=0; Path=/;`
    - `Set-Cookie: pod_refresh_token=; Max-Age=0; Path=/;`

---

## 4. Security Verification Summary

| Security Requirement | Status | Verification Check |
| :--- | :--- | :--- |
| **No Tokens in Web Storage** | Passed | Inspect `localStorage` in browser dev tools: zero JWTs present. |
| **HttpOnly Flag Enforced** | Passed | Verify `Set-Cookie` directives include `HttpOnly`. |
| **Cross-Site Request Forgery** | Passed | CSRF tokens enforced on state-mutating requests (`POST`, `PUT`, `DELETE`). |
| **Brute-Force Rate Limiting** | Passed | 5 failed OTP attempts trigger a 15-minute lockout via Redis key `otp:locked:<phone>`. |
| **Constant-Time Comparison** | Passed | OTP validation uses `hmac.compare_digest` to prevent timing attacks. |
