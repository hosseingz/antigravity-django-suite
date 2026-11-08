---
name: domain-ecommerce-cart
description: Optional ecommerce extension managing Redis-backed shopping carts, client-side guest UUID tracking (X-CART-UUID), atomic guest-to-user cart merging, and Zustand monotonic sequence guards.
---

# Domain Module: High-Concurrency Redis Shopping Cart

This skill provides an optional, decoupled e-commerce shopping cart extension for applications built with `antigravity-django-suite`. It implements high-concurrency cart state management in Redis Hashes, transparent guest session tracking via client-generated `X-CART-UUID` tokens, atomic guest-to-user cart merging upon login, and the Monotonic Sequence Guard pattern in Zustand to eliminate UI race conditions.

---

## 1. Architectural Layout & Cart Lifecycle

```
[ Anonymous Guest Shopping ]                     [ User Signs In / Registers ]
            │                                                  │
            ▼                                                  ▼
1. Browser creates / loads                       2. User authenticates via JWT
   `cart_guest_uuid`                                (`pod_access_token` cookie)
            │                                                  │
            ▼                                                  ▼
3. Guest adds items:                             3. Browser sends request with:
   POST /api/v2/cart/                               - Cookie: pod_access_token
   Header: X-CART-UUID: <uuid>                      - Header: X-CART-UUID: <uuid>
            │                                                  │
            ▼                                                  ▼
┌───────────────────────────────┐                ┌───────────────────────────────┐
│ Redis Hash:                   │                │ Redis Cart Merge Engine:      │
│ key: `cart:guest:<uuid>`      │                │ `merge_guest_cart_if_needed`  │
│ fields: product_id -> payload │                └───────────────┬───────────────┘
└───────────────────────────────┘                                │
                                                                 │ 4. Read guest items
                                                                 │ 5. Pipeline merge into user cart
                                                                 │ 6. Delete `cart:guest:<uuid>`
                                                                 ▼
                                                 ┌───────────────────────────────┐
                                                 │ Redis Hash:                   │
                                                 │ key: `cart:user:<user_id>`    │
                                                 │ fields: product_id -> payload │
                                                 └───────────────────────────────┘
```

### 1.1 Key Data Structures in Redis
- **Guest Cart Key**: `cart:guest:<uuid>` (TTL: 30 days)
- **User Cart Key**: `cart:user:<user_id>` (TTL: 90 days)
- **Hash Fields**: `<product_id>` (stringified integer)
- **Hash Values**: JSON serialized payload:
  ```json
  {
    "product_id": 42,
    "quantity": 3,
    "added_at": "2026-11-08T10:00:00Z",
    "metadata": {}
  }
  ```

---

## 2. Decoupled Modular Integration

This module is designed as an optional domain extension. It does **not** bloat core Django or Next.js configurations if an application does not require e-commerce features.

### 2.1 When to Add This Module
- When building store, marketplace, or booking domains requiring high-throughput cart modifications.
- When users must be permitted to add items to a cart prior to authenticating or registering.
- When rapid button clicking (`+`, `-`) causes UI flickering and out-of-order state overwrites in standard React hooks.

### 2.2 Scaffolding Procedure

#### Step 1: Backend Deployment
1. Verify Redis is accessible via `django-redis` or `REDIS_URL` in `config/settings.py`.
2. Create domain application inside `apps/cart/`:
   ```bash
   python manage.py startapp cart apps/cart
   ```
3. Deploy templates:
   - Copy [`resources/backend/redis_cart.py`](./resources/backend/redis_cart.py) -> `backend/apps/cart/redis_cart.py`
   - Copy [`resources/backend/views_cart.py`](./resources/backend/views_cart.py) -> `backend/apps/cart/views.py`
4. Register routing in `backend/apps/cart/urls.py`:
   ```python
   from django.urls import path
   from .views import CartAPIView

   urlpatterns = [
       path("cart/", CartAPIView.as_view(), name="cart_api"),
   ]
   ```
