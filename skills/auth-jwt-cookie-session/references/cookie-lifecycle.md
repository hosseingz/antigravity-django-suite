# Technical Reference: Dual-Token HttpOnly Cookie Lifecycle

This document provides in-depth technical analysis of the dual-token HttpOnly cookie architecture used across Django REST Framework and Next.js applications in `antigravity-django-suite`.

---

## 1. Security Architecture & Threat Vector Mitigation

Storing authentication tokens in browser `localStorage` or `sessionStorage` introduces severe vulnerabilities: any Cross-Site Scripting (XSS) vulnerability anywhere on the domain permits an attacker to execute `localStorage.getItem('token')` and exfiltrate long-lived credentials.

To provide defense-in-depth, this suite enforces a dual-token HttpOnly cookie architecture:

```
┌────────────────────────────────────────────────────────────────────────┐
│                             BROWSER RUNTIME                            │
│                                                                        │
│   ┌───────────────────────────┐      ┌─────────────────────────────┐   │
│   │   JavaScript Context      │      │   Protected Cookie Store    │   │
│   │   (Zustand, React UI)     │      │   (Inaccessible to JS)      │   │
│   │                           │      │                             │   │
│   │ • pod_user_metadata (safe)│      │ • pod_access_token          │   │
│   │ • isLoading, isAuth       │      │   (HttpOnly, SameSite=Lax)  │   │
│   │                           │      │ • pod_refresh_token         │   │
│   │   [No Raw Tokens Here]    │      │   (HttpOnly, SameSite=Lax)  │   │
│   └───────────────────────────┘      └──────────────┬──────────────┘   │
└─────────────────────────────────────────────────────┼──────────────────┘
                                                      │
                       Automatic Cookie Header on     │
                       Same-Origin / CORS Requests    │
                                                      ▼
                                       ┌─────────────────────────────┐
                                       │   Django Backend (DRF)      │
                                       │   CookieJWTAuthentication   │
                                       └─────────────────────────────┘
```

### 1.1 Cookie Security Flags Deep-Dive

| Cookie Flag | Value | Threat Mitigated | Technical Mechanism |
| :--- | :--- | :--- | :--- |
| **`HttpOnly`** | `True` | **Cross-Site Scripting (XSS)** | Directives with `HttpOnly` are hidden from client JavaScript APIs (`document.cookie`). Malicious scripts injected through DOM XSS cannot read, serialize, or exfiltrate the JWT. |
| **`Secure`** | `not settings.DEBUG` | **Man-in-the-Middle (MitM) & Wiretapping** | Forces the browser to send cookies exclusively over encrypted TLS/HTTPS connections. In local development (`DEBUG=True`), plain HTTP over `localhost` is supported. |
| **`SameSite`** | `'Lax'` | **Cross-Site Request Forgery (CSRF)** | Withholds the authentication cookie on cross-origin subrequests (e.g., third-party `<img>`, `<fetch>`, or `<form>` POSTs) while permitting normal top-level navigation links. |
| **`Path`** | `'/'` | **Path-Traversing Fragmentation** | Scopes the cookie across the entire domain so both SSR routes, API routes, and client interceptors maintain unified authentication state. |

---

## 2. Development vs. Production Cookie Policies

A common point of failure when deploying Dockerized or staging stacks is cookie rejection due to misconfigured `Secure` or `Domain` attributes:

### 2.1 The Secure Flag Switch
In `config/settings.py` and `resources/backend/views_auth.py`:
```python
# resources/backend/views_auth.py
secure_flag = not getattr(settings, "DEBUG", False)

response.set_cookie(
    key="pod_access_token",
    value=access_token,
    max_age=900,
    httponly=True,
    secure=secure_flag,
    samesite="Lax",
    path="/",
)
```

- **In Local Development (`DEBUG = True`)**: `secure=False` allows browser cookies to be written over unencrypted `http://localhost:3000` or `http://localhost:8080`.
- **In Production (`DEBUG = False`)**: `secure=True` is strictly enforced. Attempting to set or transmit a `secure` cookie over plaintext HTTP will cause modern browsers to discard the `Set-Cookie` header silently.

### 2.2 Cross-Origin & Credentials Setup
When the frontend (`https://app.example.com`) and backend (`https://api.example.com`) run on separate subdomains:
- `CORS_ALLOW_CREDENTIALS = True` must be enabled in Django settings.
- `CORS_ALLOWED_ORIGINS` must list the explicit frontend domain (wildcard `*` is strictly disallowed by browsers when credentials are enabled).
- In Axios: `withCredentials: true` must be enabled on every request (already baked into `resources/frontend/../../nextjs-api-sync/resources/apiClient.ts`).

---

## 3. Session Eviction & Invalidation Protocol

Simply deleting client-side state in React or Zustand does not log a user out; the browser continues attaching valid `HttpOnly` cookies to subsequent background network requests.

### 3.1 Expired `Set-Cookie` Directives (`Max-Age=0`)
To completely purge cookies from browser storage, the backend must emit explicit eviction headers:

```http
HTTP/1.1 200 OK
Set-Cookie: pod_access_token=; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Path=/; SameSite=Lax; HttpOnly
Set-Cookie: pod_refresh_token=; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Path=/; SameSite=Lax; HttpOnly
```

### 3.2 Implementation in `clear_auth_cookies`
```python
def clear_auth_cookies(response: Response) -> Response:
    secure_flag = not getattr(settings, "DEBUG", False)

    for cookie_name in ("pod_access_token", "pod_refresh_token"):
        response.delete_cookie(
            key=cookie_name,
            path="/",
            samesite="Lax",
        )
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
```

### 3.3 Client-Side Eviction Synchronization
When `clear_auth_cookies` is received or `auth:session-expired` is broadcast:
1. `apiClient.ts` catches terminal 401s on refresh endpoints.
2. Dispatches `window.dispatchEvent(new CustomEvent('auth:session-expired'))`.
3. `useAuthStore.ts` purges `pod_user_metadata` from `localStorage`.
4. The user is redirected to `/auth/login?expired=true`.

---

## 4. Token Lifetime & Refresh Cadence

| Token | Cookie Identifier | Suggested Lifetime | Purpose |
| :--- | :--- | :--- | :--- |
| **Access Token** | `pod_access_token` | **15 minutes** (`900s`) | Authorizes individual DRF API requests. Short lifetime limits the window of exposure if intercepted. |
| **Refresh Token** | `pod_refresh_token` | **7 days** (`604800s`) | Exchanged at `/api/v2/auth/token/refresh/` for a new access token (and optionally a rotated refresh token). |

This cadence ensures that even if an access token is compromised, its validity is strictly bounded, while legitimate users enjoy seamless multi-day sessions without disruptive login prompts.
