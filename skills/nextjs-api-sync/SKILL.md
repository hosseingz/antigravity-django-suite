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

---

## 5. DRF Error Normalization

Django REST Framework generates diverse error formats (field arrays, `non_field_errors`, `detail`, nested dicts, HTML gateway crashes). 

[`resources/errorUtils.ts`](./resources/errorUtils.ts) provides:
- `extractErrorMessage(err)`: Returns the highest-priority human-readable message for toasts and banners.
- `extractFieldErrors(err)`: Returns a structured `Record<string, string[]>` for direct binding to form libraries (e.g. React Hook Form).

For detailed breakdown, consult [`references/error-normalization.md`](./references/error-normalization.md).

---

## 6. Bundled Resource Templates

The following production-grade TypeScript templates are available in [`resources/`](./resources):

- [`apiConfig.ts`](./resources/apiConfig.ts): Dynamic base URL resolution and getter-based `API_ENDPOINTS` registry.
- [`apiClient.ts`](./resources/apiClient.ts): Client-side Axios instance with single-refresh mutex lock and CSRF injection.
- [`serverFetch.ts`](./resources/serverFetch.ts): Server-side RSC fetch utility with automatic Next.js cookie forwarding.
- [`errorUtils.ts`](./resources/errorUtils.ts): Robust DRF error parsing and form field mapping utility.

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
1. `resources/apiConfig.ts` -> `<frontend>/src/lib/api/config.ts`
2. `resources/apiClient.ts` -> `<frontend>/src/lib/api/client.ts`
3. `resources/serverFetch.ts` -> `<frontend>/src/lib/api/serverFetch.ts`
4. `resources/errorUtils.ts` -> `<frontend>/src/lib/api/errorUtils.ts`

### Step 3: Configure Environment Variables
Ensure `.env.local` (and container environments) define both bases:
```env
# Server-side internal Docker routing
INTERNAL_API_BASE_URL=http://backend:8000

# Client-side public edge routing
NEXT_PUBLIC_API_BASE_URL=http://localhost:8080
```

### Step 4: Validate Boundary Separation
- In Server Components: Verify calls use `serverFetch('/api/v2/...')`.
- In Client Components: Verify calls use `apiClient.get('/api/v2/...')`.
