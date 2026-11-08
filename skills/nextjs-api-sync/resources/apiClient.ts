/**
 * Client-Side Axios Instance with Mutex Token Refresh & CSRF Handling
 *
 * CRITICAL BOUNDARY WARNING:
 * This module references browser globals (`document.cookie`, `window`).
 * It MUST NEVER be imported into React Server Components (RSC) or Server Actions.
 * For server-side contexts, use `serverFetch.ts`.
 */

import axios, {
  AxiosError,
  AxiosInstance,
  AxiosResponse,
  InternalAxiosRequestConfig,
} from 'axios';
import { API_ENDPOINTS, getApiBaseUrl } from './apiConfig';

/**
 * Extended Axios request configuration supporting retry state tracking.
 */
export interface CustomAxiosRequestConfig extends InternalAxiosRequestConfig {
  _retry?: boolean;
}

/**
 * Queued request item structure waiting for token refresh resolution.
 */
interface FailedRequestQueueItem {
  resolve: (value?: unknown) => void;
  reject: (reason?: unknown) => void;
}

// Single-refresh mutex state
let isRefreshing = false;
let failedQueue: FailedRequestQueueItem[] = [];

/**
 * Flushes the queue of pending requests following a refresh attempt.
 */
function processQueue(error: unknown = null): void {
  failedQueue.forEach((promise) => {
    if (error) {
      promise.reject(error);
    } else {
      promise.resolve();
    }
  });
  failedQueue = [];
}

/**
 * Safely extracts the Django CSRF token (`csrftoken`) from browser cookies.
 */
export function getCsrfToken(): string | null {
  if (typeof document === 'undefined') {
    return null;
  }
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

/**
 * Authoritative client-side Axios instance.
 * Configured with credentials enabled to permit secure HTTP-only cookies.
 */
export const apiClient: AxiosInstance = axios.create({
  baseURL: getApiBaseUrl(),
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
    Accept: 'application/json',
  },
  timeout: 30000,
});

/**
 * Request Interceptor:
 * Attaches the Django `X-CSRFToken` header to mutating HTTP requests (POST, PUT, PATCH, DELETE).
 */
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const customConfig = config as CustomAxiosRequestConfig;
    const method = customConfig.method?.toUpperCase();

    // Attach CSRF token on mutating requests if present in cookies
    if (method && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
      const csrfToken = getCsrfToken();
      if (csrfToken && !customConfig.headers['X-CSRFToken']) {
        customConfig.headers['X-CSRFToken'] = csrfToken;
      }
    }

    return customConfig;
  },
  (error: unknown) => Promise.reject(error)
);

/**
 * Response Interceptor:
 * Intercepts 401 Unauthorized responses to perform a single-refresh mutex lock.
 * Parallel requests failing with 401 are queued until the refresh token call completes.
 */
apiClient.interceptors.response.use(
  (response: AxiosResponse) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as CustomAxiosRequestConfig | undefined;

    if (!originalRequest) {
      return Promise.reject(error);
    }

    const requestUrl = originalRequest.url || '';

    // Loop Protection: Never retry authentication endpoints that inherently trigger 401s
    const isAuthBypassUrl =
      requestUrl.includes('/token/refresh') ||
      requestUrl.includes('/login') ||
      requestUrl.includes('/logout');

    if (error.response?.status === 401 && !originalRequest._retry && !isAuthBypassUrl) {
      if (isRefreshing) {
        // Enqueue parallel 401 requests while refresh is in flight
        return new Promise<void>((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        })
          .then(() => apiClient(originalRequest))
          .catch((queuedErr) => Promise.reject(queuedErr));
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        // DRF endpoint reads HttpOnly refresh token cookie and issues fresh tokens
        await axios.post(
          API_ENDPOINTS.auth.tokenRefresh,
          {},
          {
            withCredentials: true,
            headers: {
              'Content-Type': 'application/json',
              Accept: 'application/json',
            },
          }
        );

        // Drain the pending queue upon successful refresh
        processQueue(null);

        // Replay the original failed request
        return apiClient(originalRequest);
      } catch (refreshError) {
        // Reject all queued requests if refresh fails
        processQueue(refreshError);

        // Cleanly notify application of session eviction
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('auth:session-expired'));
        }

        return Promise.reject(refreshError);
      } finally {
        isRefreshing = false;
      }
    }

    return Promise.reject(error);
  }
);

export default apiClient;
