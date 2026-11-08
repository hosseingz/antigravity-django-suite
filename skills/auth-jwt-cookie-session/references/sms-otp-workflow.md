# Technical Reference: Redis-Backed SMS OTP Workflow

This document details the architecture, state lifecycle, rate-limiting, and brute-force defenses governing the SMS One-Time Password (OTP) verification system in `antigravity-django-suite`.

---

## 1. Architecture & State Transition Diagram

```
[ User Browser / Mobile ]                 [ Django DRF Backend ]               [ Redis Cache ]
           │                                        │                                 │
           │ 1. POST /api/v2/auth/otp/send/         │                                 │
           │    { phone: "+1234567890" }            │                                 │
           ├───────────────────────────────────────►│                                 │
           │                                        │ 2. Check otp:locked:<phone>     │
           │                                        ├────────────────────────────────►│
           │                                        │ 3. Check otp:cooldown:<phone>   │
           │                                        ├────────────────────────────────►│
           │                                        │ 4. Generate 6-digit OTP         │
           │                                        │    Store code & set 120s TTL    │
           │                                        ├────────────────────────────────►│
           │ 5. HTTP 200 OK                         │                                 │
           │    { detail: "...", retry_after: 120 } │                                 │
           │◄───────────────────────────────────────┤                                 │
           │                                        │                                 │
           │ [ User enters code on UI ]             │                                 │
           │                                        │                                 │
           │ 6. POST /api/v2/auth/otp/verify/       │                                 │
           │    { phone: "...", code: "582910" }    │                                 │
           ├───────────────────────────────────────►│                                 │
           │                                        │ 7. Check attempts (limit: 5)    │
           │                                        ├────────────────────────────────►│
           │                                        │ 8. hmac.compare_digest check    │
           │                                        ├────────────────────────────────►│
           │                                        │ 9. Success: Delete Redis keys   │
           │                                        │    Issue JWT Cookie pair        │
           │ 10. HTTP 200 OK + Set-Cookie headers   │                                 │
           │     { user: { ... } }                  │                                 │
           │◄───────────────────────────────────────┤                                 │
```

---

## 2. Redis Key Lifecycle & Expiration Matrix

To prevent memory leaks and enforce strict operational windows, every Redis key is provisioned with an explicit Time-To-Live (TTL):

| Redis Key Pattern | Type | Default TTL | Description & Purpose |
| :--- | :--- | :--- | :--- |
| `otp:code:<phone>` | `string` | **120 seconds** (2 min) | Stores the cryptographically generated 6-digit verification code. Evaluated and deleted immediately upon successful verification. |
| `otp:cooldown:<phone>` | `string` | **120 seconds** (2 min) | Prevents users or malicious scripts from spamming SMS gateway dispatches. Resend button remains locked on frontend while key persists. |
| `otp:attempts:<phone>` | `integer` | **120 seconds** (2 min) | Tracks consecutive failed code verification attempts. Incremented on mismatch; resets to 0 on new send. |
| `otp:locked:<phone>` | `string` | **900 seconds** (15 min) | Provisioned when `otp:attempts` reaches 5. Blocks both sending and verification for 15 minutes to defeat distributed brute-force cracking. |

---

## 3. Brute-Force & Timing Attack Protection

### 3.1 Constant-Time String Comparison
Standard string equality checks (`stored_code == input_code`) short-circuit on the first mismatched byte, creating timing side-channels that attackers can exploit over high-resolution network probes.

**Enforcement**:
Always use constant-time comparison via Python's `hmac.compare_digest`:
```python
import hmac

if not hmac.compare_digest(stored_code, user_supplied_code):
    # Handle mismatch
```

### 3.2 Max 5 Attempt Lockout Protocol
Six-digit decimal codes offer $10^6 = 1,000,000$ combinations. Without attempt restrictions, an attacker could script a parallelized search within the 120-second validity window.

**Defense Implementation**:
1. When `attempts >= 5`:
   - Delete `otp:code:<phone>`.
   - Delete `otp:cooldown:<phone>`.
   - Set `otp:locked:<phone> = "1"` with a 900-second (15-minute) TTL.
   - Return HTTP `429 Too Many Requests` with code `max_attempts_exceeded`.
2. Any subsequent requests to `/otp/send/` or `/otp/verify/` for that phone number are rejected with HTTP 429 until the 15-minute window expires.

---

## 4. Frontend & Backend Synchronization (`retry_after`)

To provide responsive UI feedback without client/server clock drift issues:
- The backend returns `retry_after: 120` in the response payload.
- Next.js client components initialize an active countdown timer from `response.data.retry_after`:
```typescript
const [secondsLeft, setSecondsLeft] = useState<number>(0);

async function handleSendOtp() {
  const { data } = await apiClient.post(API_ENDPOINTS.auth.sendOtp, { phone });
  setSecondsLeft(data.retry_after); // Sync with backend Redis cooldown
}
```
- The "Resend Code" button is disabled whenever `secondsLeft > 0`.
- If the user reloads the page, an attempt to request an OTP prematurely will receive HTTP `429 Too Many Requests` with `code: "cooldown_active"` and the remaining TTL.

---

## 5. User Auto-Provisioning & Cookie Handoff

Upon successful OTP verification:
1. `User.objects.get_or_create(username=phone)` ensures seamless passwordless onboarding.
2. `issue_token_pair(user)` generates standard `pod_access_token` and `pod_refresh_token`.
3. `set_auth_cookies(response, access_token, refresh_token)` writes HttpOnly cookies.
4. Client Zustand store receives serialized user metadata and updates `isAuthenticated: true`.
