# Workflow 03: Enable High-Concurrency E-Commerce Cart

Step-by-step orchestrator runbook for conditionally injecting the decoupled, high-concurrency Redis shopping cart domain module into an existing Django REST Framework + Next.js App Router project.

---

## 1. Architectural Overview & Cart Lifecycle

This workflow activates the e-commerce shopping cart domain extension. The cart engine is decoupled from relational database writes, utilizing Redis Hashes for sub-millisecond mutations, transparent guest tracking via `X-CART-UUID`, atomic guest-to-user cart merging upon login, and client-side Monotonic Sequence Guards to eliminate rapid-click UI race conditions:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Cart Lifecycle Architecture                     │
└────────────────────────────────────────────────────────────────────────┘

 [ Anonymous Guest Browser ]                     [ Authenticated User Browser ]
             │                                                  │
             ▼                                                  ▼
 1. Reads/Generates cart_guest_uuid               2. Holds pod_access_token cookie
             │                                                  │
             ▼                                                  ▼
 3. Mutation: POST /api/v2/cart/                  3. Mutation: POST /api/v2/cart/
    Header: X-CART-UUID: <uuid>                      Header: X-CART-UUID: <uuid>
             │                                                  │
             ▼                                                  ▼
 ┌──────────────────────────────┐                 ┌──────────────────────────────┐
 │ DRF get_cart_for_request()   │                 │ DRF merge_guest_cart_...()   │
 │ Maps to:                     │                 │ Atomically merges:           │
 │ key: `cart:guest:<uuid>`     │                 │ `cart:guest:<uuid>` into     │
 │ TTL: 30 days                 │                 │ `cart:user:<user_id>`        │
 └──────────────┬───────────────┘                 └──────────────┬───────────────┘
                │                                                │
                ▼                                                ▼
 ┌──────────────────────────────┐                 ┌──────────────────────────────┐
 │ Redis Hash Storage           │                 │ Redis Hash Storage           │
 │ Field: <product_id>          │                 │ Field: <product_id>          │
 │ Value: JSON item payload     │                 │ Value: JSON item payload     │
 └──────────────────────────────┘                 └──────────────────────────────┘
```

---

## 2. Step-by-Step Implementation

### Step 1: Verify Redis Connectivity & Configuration

1. **Verify Redis Container Health**:
   Execute a Redis ping command within the running Docker stack:
   ```bash
   docker compose exec redis redis-cli ping
   ```
   - **Expected Output**: `PONG`

2. **Verify Django Redis Cache Backend**:
   Ensure `REDIS_URL` is configured in `backend/.env`:
   ```env
   REDIS_URL=redis://redis:6379/1
   ```
   In `backend/config/settings.py`, verify the cache configuration:
   ```python
   CACHES = {
       "default": {
           "BACKEND": "django.core.cache.backends.redis.RedisCache",
           "LOCATION": env("REDIS_URL", default="redis://redis:6379/1"),
       }
   }
   ```

---

### Step 2: Backend Cart Module Integration

#### 2.1 Scaffold Domain Application
Create the `cart` domain application inside `backend/apps/`:
```bash
docker compose exec backend python manage.py startapp cart apps/cart
```

#### 2.2 Deploy Cart Engine & Views
Copy the backend resources from [`skills/domain-ecommerce-cart/resources/backend/`](../skills/domain-ecommerce-cart/resources/backend/) into `backend/apps/cart/`:
```bash
cp skills/domain-ecommerce-cart/resources/backend/redis_cart.py backend/apps/cart/redis_cart.py
cp skills/domain-ecommerce-cart/resources/backend/views_cart.py backend/apps/cart/views.py
```

#### 2.3 Configure URLs
Create `backend/apps/cart/urls.py`:
```python
# backend/apps/cart/urls.py
from django.urls import path
from cart.views import CartAPIView

urlpatterns = [
    path('', CartAPIView.as_view(), name='cart-detail'),
]
```

Mount the cart endpoints in `backend/config/urls.py`:
```python
# backend/config/urls.py
from django.urls import path, include

urlpatterns = [
    # ... health, auth, admin
    path('api/v2/cart/', include('cart.urls')),
]
```

#### 2.4 Register Application in Django Settings
Add `'cart'` to `INSTALLED_APPS` in `backend/config/settings.py`:
```python
INSTALLED_APPS = [
    # Django core apps ...
    'rest_framework',
    'corsheaders',
    # Domain apps (resolved cleanly via sys.path injection)
    'users',
    'cart',
]
```

#### 2.5 Hook Cart Merge into User Authentication
In `backend/apps/users/views.py` (or your authentication login view), ensure that when an anonymous guest logs in, their pending guest cart items are merged into their authenticated user cart:
```python
from cart.redis_cart import merge_guest_cart_if_needed

class LoginAPIView(APIView):
    def post(self, request: Request) -> Response:
        # ... authenticate user ...
        request.user = user

        # Merge guest cart into user cart if X-CART-UUID is present
        merge_guest_cart_if_needed(request)
            
        # ... return response with auth cookies ...
```

---

### Step 3: Frontend Next.js Cart Integration

#### 3.1 Deploy Cart Cookie & UUID Helper
Copy [`skills/domain-ecommerce-cart/resources/frontend/cartCookies.ts`](../skills/domain-ecommerce-cart/resources/frontend/cartCookies.ts) to `frontend/lib/cart/cartCookies.ts`:
```bash
mkdir -p frontend/lib/cart
cp skills/domain-ecommerce-cart/resources/frontend/cartCookies.ts frontend/lib/cart/cartCookies.ts
```
This utility:
- Generates RFC4122 v4 UUIDs via `crypto.randomUUID()`.
- Synchronizes the guest UUID across `document.cookie` (`cart_guest_uuid`) and `localStorage` (`pod_cart_guest_uuid`).
- Rehydrates UUIDs across page refreshes and browser tabs.

#### 3.2 Link `X-CART-UUID` in HTTP Interceptors
Update `frontend/lib/api/apiClient.ts` to automatically attach the guest cart UUID to all outgoing API requests:
```typescript
import { getOrCreateCartUUID } from '@/lib/cart/cartCookies';

