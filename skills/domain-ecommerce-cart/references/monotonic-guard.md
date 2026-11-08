# Asynchronous Race Conditions & Monotonic Sequence Guards

This reference provides a deep technical analysis of client-side race conditions in high-frequency user interfaces (such as e-commerce shopping carts) and details the implementation mechanics of the Monotonic Sequence Guard pattern in state management libraries like Zustand.

---

## 1. Anatomy of an Asynchronous Race Condition

In interactive web applications, users frequently perform rapid, sequential actions:
- Clicking the `+` quantity button multiple times in under a second.
- Toggling between `+` and `-` while exploring pricing.
- Rapidly adding different items to a cart from a product grid.

### 1.1 The Out-of-Order Execution Timeline

Consider a user who has 1 item in their cart and clicks `+` twice in rapid succession:

```
User Action:           Click (+) at t=0ms                Click (+) at t=100ms
                         │                                 │
Network Dispatch:        ▼ Request 1 (Qty -> 2)           ▼ Request 2 (Qty -> 3)
                         │                                 │
                         │ (Slow Network Route: 450ms)     │ (Fast Network Route: 150ms)
                         │                                 ▼
                         │                         Request 2 Resolves (t=250ms)
                         │                         State updated: Qty = 3  [CORRECT]
                         ▼                                 │
                 Request 1 Resolves (t=450ms)              │
                 State updated: Qty = 2  [STALE REVERT]    │
                         │                                 │
                         ▼                                 ▼
Final Visual UI State:   Cart displays Qty: 2  <-- BUG: Stale response overwrote newer action!
```

### 1.2 Why Common Mitigation Strategies Fail
1. **Button Disabling / Spinners**:
   - Disabling buttons on click introduces artificial friction. Users expect immediate responsiveness; latency spikes freeze the UI and make the application feel unresponsive.
2. **Debouncing / Throttling**:
   - Debouncing delays network dispatch (e.g., waiting 300ms after the last click). While it reduces request volume, it degrades perceived responsiveness and does not solve network packet reordering when separate requests are actually dispatched.
3. **Promise Cancellation (AbortController)**:
   - Aborting previous requests on the client aborts the *client's receipt* of the response, but the server has already processed the mutation (e.g., Redis `HSET` executed). The client state then drifts out of sync with the backend.

---

## 2. The Monotonic Sequence Guard Pattern

The Monotonic Sequence Guard resolves this problem deterministically without blocking user interactions or aborting in-flight server mutations.

### 2.1 Theoretical Foundation
A monotonic sequence is an ordered set where each term is strictly greater than or equal to its predecessor ($S_{n+1} > S_n$). By maintaining a module-level monotonic counter in JavaScript, every dispatched request receives an immutable sequence ticket.

### 2.2 Sequence Diagram

```
Zustand Store Context
lastRequestSeq = 0

Mutation 1 Dispatched:
  const currentSeq = ++lastRequestSeq  // currentSeq = 1, lastRequestSeq = 1
  fetch('/api/v2/cart/', { ... })

Mutation 2 Dispatched (50ms later):
  const currentSeq = ++lastRequestSeq  // currentSeq = 2, lastRequestSeq = 2
  fetch('/api/v2/cart/', { ... })

Resolution 2 Arrives (at t=180ms):
  Is currentSeq (2) === lastRequestSeq (2)? -> TRUE
  Apply state: Qty = 3. Update localStorage cache.

Resolution 1 Arrives (at t=420ms):
  Is currentSeq (1) === lastRequestSeq (2)? -> FALSE
  STALE RESPONSE DETECTED: Immediately discard payload without touching store state!
```

### 2.3 Concrete Implementation in Zustand
```typescript
// Module-level monotonic counter (persists across re-renders outside component closures)
let lastRequestSeq = 0;

export const useCartStore = create<CartState>((set, get) => ({
  updateQuantity: async (productId: number, quantity: number) => {
    // 1. Increment and capture the local sequence ticket
    const currentSeq = ++lastRequestSeq;
    set({ isLoading: true, error: null });

    try {
      const response = await apiClient.patch('/api/v2/cart/', {
        product_id: productId,
        quantity,
      });

      // 2. MONOTONIC GUARD:
      // If a newer request was dispatched while this was in flight, discard this response.
      if (currentSeq !== lastRequestSeq) {
        return;
      }

      // 3. Safe State Application
      set({
        items: response.data.cart.items,
        itemCount: response.data.cart.item_count,
        subtotal: response.data.cart.subtotal,
        isLoading: false,
      });
    } catch (err) {
      if (currentSeq !== lastRequestSeq) return;
      set({ isLoading: false, error: 'Failed to update cart.' });
    }
  },
}));
```

---

## 3. Next.js App Router Cache Invalidation Rules

When querying cart data in Next.js App Router (via React Server Components or Client Components), strict cache invalidation must be enforced to prevent serving stale or cross-contaminated user carts.

### 3.1 Server Fetching Cache Directives
Cart data represents mutable user state and must **never** be cached in Next.js Data Cache or Full Route Cache:

```typescript
// RSC Cart Fetching: Explicit cache bypass
const response = await fetch(`${process.env.INTERNAL_API_BASE_URL}/api/v2/cart/`, {
  cache: 'no-store', // CRITICAL: Guarantees fresh read on every request
  headers: {
    'Cookie': cookieStore.toString(),
    'X-CART-UUID': guestUUID,
  },
});
```

### 3.2 HTTP Response Header Requirements
The Django backend must explicitly mark all cart responses with non-cacheable headers and include `Vary` directives to prevent edge proxies (Nginx, Cloudflare) from caching private cart payloads:

```python
# Required Backend Response Headers:
response['Cache-Control'] = 'no-cache, no-store, must-revalidate, private'
response['Pragma'] = 'no-cache'
response['Expires'] = '0'
response['Vary'] = 'Cookie, X-CART-UUID, Authorization'
```

- **`no-store, private`**: Prevents intermediate proxies and shared caches from persisting the payload.
- **`Vary: Cookie, X-CART-UUID`**: Tells compliant caches that responses differ based on the visitor's authentication cookies and guest cart identifier.
