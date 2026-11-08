# Dual-Environment Networking: SSR vs. CSR Routing

This reference details the architectural rationale, network topologies, and runtime boundary mechanisms separating Server-Side Rendering (SSR) from Client-Side Rendering (CSR) when integrating Next.js App Router with a containerized Django REST Framework backend.

---

## 1. Network Topology & Execution Realities

In a modern containerized production or development topology, Next.js executes in two fundamentally different physical environments:

```
[ User Browser ]
       │
       │ Public Traffic: NEXT_PUBLIC_API_BASE_URL (http://localhost:8080 or https://api.site.com)
       ▼
┌────────────────────────────────────────────────────────┐
│ Nginx Reverse Proxy (:8080 / :443)                     │
└──────────────┬──────────────────────────┬──────────────┘
               │                          │
               ▼                          ▼
┌─────────────────────────────┐ ┌─────────────────────────────┐
│ Next.js Frontend Container  │ │ Django Backend Container    │
│ (Node.js App Router Server) │ │ (Gunicorn WSGI / ASGI)      │
│ service: "frontend"         │ │ service: "backend"          │
│ port: :3000                 │ │ port: :8000                 │
└──────────────┬──────────────┘ └─────────────────────────────┘
               │                                ▲
               │ Private Internal Network       │
               │ INTERNAL_API_BASE_URL          │
               │ (http://backend:8000)          │
               └────────────────────────────────┘
```

### 1.1 The Two Execution Boundaries

| Metric | Server-Side Execution (SSR / RSC) | Client-Side Execution (CSR / Browser) |
| :--- | :--- | :--- |
| **Runtime Engine** | Node.js / V8 Server Runtime | Web Browser JavaScript Engine |
| **Physical Location** | Inside Docker container (`frontend`) | Outside Docker on end-user machine |
| **Network Context** | Docker internal bridge (`internal_net`) | Public Internet / Localhost interface |
| **API Base URL** | `INTERNAL_API_BASE_URL` (`http://backend:8000`) | `NEXT_PUBLIC_API_BASE_URL` (`http://localhost:8080`) |
| **DNS Resolver** | Embedded Docker DNS (`127.0.0.11`) | Local OS / ISP Public DNS |
| **Credential Storage**| Incoming Request Cookies (`next/headers`) | Browser Cookie Jar (`document.cookie`) |
| **Transport Utility** | `serverFetch.ts` (native Fetch API) | `apiClient.ts` (Axios with Mutex) |

---

## 2. Docker Network Loopback & Hairpinning Failures

### 2.1 The Container Loopback Trap
When developers attempt to use a single base URL like `http://localhost:8080` or `http://127.0.0.1:8080` universally across both server and client:
1. **In the Browser**: `localhost:8080` correctly resolves to the host machine's port mapped to Nginx.
2. **Inside the Next.js Container (SSR)**: `localhost` resolves to the container's own internal loopback interface (`127.0.0.1`), where no reverse proxy or backend is listening. The request fails immediately with `ECONNREFUSED 127.0.0.1:8080`.

### 2.2 NAT Loopback (Hairpinning) Failure
When using public domain names (e.g., `https://api.example.com`):
1. A Server Component rendering on the `frontend` container initiates an HTTP request to `https://api.example.com`.
2. The packet leaves the container, traverses the gateway, and attempts to route back into the same public IP address.
3. Many cloud routers, firewall appliances, and Docker bridge configurations disallow NAT loopback (hairpinning), leading to dropped packets, `ETIMEDOUT`, or severe latency penalties.
4. Routing directly across the Docker bridge via `http://backend:8000` bypasses public TLS termination overhead, avoids firewall hairpinning, and achieves single-digit microsecond latency.

---

## 3. Dynamic Runtime Evaluation vs. Build-Time Inlining

Next.js statically compiles and bundles client and server code during `next build`. Environment variables prefixed with `NEXT_PUBLIC_` are statically replaced into code strings at build time.

### 3.1 The Static Evaluation Anti-Pattern
Consider this naive implementation:
```typescript
// ANTI-PATTERN: Evaluated once at bundle creation
const API_BASE_URL = typeof window === 'undefined'
  ? process.env.INTERNAL_API_BASE_URL
  : process.env.NEXT_PUBLIC_API_BASE_URL;

export const ENDPOINT = `${API_BASE_URL}/api/v2/auth/login/`;
```
**Why this fails:**
1. During `next build`, `typeof window === 'undefined'` evaluates to `true` (the build runs in Node.js).
2. `API_BASE_URL` evaluates to `http://backend:8000`.
3. Next.js inlines this string literal into shared modules.
4. When loaded in the user's browser, `ENDPOINT` points to `http://backend:8000`.
5. Because `backend` is a private Docker hostname unrecognizable by public DNS, every client request fails with `ERR_NAME_NOT_RESOLVED`.

### 3.2 The Dynamic Getter Solution
To prevent build-time inlining, `apiConfig.ts` employs dynamic property getters:
```typescript
// CORRECT: Evaluated on every access at request runtime
export function getApiBaseUrl(): string {
  if (typeof window === 'undefined') {
    return process.env.INTERNAL_API_BASE_URL || 'http://backend:8000';
  }
  return process.env.NEXT_PUBLIC_API_BASE_URL || '';
}

export const API_ENDPOINTS = {
  auth: {
    get login(): string {
      return `${getApiBaseUrl()}/api/v2/auth/login/`;
    },
  },
};
```
When `API_ENDPOINTS.auth.login` is accessed:
- On the server during RSC execution: returns `http://backend:8000/api/v2/auth/login/`.
- In the client browser: returns `http://localhost:8080/api/v2/auth/login/` (or relative path `/api/v2/auth/login/`).

---

## 4. Security & Isolation Boundaries

1. **Information Leakage Prevention**:
   Internal service hostnames (`http://backend:8000`, database credentials, Docker networks) must never leak into client JavaScript bundles. Keeping `INTERNAL_API_BASE_URL` devoid of `NEXT_PUBLIC_` ensures Next.js webpack/turbopack never injects it into client bundles.

2. **Cookie Forwarding Isolation**:
   - Client requests automatically send cookies via the browser networking layer (`withCredentials: true`).
   - Server requests (RSC) have no default cookie storage. `serverFetch.ts` explicitly extracts incoming cookies via `cookies()` from `next/headers` and attaches the `Cookie` header when querying `INTERNAL_API_BASE_URL`.
