/**
 * API Configuration & Dynamic Endpoint Resolver
 *
 * Provides runtime-aware base URL resolution and dynamically evaluated
 * API endpoint definitions. Prevents leaking internal Docker network names
 * to client-side bundles while avoiding NAT loopback failures during SSR.
 */

/**
 * Resolves the appropriate API base URL based on the current execution runtime.
 *
 * - Server-side (Node.js / RSC): Uses INTERNAL_API_BASE_URL (defaults to Docker network bridge 'http://backend:8000')
 * - Client-side (Browser): Uses NEXT_PUBLIC_API_BASE_URL (defaults to public edge gateway or relative '')
 */
export function getApiBaseUrl(): string {
  if (typeof window === 'undefined') {
    // Server-Side Execution (RSC, SSR, Route Handlers)
    return process.env.INTERNAL_API_BASE_URL || 'http://backend:8000';
  }

  // Client-Side Execution (Browser CSR)
  return process.env.NEXT_PUBLIC_API_BASE_URL || '';
}

/**
 * Authoritative API Endpoint Registry.
 *
 * Utilizes JavaScript property getters to guarantee dynamic, request-time
 * resolution of getApiBaseUrl(). NEVER evaluate these endpoints at build-time.
 */
export const API_ENDPOINTS = {
  auth: {
    get register(): string {
      return `${getApiBaseUrl()}/api/v2/auth/register/`;
    },
    get login(): string {
      return `${getApiBaseUrl()}/api/v2/auth/login/`;
    },
    get logout(): string {
      return `${getApiBaseUrl()}/api/v2/auth/logout/`;
    },
    get tokenRefresh(): string {
      return `${getApiBaseUrl()}/api/v2/auth/token/refresh/`;
    },
    get sendOtp(): string {
      return `${getApiBaseUrl()}/api/v2/auth/otp/send/`;
    },
    get verifyOtp(): string {
      return `${getApiBaseUrl()}/api/v2/auth/otp/verify/`;
    },
    get resetPassword(): string {
      return `${getApiBaseUrl()}/api/v2/auth/password/reset/`;
    },
  },
  profile: {
    get me(): string {
      return `${getApiBaseUrl()}/api/v2/auth/profile/`;
    },
  },
  health: {
    get check(): string {
      return `${getApiBaseUrl()}/api/health/`;
    },
  },
} as const;
