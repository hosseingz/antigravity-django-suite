/**
 * Server-Side Fetch Utility for React Server Components (RSC) and Server Actions
 *
 * Automatically forwards HttpOnly session and authentication cookies from the
 * incoming Next.js request context to the internal Django backend container.
 *
 * ALWAYS use this utility in React Server Components, Route Handlers, and Server Actions.
 * NEVER import `apiClient.ts` in server components.
 */

import { cookies } from 'next/headers';
import { getApiBaseUrl } from './apiConfig';

/**
 * Options extending native RequestInit with typed query params and Next.js revalidation.
 */
export interface ServerFetchOptions extends RequestInit {
  params?: Record<string, string | number | boolean | undefined | null>;
  revalidate?: number | false;
  tags?: string[];
}

/**
 * Structured error class thrown when server-side API requests return non-2xx statuses.
 */
export class ServerFetchError extends Error {
  public readonly status: number;
  public readonly statusText: string;
  public readonly data: unknown;

  constructor(status: number, statusText: string, data: unknown) {
    super(`ServerFetchError [HTTP ${status}]: ${statusText}`);
    this.name = 'ServerFetchError';
    this.status = status;
    this.statusText = statusText;
    this.data = data;
  }
}

/**
 * Authoritative server-side fetch wrapper.
 *
 * @template T Expected return data type.
 * @param endpoint Relative or absolute API route (e.g., '/api/v2/users/me/').
 * @param options Native fetch RequestInit configuration, query params, and caching directives.
 * @returns Parsed JSON or text payload.
 */
export async function serverFetch<T = unknown>(
  endpoint: string,
  options: ServerFetchOptions = {}
): Promise<T> {
  const { params, revalidate, tags, headers: customHeaders, ...fetchInit } = options;

  // Resolve target base URL (defaults to INTERNAL_API_BASE_URL on the server)
  let targetUrl: URL;
  if (endpoint.startsWith('http://') || endpoint.startsWith('https://')) {
    targetUrl = new URL(endpoint);
  } else {
    const baseUrl = getApiBaseUrl();
    const cleanBase = baseUrl.endsWith('/') ? baseUrl.slice(0, -1) : baseUrl;
    const cleanEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
    targetUrl = new URL(`${cleanBase}${cleanEndpoint}`);
  }

  // Append query parameters if provided
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        targetUrl.searchParams.append(key, String(value));
      }
    });
  }

  // Construct request headers and forward incoming cookies from Next.js request context
  const headers = new Headers(customHeaders);

  try {
    const cookieStore = await cookies();
    const cookieString = cookieStore.toString();
    if (cookieString && !headers.has('Cookie')) {
      headers.set('Cookie', cookieString);
    }
  } catch {
    // Gracefully handle contexts where cookies() is invoked outside active request lifecycle
  }

  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json');
  }

  if (fetchInit.body && typeof fetchInit.body === 'string' && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  // Configure Next.js caching directives
  const nextConfig: { revalidate?: number | false; tags?: string[] } = {};
  if (revalidate !== undefined) {
    nextConfig.revalidate = revalidate;
  }
  if (tags && tags.length > 0) {
    nextConfig.tags = tags;
  }

  const finalOptions: RequestInit & { next?: { revalidate?: number | false; tags?: string[] } } = {
    ...fetchInit,
    headers,
  };

  if (Object.keys(nextConfig).length > 0) {
    finalOptions.next = nextConfig;
  }

  const response = await fetch(targetUrl.toString(), finalOptions);

  if (!response.ok) {
    let errorData: unknown;
    try {
      errorData = await response.json();
    } catch {
      errorData = await response.text();
    }
    throw new ServerFetchError(response.status, response.statusText, errorData);
  }

  if (response.status === 204) {
    return null as T;
  }

  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    return (await response.json()) as T;
  }

  return (await response.text()) as unknown as T;
}

export default serverFetch;
