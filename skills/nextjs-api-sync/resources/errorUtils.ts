/**
 * Django REST Framework Error Normalization Utility
 *
 * Normalizes heterogeneous DRF error responses (validation arrays, non_field_errors,
 * detail strings, nested objects, and transport failures) into user-ready strings
 * and structured field error maps.
 */

interface ErrorResponseObject {
  [key: string]: unknown;
}

/**
 * Extracts a normalized, single human-readable error message from arbitrary DRF exceptions.
 * Follows a prioritized evaluation pipeline to present the most specific error message first.
 *
 * @param err Caught exception from Axios, serverFetch, or generic runtime.
 * @returns Human-readable, actionable error message string.
 */
export function extractErrorMessage(err: unknown): string {
  if (!err) {
    return 'An unexpected error occurred. Please try again.';
  }

  // 1. Direct string error
  if (typeof err === 'string') {
    return err;
  }

  const errorObj = err as Record<string, unknown>;

  // 2. Extract payload data from AxiosError (err.response.data) or ServerFetchError (err.data)
  let data: unknown = undefined;
  if (errorObj.response && typeof errorObj.response === 'object') {
    const response = errorObj.response as Record<string, unknown>;
    data = response.data;
  } else if ('data' in errorObj) {
    data = errorObj.data;
  } else {
    data = err;
  }

  // 3. Handle string response payload (e.g. 502/500 HTML or raw text)
  if (typeof data === 'string') {
    const trimmed = data.trim();
    if (trimmed.startsWith('<!DOCTYPE') || trimmed.startsWith('<html')) {
      const status =
        (errorObj.response as Record<string, unknown> | undefined)?.status ||
        errorObj.status;
      return status
        ? `Server error (${status}). Please try again later.`
        : 'Internal server error. Please try again later.';
    }
    return trimmed;
  }

  // 4. Handle array payloads (e.g., ["Direct array validation error"])
  if (Array.isArray(data)) {
    if (data.length > 0) {
      const first = data[0];
      return typeof first === 'string' ? first : extractErrorMessage(first);
    }
  }

  // 5. Handle structured JSON objects from DRF
  if (data && typeof data === 'object') {
    const dict = data as ErrorResponseObject;

    // 5a. Prioritize DRF detail string (PermissionDenied, NotFound, AuthenticationFailed)
    if (dict.detail) {
      if (typeof dict.detail === 'string') {
        return dict.detail;
      }
      if (Array.isArray(dict.detail) && dict.detail.length > 0) {
        return String(dict.detail[0]);
      }
    }

    // 5b. DRF standard non_field_errors
    if (dict.non_field_errors) {
      if (Array.isArray(dict.non_field_errors) && dict.non_field_errors.length > 0) {
        return String(dict.non_field_errors[0]);
      }
      if (typeof dict.non_field_errors === 'string') {
        return dict.non_field_errors;
      }
    }

    // 5c. Generic top-level 'error' field
    if (dict.error) {
      if (typeof dict.error === 'string') {
        return dict.error;
      }
      if (Array.isArray(dict.error) && dict.error.length > 0) {
        return String(dict.error[0]);
      }
      if (typeof dict.error === 'object') {
        return extractErrorMessage(dict.error);
      }
    }

    // 5d. Generic top-level 'message' field
    if (dict.message) {
      if (typeof dict.message === 'string') {
        return dict.message;
      }
      if (Array.isArray(dict.message) && dict.message.length > 0) {
        return String(dict.message[0]);
      }
    }

    // 5e. First field-specific validation error (e.g., { "username": ["Field is required"] })
    const fieldEntries = Object.entries(dict);
    for (const [field, errorValue] of fieldEntries) {
      // Ignore meta keys that are not validation fields
      if (['status', 'status_code', 'code'].includes(field)) {
        continue;
      }

      const formattedFieldName = field.replace(/_/g, ' ');

      if (Array.isArray(errorValue) && errorValue.length > 0) {
        const firstVal = errorValue[0];
        if (typeof firstVal === 'string') {
          return `${formattedFieldName}: ${firstVal}`;
        }
        if (typeof firstVal === 'object') {
          return `${formattedFieldName}: ${extractErrorMessage(firstVal)}`;
        }
      }

      if (typeof errorValue === 'string') {
        return `${formattedFieldName}: ${errorValue}`;
      }

      if (errorValue && typeof errorValue === 'object') {
        return `${formattedFieldName}: ${extractErrorMessage(errorValue)}`;
      }
    }
  }

  // 6. Network/Axios transport error fallbacks
  if (errorObj.code === 'ECONNABORTED' || errorObj.message === 'Network Error') {
    return 'Network connection failed. Please verify your internet connection.';
  }

  if (typeof errorObj.message === 'string' && errorObj.message.length > 0) {
    return errorObj.message;
  }

  // 7. Ultimate safe fallback
  return 'An unexpected error occurred. Please try again.';
}

/** Non-field keys that must never be mapped to individual form input fields. */
const NON_FIELD_KEYS = [
  'detail',
  'code',
  'error',
  'message',
  'non_field_errors',
  'status',
  'status_code',
];

/**
 * Normalizes DRF field validation errors into a structured map for form binding.
 * Explicitly ignores non-field / banner keys so they are not bound to phantom inputs.
 *
 * Example input:  { "email": ["Invalid email"], "password": ["Too short"] }
 * Example output: { "email": ["Invalid email"], "password": ["Too short"] }
 *
 * @param err Caught exception
 * @returns Key-value record mapping field names to string error arrays.
 */
export function extractFieldErrors(err: unknown): Record<string, string[]> {
  const result: Record<string, string[]> = {};

  if (!err || typeof err !== 'object') {
    return result;
  }

  const errorObj = err as Record<string, unknown>;
  const data = (errorObj.response as Record<string, unknown> | undefined)?.data || errorObj.data || err;

  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    return result;
  }

  // If structured fields object is present (from standardized api_exception_handler)
  const fieldsSource = (data as Record<string, unknown>).fields || data;
  if (!fieldsSource || typeof fieldsSource !== 'object' || Array.isArray(fieldsSource)) {
    return result;
  }

  for (const [field, value] of Object.entries(fieldsSource as ErrorResponseObject)) {
    if (NON_FIELD_KEYS.includes(field)) {
      continue;
    }

    if (Array.isArray(value)) {
      result[field] = value.map((item) => (typeof item === 'string' ? item : JSON.stringify(item)));
    } else if (typeof value === 'string') {
      result[field] = [value];
    } else if (value && typeof value === 'object') {
      result[field] = [extractErrorMessage(value)];
    }
  }

  return result;
}

/**
 * Extracts a non-field error message specifically intended for top-level alert banners.
 * Returns null if the error is purely field-specific with no general message.
 *
 * @param err Caught exception
 * @returns High-level banner error string, or null.
 */
export function extractNonFieldError(err: unknown): string | null {
  if (!err || typeof err !== 'object') {
    return null;
  }

  const errorObj = err as Record<string, unknown>;
  const data = (
    (errorObj.response as Record<string, unknown> | undefined)?.data ??
    errorObj.data ??
    err
  ) as Record<string, unknown> | null;

  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    return null;
  }

  const raw = data.detail ?? data.non_field_errors ?? data.error ?? data.message;
  if (!raw) {
    return null;
  }

  if (Array.isArray(raw)) {
    return raw.length > 0 ? String(raw[0]) : null;
  }
  return typeof raw === 'string' ? raw : extractErrorMessage(raw);
}

export default extractErrorMessage;
