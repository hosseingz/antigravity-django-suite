---
name: nextjs-api-sync
description: Authoritative blueprint for Next.js App Router and Django REST Framework API synchronization. Manages dual-environment networking (SSR vs CSR), Axios single-refresh mutex locks, CSRF handling, and DRF error normalization.
---

# Next.js API Synchronization Layer

This skill establishes the production communication layer between Next.js (App Router) and the Django REST Framework backend. It addresses the dual-environment runtime split (SSR vs. CSR), ensures seamless token refresh synchronization via a single-refresh mutex lock, automates Django CSRF token injection, and normalizes polymorphic DRF error responses.

---

## 1. Dual-Environment Architectural Routing

Next.js App Router executes across two distinct physical network boundaries. Requests originating from the server (Node.js runtime) and the client (user browser) must resolve to different network base URLs:

```
                      [ Client Web Browser ]
                                │
                                │ CSR Requests (Mutations, UI Interactions)
                                │ Base URL: NEXT_PUBLIC_API_BASE_URL (http://localhost:8080)
                                ▼
               ┌─────────────────────────────────┐
               │    Nginx Edge Proxy (:8080)     │
               └────────────────┬────────────────┘
                                │
             ┌──────────────────┴──────────────────┐
             │ Path: /                             │ Path: /api/, /admin/
             ▼                                     ▼
┌─────────────────────────┐               ┌─────────────────────────┐
│ Next.js Frontend :3000  │               │   Django Backend :8000  │
│ (SSR / RSC Node Server) │               │   (DRF, Gunicorn, ASGI) │
└────────────┬────────────┘               └────────────▲────────────┘
             │                                         │
             │ SSR Server Component Fetch              │
             │ Base URL: INTERNAL_API_BASE_URL         │
             │ (http://backend:8000 via Docker Bridge) │
             └─────────────────────────────────────────┘
```

### 1.1 Network Boundary Specifications
- **SSR (Server-Side Rendering & Server Actions)**:
  - **Base URL**: `INTERNAL_API_BASE_URL` (Defaults to `http://backend:8000`).
  - **Transport**: [`resources/serverFetch.ts`](./resources/serverFetch.ts).
  - **Context**: Communicates over Docker's internal network bridge (`internal_net`). Eliminates NAT loopback hairpinning and bypasses TLS termination latency.
- **CSR (Client-Side Rendering & React Hooks)**:
  - **Base URL**: `NEXT_PUBLIC_API_BASE_URL` (Defaults to `http://localhost:8080` in local dev or empty string for same-origin proxying).
  - **Transport**: [`resources/apiClient.ts`](./resources/apiClient.ts).
  - **Context**: Executes in the user's browser, traversing the public edge gateway / reverse proxy.

For full technical analysis, consult [`references/ssr-vs-csr-routing.md`](./references/ssr-vs-csr-routing.md).

---

## 2. Critical Execution Boundary Warning

> [!CAUTION]
> **Boundary Violation Prevention**:
> [`resources/apiClient.ts`](./resources/apiClient.ts) references browser-only globals (`document.cookie`, `window`, and Axios interceptors).
> **It MUST NEVER be imported or invoked inside React Server Components (RSC) or Server Actions.**
>
> Attempting to import `apiClient.ts` on the server triggers runtime exceptions (`ReferenceError: document is not defined`) and leaks request-level auth state across concurrent server threads.
>
> **Enforcement**:
> - For React Server Components (RSC), Route Handlers, and Server Actions: **ALWAYS** import and use [`resources/serverFetch.ts`](./resources/serverFetch.ts).
> - For Client Components (`'use client'`), interactive hooks, and client-side mutations: **ALWAYS** use [`resources/apiClient.ts`](./resources/apiClient.ts).

---

## 2.5 Response & Error Contract (Normative)

Success payloads are **never** wrapped (`{data: ...}` is strictly prohibited).

### Collections Contract
| Class | Response Shape | Ownership & Constraints |
| :--- | :--- | :--- |
| **Pageable Collections** (`/posts/`) | `{count, next, previous, results}` | Server owns pagination via `PageNumberPagination`. Client MUST render `count` and follow `next`/`previous` query params (`?page=2`). **Local client slicing (`.slice(0, 9)`) or re-pagination is prohibited.** |
| **Bounded Lookup Collections** (`/categories/`, `/tags/`) | Bare array `[...]` | Allowed **only** via documented `pagination_class = None` allowlists (maximum ~100 items). |
| **Nested / Action Collections** (`/posts/{slug}/comments/`) | Bare array `[...]` | Must be explicitly documented in the endpoint inventory. |
| **Single Resource** (`/posts/{slug}/`) | Bare object `{...}` | Direct entity representation without wrappers. |
| **State Mutations** (`/posts/{slug}/like/`) | Bare object `{...}` | Contains only changed fields (`{likes, has_liked}`). |