apiClient.interceptors.request.use(
  (config) => {
    // Attach guest cart UUID header
    const guestUuid = getOrCreateCartUUID();
    if (guestUuid) {
      config.headers['X-CART-UUID'] = guestUuid;
    }
    
    // ... CSRF token injection ...
    return config;
  },
  (error) => Promise.reject(error)
);
```

#### 3.3 Deploy Zustand Cart Store with Monotonic Guard
Copy [`skills/domain-ecommerce-cart/resources/frontend/useCartStore.ts`](../skills/domain-ecommerce-cart/resources/frontend/useCartStore.ts) to `frontend/lib/stores/useCartStore.ts`:
```bash
cp skills/domain-ecommerce-cart/resources/frontend/useCartStore.ts frontend/lib/stores/useCartStore.ts
```

> [!TIP]
> **Understanding the Monotonic Sequence Guard**:
> When a user clicks '+' or '-' rapidly, multiple asynchronous network requests are in flight. If request #1 takes 300ms and request #2 takes 80ms, request #1 could arrive *after* request #2 and overwrite newer UI state with stale data.
> The Monotonic Sequence Guard (`lastRequestSeq`) tracks incrementing request integers and discards out-of-order responses:
> ```typescript
> const currentSeq = ++lastRequestSeq;
> const response = await apiClient.post('/api/v2/cart/', { ... });
> if (currentSeq < lastRequestSeq) {
>   // Newer request has already been dispatched; discard this stale payload
>   return;
> }
> ```
> For complete technical rationale, consult [`skills/domain-ecommerce-cart/references/monotonic-guard.md`](../skills/domain-ecommerce-cart/references/monotonic-guard.md).

---

## 4. Acceptance Criteria & Verification Checklist

Execute each verification step to test high-concurrency cart functionality:

### Check 1: Guest Cart Creation & Item Addition
Add an item to the cart as an anonymous guest with a custom UUID:
```bash
curl -i -X POST http://localhost:8080/api/v2/cart/ \
  -H "Content-Type: application/json" \
  -H "X-CART-UUID: test-guest-uuid-12345" \
  -d '{"product_id": 101, "quantity": 2}'
```
- **Expected Outcome**:
  - HTTP `200 OK`.
  - JSON response contains cart summary with item count `2` and subtotal.
  - Header includes `Cache-Control: no-cache, no-store, must-revalidate`.

### Check 2: Inspect Redis Hash Key
Verify that the cart item was written directly to Redis:
```bash
docker compose exec redis redis-cli HGETALL cart:guest:test-guest-uuid-12345
```
- **Expected Outcome**: Field `"101"` contains JSON payload with `"product_id": 101` and `"quantity": 2`.

### Check 3: Retrieve Cart Summary
Query the cart endpoint via `GET`:
```bash
curl -i -X GET http://localhost:8080/api/v2/cart/ \
  -H "X-CART-UUID: test-guest-uuid-12345"
```
- **Expected Outcome**: HTTP `200 OK` with full cart items array and item count `2`.

### Check 4: Update Item Quantity (PATCH)
Update product quantity to 5:
```bash
curl -i -X PATCH http://localhost:8080/api/v2/cart/ \
  -H "Content-Type: application/json" \
  -H "X-CART-UUID: test-guest-uuid-12345" \
  -d '{"product_id": 101, "quantity": 5}'
```
- **Expected Outcome**: HTTP `200 OK` with updated item count `5`.

### Check 5: Atomic Guest-to-User Cart Merge
Log in as an authenticated user while supplying the active `X-CART-UUID` header:
```bash
curl -i -X POST http://localhost:8080/api/v2/auth/login/ \
  -H "Content-Type: application/json" \
  -H "X-CART-UUID: test-guest-uuid-12345" \
  -d '{"username": "testuser", "password": "TestPassword123!"}'
```
Inspect Redis keys to verify the merge:
```bash
# User cart should now contain the 5 items
docker compose exec redis redis-cli HGETALL cart:user:1
# Guest cart key must be evicted/deleted
docker compose exec redis redis-cli EXISTS cart:guest:test-guest-uuid-12345
```
- **Expected Outcome**:
  - `cart:user:1` returns the merged items.
  - `EXISTS cart:guest:test-guest-uuid-12345` returns `0` (evicted).

### Check 6: Delete Item & Clear Cart
Remove an item:
```bash
curl -i -X DELETE http://localhost:8080/api/v2/cart/ \
  -H "Content-Type: application/json" \
  -H "X-CART-UUID: test-guest-uuid-12345" \
  -d '{"product_id": 101}'
```
- **Expected Outcome**: HTTP `200 OK` with item removed from summary.

---

## 5. Summary of Cache Prevention & Concurrency Controls

| Control | Mechanism | Purpose |
| :--- | :--- | :--- |
| **Monotonic Sequence Guard** | Module-level sequence counter in Zustand store | Prevents out-of-order async responses from overwriting newer user changes. |
| **Pipeline Merging** | Redis pipeline atomic execution | Merges guest cart items in a single round-trip before evicting the guest key. |
| **Cache Invalidation** | `Cache-Control: no-cache, no-store, must-revalidate` | Prevents browser and proxy caches from serving stale cart totals. |
| **Stock Boundary Check** | `RedisCart.verify_stock_availability()` | Automatically clamps requested quantity to maximum available inventory. |
