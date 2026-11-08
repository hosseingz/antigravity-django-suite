/**
 * Zustand Authentication & Identity State Store
 *
 * CRITICAL SECURITY ENFORCEMENT:
 * - NO JWTs OR SENSITIVE CREDENTIALS IN LOCALSTORAGE!
 * - Raw JWTs remain strictly encapsulated inside HttpOnly cookies (`pod_access_token`, `pod_refresh_token`).
 * - Only safe, non-sensitive user profile metadata (ID, email, name, role) may be persisted
 *   in `localStorage` to eliminate flash-of-unauthenticated-state (FOUC) during initial render.
 * - Listens for 'auth:session-expired' window event dispatched by `apiClient.ts` on refresh failure.
 */

import { create } from 'zustand';
import { apiClient } from '@/lib/api/apiClient';
import { API_ENDPOINTS } from '@/lib/api/apiConfig';

export interface UserProfile {
  id: number | string;
  email: string;
  username?: string;
  first_name?: string;
  last_name?: string;
  is_active?: boolean;
}

interface AuthState {
  user: UserProfile | null;
  isAuthenticated: boolean;
  isLoading: boolean;

  /**
   * Sets active user state and caches non-sensitive profile metadata.
   */
  setAuth: (user: UserProfile) => void;

  /**
   * Clears in-memory auth state and eliminates cached profile metadata.
   */
  clearAuth: () => void;

  /**
   * Hydrates state from cached profile metadata and verifies session integrity with DRF.
   */
  hydrateAuth: () => Promise<void>;

  /**
   * Executes remote DRF cookie-clearing logout and clears client state.
   */
  logout: () => Promise<void>;
}

const PROFILE_STORAGE_KEY = 'pod_user_metadata';

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true,

  setAuth: (user: UserProfile) => {
    if (typeof window !== 'undefined') {
      try {
        localStorage.setItem(PROFILE_STORAGE_KEY, JSON.stringify(user));
      } catch (err) {
        console.warn('Failed to cache user metadata to localStorage', err);
      }
    }
    set({ user, isAuthenticated: true, isLoading: false });
  },

  clearAuth: () => {
    if (typeof window !== 'undefined') {
      try {
        localStorage.removeItem(PROFILE_STORAGE_KEY);
      } catch (err) {
        console.warn('Failed to remove user metadata from localStorage', err);
      }
    }
    set({ user: null, isAuthenticated: false, isLoading: false });
  },

  hydrateAuth: async () => {
    set({ isLoading: true });

    // Step 1: Optimistic fast hydration from non-sensitive local metadata
    if (typeof window !== 'undefined') {
      try {
        const cached = localStorage.getItem(PROFILE_STORAGE_KEY);
        if (cached) {
          const parsedUser = JSON.parse(cached) as UserProfile;
          set({ user: parsedUser, isAuthenticated: true });
        }
      } catch (err) {
        console.warn('Failed to parse cached user metadata', err);
      }
    }

    // Step 2: Validate live session against Django backend
    try {
      // Endpoint handled by apiClient (auto-handles 401 & single-refresh mutex)
      const response = await apiClient.get<UserProfile>(API_ENDPOINTS.profile.me);
      get().setAuth(response.data);
    } catch (error) {
      // If profile fetch fails completely (e.g. 401 or refresh expired), clear stale state
      get().clearAuth();
    } finally {
      set({ isLoading: false });
    }
  },

  logout: async () => {
    set({ isLoading: true });
    try {
      await apiClient.post(API_ENDPOINTS.auth.logout);
    } catch (err) {
      console.warn('Backend logout encountered error; proceeding with local eviction', err);
    } finally {
      get().clearAuth();
      if (typeof window !== 'undefined') {
        window.location.href = '/auth/login';
      }
    }
  },
}));

// Global listener for session termination dispatched by `apiClient.ts`
if (typeof window !== 'undefined') {
  window.addEventListener('auth:session-expired', () => {
    useAuthStore.getState().clearAuth();
    window.location.href = '/auth/login?expired=true';
  });
}