> [!IMPORTANT]
> **No Ambiguous Fallback Guessing**:
> Client code MUST NOT use fallback patterns like `data.results || data || []`. The endpoint inventory dictates the exact contract shape; fallback guessing masks contract drift.

### Canonical Field Naming
- One name per concept across list, detail, and mutation views (`likes`, `bookmarks`, `comments_count`).
- Serializer emitting `likes` while mutation emits `{likes, has_liked}` and client expects `likes_count` is a defect.
- Domain fields MUST NOT be renamed on the client; rename only UI display strings (e.g., `publishDate`).

### Standardized Error Contract
All 4xx and 5xx responses conform to a 3-part contract:
```json
{
  "detail": "Human-readable summary message.",
  "code": "stable_snake_case_code",
  "fields": {
    "password": ["This password is too short."]
  }
}
```
- `detail`: Always a **string** (never a list, never absent). Code must never call `ValidationError({"detail": [...]})`.
- `code`: Always present and stable (`validation_error`, `not_found`, `permission_denied`, `authentication_required`, `token_refresh_required`, `throttled`, `csrf_failed`).
- `fields`: Present **only** on validation errors, keyed by write field name. Cross-field errors belong in `detail`. `fields` must never contain `detail`, `code`, or `non_field_errors`.

### Status Matrix
| Scenario | Status Code | Error `code` | Notes |
| :--- | :--- | :--- | :--- |
| Validation Failure | `400 Bad Request` | `validation_error` | Carries populated `fields` object |
| Invalid Login Credentials | `400 Bad Request` | `invalid_credentials` | Documented exception: never triggers 401 refresh |
| Missing / Expired Credential | `401 Unauthorized` | `authentication_required` / `token_refresh_required` | Only status triggering apiClient mutex refresh |
| CSRF Failure | `403 Forbidden` | `csrf_failed` | PermissionDenied |
| Forbidden Resource | `403 Forbidden` | `permission_denied` | Authenticated but lacks permissions |
| Resource Not Found | `404 Not Found` | `not_found` | Missing entity |
| Rate Limited | `429 Too Many Requests` | `throttled` | Includes `Retry-After` header |

---

## 3. Single-Refresh Mutex Lock & CSRF Attachment

### 3.1 Single-Refresh Mutex Pattern
When access tokens expire, concurrent client-side requests will simultaneously receive HTTP `401 Unauthorized`. Without coordination, each request triggers its own refresh call, causing race conditions and database session invalidations.

[`resources/apiClient.ts`](./resources/apiClient.ts) implements an atomic single-refresh mutex:
1. Catches the initial `401 Unauthorized`.
2. Sets `isRefreshing = true` and holds subsequent failing requests in a FIFO memory queue (`failedQueue`).
3. Executes a single call to `/api/v2/auth/token/refresh/` using secure `HttpOnly` cookies.
4. On success: Drains `failedQueue`, replaying all queued requests with refreshed authorization credentials.
5. On failure: Rejects all queued requests and dispatches `auth:session-expired` to evict client state.
6. **Loop Protection**: Explicitly excludes `/token/refresh/`, `/login/`, and `/logout/` from retry recursion to prevent infinite loops.

### 3.2 Automated CSRF Attachment
For mutating requests (`POST`, `PUT`, `PATCH`, `DELETE`), `apiClient` automatically extracts the `csrftoken` cookie and injects the `X-CSRFToken` header required by Django's `CsrfViewMiddleware`.

---

## 4. AI Guardrails & Anti-Patterns

- **Anti-Pattern 1: Evaluating Base URLs at Build Time**
  - *Rule*: Never compute API URLs as static top-level string constants.
  - *Risk*: `next build` runs in Node.js, causing build-time inlining of `http://backend:8000` into client bundles, leaking Docker topology and breaking browser network requests.
  - *Solution*: Always use dynamic property getters in [`resources/apiConfig.ts`](./resources/apiConfig.ts).

- **Anti-Pattern 2: Uncoordinated Parallel Token Refreshes**
  - *Rule*: Never allow parallel 401 handlers to fire concurrent refresh requests.
  - *Risk*: Refresh token rotation invalidates the first token immediately; subsequent concurrent refresh calls fail, wiping user sessions unpredictably.
  - *Solution*: Queue all parallel 401s behind the mutex lock in `apiClient.ts`.

- **Anti-Pattern 3: Storing JWTs in `localStorage` or `sessionStorage`**
  - *Rule*: Tokens must never touch browser web storage per [`.agent/rules/ai-guardrails.md`](../../.agent/rules/ai-guardrails.md).
  - *Risk*: Direct vulnerability to Cross-Site Scripting (XSS) credential theft.
  - *Solution*: Rely entirely on `HttpOnly`, `SameSite=Lax`, `Secure` cookies with `withCredentials: true`.

