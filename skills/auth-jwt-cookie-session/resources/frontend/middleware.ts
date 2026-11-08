/**
 * Next.js Edge Middleware for Route Guarding & Non-Premature Session Eviction
 *
 * CRITICAL ARCHITECTURAL GUARDRAIL (Non-Premature Route Eviction):
 * - Protected routes MUST allow entry if EITHER `pod_access_token` OR `pod_refresh_token` is present.
 * - If `pod_access_token` has expired, the client browser still holds `pod_refresh_token`.
 *   Prematurely redirecting to `/auth/login` destroys UX and causes unneeded logouts.
 * - By passing requests through when `pod_refresh_token` exists, client-side hydration
 *   and `apiClient.ts` interceptors seamlessly execute background token refreshes.
 */

import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

const ACCESS_COOKIE_NAME = 'pod_access_token';
const REFRESH_COOKIE_NAME = 'pod_refresh_token';

// Routes requiring authentication
const PROTECTED_ROUTES = ['/dashboard', '/checkout', '/profile', '/settings'];

// Routes reserved for non-authenticated guests
const AUTH_ROUTES = ['/auth/login', '/auth/register', '/auth/otp'];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  const hasAccessToken = request.cookies.has(ACCESS_COOKIE_NAME);
  const hasRefreshToken = request.cookies.has(REFRESH_COOKIE_NAME);
  const hasSession = hasAccessToken || hasRefreshToken;

  const isProtectedRoute = PROTECTED_ROUTES.some((route) =>
    pathname.startsWith(route)
  );

  const isAuthRoute = AUTH_ROUTES.some((route) =>
    pathname.startsWith(route)
  );

  // 1. Guard Protected Routes
  if (isProtectedRoute) {
    if (!hasSession) {
      // Complete session absence: redirect to login with return destination
      const loginUrl = new URL('/auth/login', request.url);
      loginUrl.searchParams.set('next', pathname);
      return NextResponse.redirect(loginUrl);
    }

    // Has either valid access token OR refresh token: allow through for silent refresh
    return NextResponse.next();
  }

  // 2. Redirect Authenticated Users Away From Login/Register
  if (isAuthRoute) {
    if (hasSession) {
      // User is already logged in (or has active refresh token), redirect to dashboard
      const nextParam = request.nextUrl.searchParams.get('next');
      const destination = nextParam && nextParam.startsWith('/') ? nextParam : '/dashboard';
      return NextResponse.redirect(new URL(destination, request.url));
    }

    return NextResponse.next();
  }

  return NextResponse.next();
}

/**
 * Configure matching routes for Next.js Middleware.
 * Excludes static assets, image optimization, and favicon files.
 */
export const config = {
  matcher: [
    '/dashboard/:path*',
    '/checkout/:path*',
    '/profile/:path*',
    '/settings/:path*',
    '/auth/login',
    '/auth/register',
    '/auth/otp',
  ],
};
