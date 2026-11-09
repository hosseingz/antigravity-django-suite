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
| **`Path`** | `'/'` | **Path Fragmentation & SSR Route Eviction** | MUST be explicitly configured to `'/'` for BOTH access and refresh cookies. Restricting the refresh cookie path to `/api/auth/` prevents Next.js Edge route guards (`middleware.ts`) and SSR layouts from reading the refresh cookie on page navigation (e.g., `/dashboard`), causing catastrophic premature session eviction. |

---

## 2. Cryptographic Separation & CSRF Defense

### 2.1 Dedicated JWT Signing Key
Signing JWTs with the framework's core `settings.SECRET_KEY` is strictly prohibited:
- **Blast Radius Mitigation**: If the JWT signing key is rotated or leaked, core framework capabilities (password reset tokens, Django session signatures, form signing) remain intact.
- **Service Isolation**: Dedicated keys (`JWT_SIGNING_KEY`) can be securely distributed to edge proxies, microservices, or Next.js server runtimes without granting full admin-level framework access.
- In `config/settings.py`:
  ```python
  JWT_SIGNING_KEY = env("JWT_SIGNING_KEY")
  if not JWT_SIGNING_KEY and not DEBUG:
      raise ValueError("FATAL: JWT_SIGNING_KEY must be set in production environments.")
  ```

### 2.2 CSRF Defense for Cookie-Authenticated Requests
Because browsers automatically attach `HttpOnly` cookies to same-site and top-level navigation requests, state-changing requests (POST, PUT, PATCH, DELETE) authenticated via cookies are vulnerable to Cross-Site Request Forgery (CSRF).
- `CookieJWTAuthentication` strictly enforces CSRF verification (via DRF `CSRFCheck`) whenever the request credential originates from cookies.
- Pure Bearer header requests (used by mobile apps and third-party APIs) are exempt from CSRF checks because external scripts cannot inject arbitrary authorization headers cross-origin without CORS pre-flight consent.

---

## 3. Development vs. Production Cookie Policies

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

## 4. Session Eviction & Server-Side Invalidation

Simply deleting client-side state in React or Zustand does not log a user out; the browser continues attaching valid `HttpOnly` cookies to subsequent background network requests. Furthermore, stateless JWTs remain valid until their expiration timestamp unless tracked server-side.

### 4.1 Server-Side Blacklisting via Redis
During logout or token rotation:
1. The backend extracts the `jti` (JWT ID) from the active refresh token.
2. The remaining lifetime is calculated: `remaining_ttl = int(exp - now)`.
3. The `jti` is stored in the Redis blacklist:
   ```python
   cache.set(f"jwt:blacklist:{jti}", "revoked", timeout=remaining_ttl)
   ```
4. If an incoming token request presents a blacklisted `jti`, the request is immediately rejected.

### 4.2 Expired `Set-Cookie` Directives (`Max-Age=0`)
To completely purge cookies from browser storage, the backend must emit explicit eviction headers with `Path=/`:

```http
HTTP/1.1 200 OK
Set-Cookie: pod_access_token=; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Path=/; SameSite=Lax; HttpOnly
Set-Cookie: pod_refresh_token=; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Path=/; SameSite=Lax; HttpOnly
```

### 4.3 Implementation in `clear_auth_cookies`
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

### 4.4 Client-Side Eviction Synchronization
When `clear_auth_cookies` is received or `auth:session-expired` is broadcast:
1. `apiClient.ts` catches terminal 401s on refresh endpoints.
2. Dispatches `window.dispatchEvent(new CustomEvent('auth:session-expired'))`.
3. `useAuthStore.ts` purges `pod_user_metadata` from `localStorage`.
4. The user is redirected to `/auth/login?expired=true`.

---

## 5. Refresh Token Rotation (RTR) & Reuse Detection

Under RFC 6749 and OAuth 2.0 Security Best Current Practices, refresh tokens must be single-use credentials:

```
Normal Flow:
Client (Token A) ───► POST /token/refresh/ ───► Server:
                                                 1. Validates Token A
                                                 2. Blacklists Token A (jwt:blacklist:<jti_A>)
                                                 3. Issues Token B (jti_B)
                                                 4. Returns Set-Cookie: Token B

Attack / Reuse Flow:
Attacker (Token A) ──► POST /token/refresh/ ──► Server:
                                                 1. Finds jti_A in Redis blacklist!
                                                 2. Flags CRITICAL SECURITY EVENT: Token Reuse
                                                 3. Revokes all active tokens for that user
                                                 4. Returns HTTP 401 Unauthorized
```

### 5.1 Lifetime Cadence
| Token | Cookie Identifier | Suggested Lifetime | Purpose |
| :--- | :--- | :--- | :--- |
| **Access Token** | `pod_access_token` | **15 minutes** (`900s`) | Authorizes individual DRF API requests. Short lifetime limits the window of exposure if intercepted. |
| **Refresh Token** | `pod_refresh_token` | **7 days** (`604800s`) | Exchanged at `/api/v2/auth/token/refresh/` for a new access token and a freshly rotated refresh token. |
