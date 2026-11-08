/**
 * Zustand Shopping Cart Store with Monotonic Sequence Guards
 *
 * Provides reactive shopping cart state management for Next.js App Router.
 * Solves asynchronous race conditions (e.g., rapid '+' and '-' button clicking)
 * by enforcing module-level monotonic sequence checks (`lastRequestSeq`).
 *
 * Implements graceful offline fallback to localStorage snapshots on network failure.
 */

import { create } from 'zustand';
import { apiClient } from '@/lib/api/apiClient';
import { getOrCreateCartUUID, clearCartUUID } from '@/lib/cart/cartCookies';

/**
 * Standard cart item structure returned by DRF backend.
 */
export interface CartItem {
  product_id: number;
  quantity: number;
  title: string;
  unit_price: string;
  total_price: string;
  image_url: string | null;
  in_stock: boolean;
  metadata?: Record<string, unknown>;
}

/**
 * Serialized cart summary payload.
 */
export interface CartSummary {
  items: CartItem[];
  item_count: number;
  subtotal: string;
  currency: string;
}

/**
 * Shape of the Cart API response.
 */
interface CartApiResponse {
  success: boolean;
  message?: string;
  cart: CartSummary;
  error?: string;
}

/**
 * State and action interface for the Zustand cart store.
 */
export interface CartState {
  items: CartItem[];
  itemCount: number;
  subtotal: string;
  currency: string;
  isLoading: boolean;
  isOffline: boolean;
  error: string | null;

  // Actions
  fetchCart: () => Promise<void>;
  addToCart: (productId: number, quantity?: number, metadata?: Record<string, unknown>) => Promise<void>;
  updateQuantity: (productId: number, quantity: number) => Promise<void>;
  removeFromCart: (productId: number) => Promise<void>;
  clearCart: () => Promise<void>;
  mergeGuestCart: () => Promise<void>;
  resetCart: () => void;
}

// ----------------------------------------------------------------------------
// Monotonic Sequence Guard State
// ----------------------------------------------------------------------------
// Module-level monotonic counter tracking dispatched mutation requests.
// Prevents slow out-of-order network responses from reverting fast recent user actions.
let lastRequestSeq = 0;

// LocalStorage caching constants
const CART_STORAGE_KEY = 'pod_cart_snapshot_v1';

function saveCartToStorage(summary: CartSummary): void {
  if (typeof window === 'undefined') return;
  try {
    localStorage.setItem(CART_STORAGE_KEY, JSON.stringify(summary));
  } catch {
    // Ignore storage quota warnings
  }
}

