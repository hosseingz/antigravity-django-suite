/**
 * Guest Cart UUID Tracking & Cookie Management
 *
 * Generates and synchronizes anonymous guest cart identifiers across
 * browser cookies and localStorage. Enables persistent guest shopping
 * and atomic server-side merging upon user authentication.
 */

const CART_UUID_COOKIE = 'cart_guest_uuid';
const CART_UUID_STORAGE_KEY = 'pod_cart_guest_uuid';
const COOKIE_MAX_AGE_DAYS = 30;

/**
 * Generates a RFC4122 compliant UUID v4 string.
 * Uses native crypto.randomUUID() when available, with a pseudo-random fallback.
 */
function generateUUID(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }

  // Fallback for older runtimes
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/**
 * Reads a specific cookie value by name from document.cookie.
 */
function getCookie(name: string): string | null {
  if (typeof document === 'undefined') {
    return null;
  }
  const match = document.cookie.match(new RegExp(`(?:^|;\\s*)${name}=([^;]+)`));
  return match ? decodeURIComponent(match[1]) : null;
}

/**
 * Sets a cookie in document.cookie with Lax SameSite and 30-day expiration.
 */
function setCookie(name: string, value: string, days: number = COOKIE_MAX_AGE_DAYS): void {
  if (typeof document === 'undefined') {
    return;
  }
  const maxAge = days * 24 * 60 * 60;
  const isSecure = typeof window !== 'undefined' && window.location.protocol === 'https:';
  document.cookie = `${name}=${encodeURIComponent(value)}; path=/; max-age=${maxAge}; SameSite=Lax${
    isSecure ? '; Secure' : ''
  }`;
}

/**
 * Retrieves the existing guest cart UUID from cookie or localStorage,
 * or generates and stores a new UUID if none exists.
 *
 * @returns Synchronized guest cart UUID string.
 */
export function getOrCreateCartUUID(): string {
  if (typeof window === 'undefined') {
    return '';
  }

  // 1. Check existing cookie
  let uuid = getCookie(CART_UUID_COOKIE);

  // 2. Check localStorage fallback if cookie was cleared
  if (!uuid) {
    try {
      uuid = localStorage.getItem(CART_UUID_STORAGE_KEY);
    } catch {
      // Ignore storage access restrictions
    }
  }

  // 3. Generate new UUID if absent
  if (!uuid || uuid.trim().length === 0) {
    uuid = generateUUID();
  }

  // 4. Synchronize across both storage layers
  setCookie(CART_UUID_COOKIE, uuid);
  try {
    localStorage.setItem(CART_UUID_STORAGE_KEY, uuid);
  } catch {
    // Ignore storage quota errors
  }

  return uuid;
}

/**
 * Returns the active guest cart UUID if one exists, without generating a new one.
 */
export function getExistingCartUUID(): string | null {
  if (typeof window === 'undefined') {
    return null;
  }
  return getCookie(CART_UUID_COOKIE) || localStorage.getItem(CART_UUID_STORAGE_KEY) || null;
}

/**
 * Evicts the guest cart UUID from cookies and localStorage after an
 * authenticated merge has completed.
 */
export function clearCartUUID(): void {
  if (typeof document === 'undefined') {
    return;
  }
  document.cookie = `${CART_UUID_COOKIE}=; path=/; max-age=0; SameSite=Lax`;
  try {
    localStorage.removeItem(CART_UUID_STORAGE_KEY);
  } catch {
    // Ignore storage errors
  }
}