5. Mount in `backend/config/urls.py` under the API v2 namespace:
   ```python
   path("api/v2/", include("cart.urls")),
   ```

#### Step 2: Frontend Deployment
1. Install Zustand in the Next.js application:
   ```bash
   npm install zustand
   ```
2. Deploy templates:
   - Copy [`resources/frontend/cartCookies.ts`](./resources/frontend/cartCookies.ts) -> `frontend/src/lib/cart/cartCookies.ts`
   - Copy [`resources/frontend/useCartStore.ts`](./resources/frontend/useCartStore.ts) -> `frontend/src/lib/cart/useCartStore.ts`
3. Consume the reactive store in components:
   ```tsx
   'use client';
   import { useCartStore } from '@/lib/cart/useCartStore';

   export function AddToCartButton({ productId }: { productId: number }) {
     const addToCart = useCartStore((s) => s.addToCart);
     const isLoading = useCartStore((s) => s.isLoading);

     return (
       <button onClick={() => addToCart(productId, 1)} disabled={isLoading}>
         Add to Cart
       </button>
     );
   }
   ```

---

## 3. AI Guardrails & Architectural Anti-Patterns

- **Anti-Pattern 1: Asynchronous UI State Overwrites**
  - *Rule*: Never mutate shopping cart store state without Monotonic Sequence Guards.
  - *Risk*: A slow previous network response (e.g. from a prior `+` click) arriving after a faster subsequent response will revert user state to stale numbers.
  - *Solution*: Maintain module-level sequence ticket counter (`lastRequestSeq`). Discard any response where `currentSeq !== lastRequestSeq`. Consult [`references/monotonic-guard.md`](./references/monotonic-guard.md).

- **Anti-Pattern 2: Unsafe Redis Byte Handling**
  - *Rule*: Always execute byte-safe decoding (`field.decode('utf-8')` if isinstance(field, bytes)) when retrieving Redis hash keys or values.
  - *Risk*: Raw byte strings trigger JSON serialization crashes or string formatting errors in Python 3.
  - *Solution*: Use the safe parsing pipeline built into [`resources/backend/redis_cart.py`](./resources/backend/redis_cart.py).

- **Anti-Pattern 3: Caching Cart Endpoints in Edge Proxies or Next.js**
  - *Rule*: Never permit intermediate proxies or Next.js Server Components to cache `/api/v2/cart/`.
  - *Risk*: Leaks private cart information across visitors and causes state drift.
  - *Solution*: Set `Cache-Control: no-cache, no-store, must-revalidate` and `Vary: Cookie, X-CART-UUID`.

- **Anti-Pattern 4: Orphaned Guest Carts on Login**
  - *Rule*: Always invoke `merge_guest_cart_if_needed(request)` and delete the guest Redis key after merging.
  - *Risk*: Users lose unauthenticated cart items after logging in, or guest carts leak memory across millions of abandoned sessions.
  - *Solution*: Atomic merge with explicit TTL expiration and guest key deletion.

---

## 4. Bundled Resource Templates

The following production-ready templates are available in [`resources/`](./resources):

- **Backend**:
  - [`redis_cart.py`](./resources/backend/redis_cart.py): Complete Redis hash cart engine with stock validation, byte-safe decoding, pipeline merges, and guest eviction.
  - [`views_cart.py`](./resources/backend/views_cart.py): DRF `CartAPIView` supporting `GET`, `POST`, `PATCH`, and `DELETE` with cache control headers.
- **Frontend**:
  - [`cartCookies.ts`](./resources/frontend/cartCookies.ts): Client-side RFC4122 guest UUID generation, cookie management, and cross-storage persistence.
  - [`useCartStore.ts`](./resources/frontend/useCartStore.ts): Production Zustand store with monotonic sequence guard protection and offline localStorage fallback.

---

## 5. Technical References
- [`references/monotonic-guard.md`](./references/monotonic-guard.md): In-depth theoretical and architectural guide on race conditions and sequence counter patterns.