function loadCartFromStorage(): CartSummary | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = localStorage.getItem(CART_STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

/**
 * Authoritative Zustand Cart Store Hook.
 */
export const useCartStore = create<CartState>((set, get) => ({
  items: [],
  itemCount: 0,
  subtotal: '0.00',
  currency: 'USD',
  isLoading: false,
  isOffline: false,
  error: null,

  fetchCart: async () => {
    const currentSeq = ++lastRequestSeq;
    set({ isLoading: true, error: null });

    try {
      const guestUUID = getOrCreateCartUUID();
      const response = await apiClient.get<CartApiResponse>('/api/v2/cart/', {
        withCredentials: true,
        headers: {
          'X-CART-UUID': guestUUID,
          Accept: 'application/json',
        },
      });

      // MONOTONIC SEQUENCE GUARD:
      // If a newer mutation dispatched while this request was inflight, discard this stale result.
      if (currentSeq !== lastRequestSeq) {
        return;
      }

      const cart = response.data.cart;
      set({
        items: cart.items,
        itemCount: cart.item_count,
        subtotal: cart.subtotal,
        currency: cart.currency,
        isLoading: false,
        isOffline: false,
        error: null,
      });

      saveCartToStorage(cart);
    } catch (err: unknown) {
      if (currentSeq !== lastRequestSeq) {
        return;
      }

      // Offline Fallback: Recover from localStorage snapshot
      const cached = loadCartFromStorage();
      if (cached) {
        set({
          items: cached.items,
          itemCount: cached.item_count,
          subtotal: cached.subtotal,
          currency: cached.currency,
          isLoading: false,
          isOffline: true,
          error: 'Offline mode: displaying cached cart.',
        });
      } else {
        set({
          isLoading: false,
          isOffline: true,
          error: 'Failed to fetch cart. Please check your network connection.',
        });
      }
    }
  },

  addToCart: async (productId: number, quantity: number = 1, metadata?: Record<string, unknown>) => {
    const currentSeq = ++lastRequestSeq;
    set({ isLoading: true, error: null });

    try {
      const guestUUID = getOrCreateCartUUID();
      const response = await apiClient.post<CartApiResponse>(
        '/api/v2/cart/',
        {
          product_id: productId,
          quantity,
          metadata,
        },
        {
          withCredentials: true,
          headers: {
            'X-CART-UUID': guestUUID,
            'Content-Type': 'application/json',
            Accept: 'application/json',
          },
        }
      );

      // Guard check
      if (currentSeq !== lastRequestSeq) {
        return;
      }

      const cart = response.data.cart;
      set({
        items: cart.items,
        itemCount: cart.item_count,
        subtotal: cart.subtotal,
        currency: cart.currency,
        isLoading: false,
        isOffline: false,
        error: null,
      });

      saveCartToStorage(cart);
    } catch (err: any) {
      if (currentSeq !== lastRequestSeq) {
        return;
      }

      const errorMsg =
        err.response?.data?.error ||
        err.response?.data?.detail ||
        'Unable to add item to cart. Please try again.';

      set({
        isLoading: false,
        error: errorMsg,
      });
    }
  },

  updateQuantity: async (productId: number, quantity: number) => {
    const currentSeq = ++lastRequestSeq;
    set({ isLoading: true, error: null });

    try {
      const guestUUID = getOrCreateCartUUID();
      const response = await apiClient.patch<CartApiResponse>(
        '/api/v2/cart/',
        {
          product_id: productId,
          quantity,
        },
        {
          withCredentials: true,
          headers: {
            'X-CART-UUID': guestUUID,
            'Content-Type': 'application/json',
            Accept: 'application/json',
          },
        }
      );

      // Guard check
      if (currentSeq !== lastRequestSeq) {
        return;
      }

      const cart = response.data.cart;
      set({
        items: cart.items,
        itemCount: cart.item_count,
        subtotal: cart.subtotal,
        currency: cart.currency,
        isLoading: false,
        isOffline: false,
        error: null,
      });

      saveCartToStorage(cart);
    } catch (err: any) {
      if (currentSeq !== lastRequestSeq) {
        return;
      }

      const errorMsg =
        err.response?.data?.error ||
        err.response?.data?.detail ||
        'Failed to update item quantity.';

      set({
        isLoading: false,
        error: errorMsg,
      });
    }
  },

  removeFromCart: async (productId: number) => {
    const currentSeq = ++lastRequestSeq;
    set({ isLoading: true, error: null });

    try {
      const guestUUID = getOrCreateCartUUID();
      const response = await apiClient.delete<CartApiResponse>('/api/v2/cart/', {
        withCredentials: true,
        headers: {
          'X-CART-UUID': guestUUID,
          Accept: 'application/json',
        },
        params: {
          product_id: productId,
        },
      });

      // Guard check
      if (currentSeq !== lastRequestSeq) {
        return;
      }

      const cart = response.data.cart;
      set({
        items: cart.items,
        itemCount: cart.item_count,
        subtotal: cart.subtotal,
        currency: cart.currency,
        isLoading: false,
        isOffline: false,
        error: null,
      });

      saveCartToStorage(cart);
    } catch (err: any) {
      if (currentSeq !== lastRequestSeq) {
        return;
      }

      set({
        isLoading: false,
        error: 'Failed to remove item from cart.',
      });
    }
  },

  clearCart: async () => {
    const currentSeq = ++lastRequestSeq;
    set({ isLoading: true, error: null });

    try {
      const guestUUID = getOrCreateCartUUID();
      const response = await apiClient.delete<CartApiResponse>('/api/v2/cart/', {
        withCredentials: true,
        headers: {
          'X-CART-UUID': guestUUID,
          Accept: 'application/json',
        },
      });

      // Guard check
      if (currentSeq !== lastRequestSeq) {
        return;
      }

      const emptySummary: CartSummary = {
        items: [],
        item_count: 0,
        subtotal: '0.00',
        currency: 'USD',
      };

      set({
        items: [],
        itemCount: 0,
        subtotal: '0.00',
        isLoading: false,
        isOffline: false,
        error: null,
      });

      saveCartToStorage(emptySummary);
    } catch (err: any) {
      if (currentSeq !== lastRequestSeq) {
        return;
      }

      set({
        isLoading: false,
        error: 'Failed to clear cart.',
      });
    }
  },

  mergeGuestCart: async () => {
    const currentSeq = ++lastRequestSeq;
    set({ isLoading: true, error: null });

    try {
      const guestUUID = getOrCreateCartUUID();
      const response = await apiClient.get<CartApiResponse>('/api/v2/cart/', {
        withCredentials: true,
        headers: {
          'X-CART-UUID': guestUUID,
          Accept: 'application/json',
        },
      });

      if (currentSeq !== lastRequestSeq) {
        return;
      }

      // Guest cart merged on server; clear local guest UUID
      clearCartUUID();

      const cart = response.data.cart;
      set({
        items: cart.items,
        itemCount: cart.item_count,
        subtotal: cart.subtotal,
        currency: cart.currency,
        isLoading: false,
        isOffline: false,
        error: null,
      });

      saveCartToStorage(cart);
    } catch (err: any) {
      if (currentSeq !== lastRequestSeq) {
        return;
      }

      set({
        isLoading: false,
        error: 'Failed to synchronize merged cart.',
      });
    }
  },

  resetCart: () => {
    set({
      items: [],
      itemCount: 0,
      subtotal: '0.00',
      currency: 'USD',
      isLoading: false,
      isOffline: false,
      error: null,
    });
  },
}));

export default useCartStore;