- **Anti-Pattern 4: Importing Browser Client in React Server Components**
  - *Rule*: Never import `apiClient.ts` into server-rendered files.
  - *Risk*: Crashes with `document is not defined` and fails to forward user cookies from incoming requests.
  - *Solution*: Use `serverFetch.ts`, which extracts `cookies()` via `next/headers`.

- **Anti-Pattern 5: Ad-hoc Field Renaming & Client-Side List Slicing**
  - *Rule*: Never rename API fields on the client or slice paginated collections locally.
  - *Risk*: Slicing `.slice(0, 9)` over page 1 means users never see items on page 2+; ad-hoc renaming causes `undefined` renders.
  - *Solution*: Server owns pagination (`?page=`, `?search=`, `?category=`), client renders server-provided `count`, `next`, and `previous`.

- **Anti-Pattern 6: Binding System/Non-Field Errors to Form Inputs**
  - *Rule*: Non-field error keys (`detail`, `non_field_errors`, `code`) must never be mapped to individual form fields.
  - *Risk*: Error is attached to a non-existent input (`input[name="detail"]`), leaving form alert banners empty.
  - *Solution*: Filter out `NON_FIELD_KEYS` in `extractFieldErrors` and bind them exclusively to top-level alert banners via `extractNonFieldError`.

---

## 5. DRF Error Normalization

Django REST Framework generates diverse error formats (field arrays, `non_field_errors`, `detail`, nested dicts, HTML gateway crashes). 

[`resources/errorUtils.ts`](./resources/errorUtils.ts) provides:
- `extractErrorMessage(err)`: Returns the highest-priority human-readable message for toasts and banners.
- `extractFieldErrors(err)`: Returns a structured `Record<string, string[]>` excluding non-field keys, for direct binding to form libraries.
- `extractNonFieldError(err)`: Returns top-level non-field message for alert banners.

For detailed breakdown, consult [`references/error-normalization.md`](./references/error-normalization.md).

---

## 6. Bundled Resource Templates

The following production-grade TypeScript templates are available in [`resources/`](./resources):

- [`apiConfig.ts`](./resources/apiConfig.ts): Dynamic base URL resolution and getter-based `API_ENDPOINTS` registry with API versioning and local dev SSR fallback.
- [`apiClient.ts`](./resources/apiClient.ts): Client-side Axios instance with single-refresh mutex lock and CSRF injection.
- [`serverFetch.ts`](./resources/serverFetch.ts): Server-side RSC fetch utility with automatic Next.js cookie forwarding.
- [`errorUtils.ts`](./resources/errorUtils.ts): Robust DRF error parsing and form field mapping utility.
- [`apiTypes.ts`](./resources/apiTypes.ts): Canonical TypeScript interfaces for paginated collections and error payloads.

---

## 7. Agent Scaffolding Procedure

When integrating this communication layer into a target Next.js application:

### Step 1: Verify Dependencies
Ensure the target Next.js project has `axios` installed:
```bash
npm install axios
```

### Step 2: Deploy Resource Templates
Copy the templates into the frontend application directory structure:
1. `resources/apiConfig.ts` -> `<frontend>/lib/api/apiConfig.ts`
2. `resources/apiClient.ts` -> `<frontend>/lib/api/apiClient.ts`
3. `resources/serverFetch.ts` -> `<frontend>/lib/api/serverFetch.ts`
4. `resources/errorUtils.ts` -> `<frontend>/lib/api/errorUtils.ts`
5. `resources/apiTypes.ts` -> `<frontend>/types/api.ts`

### Step 3: Configure Environment Variables
Ensure `.env.local` (and container environments) define both bases:
```env
# Server-side internal Docker routing (SSR)
INTERNAL_API_BASE_URL=http://backend:8000

# Client-side public edge routing (CSR)
NEXT_PUBLIC_API_BASE_URL=http://localhost:8080
```

### Step 3.5: Module Resolution & Type Integrity Gate
Assert that all required sync modules exist on disk and compile without error:
```bash
for f in lib/api/apiConfig.ts lib/api/apiClient.ts lib/api/serverFetch.ts lib/api/errorUtils.ts types/api.ts; do
  test -f "frontend/$f" || { echo "FATAL: Missing required sync module frontend/$f"; exit 1; }
done
cd frontend && npx tsc --noEmit
```
A codebase importing `@/lib/api/*` without these files fails compilation immediately.

### Step 4: Validate Boundary Separation
- In Server Components: Verify calls use `serverFetch('/api/v1/...')`.
- In Client Components: Verify calls use `apiClient.get('/api/v1/...')`.
