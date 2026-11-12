/**
 * Canonical API Type Definitions for Next.js and DRF Integration.
 *
 * Enforces strict typing across API boundaries, eliminating 'any' pollution
 * and ensuring field names strictly mirror DRF serializers.
 */

/**
 * Standardized DRF PageNumberPagination envelope.
 * Guaranteed shape for all pageable collection endpoints.
 */
export interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

/**
 * Standardized 3-part DRF Error Contract.
 * Produced by config.exceptions.api_exception_handler.
 */
export interface ApiErrorResponse {
  /** High-level human-readable summary message. Always present as a string. */
  detail: string;
  /** Stable snake_case machine identifier (e.g. 'validation_error', 'token_refresh_required'). */
  code: string;
  /** Field-specific validation errors. Populated only on 400 validation failures. */
  fields?: Record<string, string[]>;
}

/**
 * Common base entity metadata present on most persistent models.
 */
export interface BaseEntity {
  id: number | string;
  created_at?: string;
  updated_at?: string;
}

/**
 * Authenticated user profile metadata returned by /api/v1/auth/me/.
 */
export interface UserProfile extends BaseEntity {
  email: string;
  username?: string;
  first_name?: string;
  last_name?: string;
  is_active?: boolean;
}

