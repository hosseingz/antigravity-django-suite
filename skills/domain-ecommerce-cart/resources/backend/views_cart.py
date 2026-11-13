"""
Django REST Framework Cart API Views

Exposes REST endpoints for cart management:
- GET: Retrieve current cart items and totals
- POST: Add product with quantity
- PATCH: Update existing product quantity
- DELETE: Remove single item or clear cart

Every mutation executes `merge_guest_cart_if_needed(request)` to guarantee
atomic transition from anonymous guest to authenticated user.
"""

import logging
import uuid
from typing import Optional

from django.conf import settings
from django.core.exceptions import ValidationError
from rest_framework import permissions, status
from rest_framework.authentication import CSRFCheck
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from .redis_cart import RedisCart, merge_guest_cart_if_needed

logger = logging.getLogger(__name__)

CART_UUID_HEADER = "X-CART-UUID"
CART_UUID_COOKIE = "cart_guest_uuid"
CART_UUID_TTL_SECONDS = 60 * 60 * 24 * 30
AUTH_COOKIE_NAMES = ("pod_access_token", "pod_refresh_token")


def get_guest_identifier(request) -> Optional[str]:
    """
    Returns the caller's guest cart identifier as a canonical UUID, or None.

    The identifier alone selects a guest cart, so it is parsed as a UUID: free-form text
    would let a caller address arbitrary Redis key paths.
    """
    raw = (
        request.headers.get(CART_UUID_HEADER)
        or request.COOKIES.get(CART_UUID_COOKIE)
        or request.COOKIES.get("x-cart-uuid")
    )
    if not raw:
        return None
    try:
        return str(uuid.UUID(str(raw).strip()))
    except (ValueError, AttributeError, TypeError):
        logger.warning("Rejected malformed guest cart identifier on %s.", request.path)
        return None


def get_cart_for_request(request) -> RedisCart:
    """
    Extracts the appropriate RedisCart instance based on user authentication
    or guest tracking identifier (X-CART-UUID header / cookie).
    """
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        return RedisCart(identifier=str(user.id), is_user=True)

    guest_uuid = get_guest_identifier(request)
    if not guest_uuid:
        # A single constant key (formerly "anonymous_session") made every anonymous visitor
        # with no cart identifier share one cart, readable and clearable by anyone.
        guest_uuid = str(uuid.uuid4())
        request._issued_cart_uuid = guest_uuid

    return RedisCart(identifier=guest_uuid, is_user=False)


class CartCSRFProtectionMixin:
    """
    Re-introduces CSRF verification for cart mutations that arrive with the ambient
    authentication cookies, which DRF's csrf_exempt APIView would otherwise skip.

    Only cookie-authenticated requests are checked: a guest cart is selected by a
    SameSite=Lax cookie browsers already withhold from cross-site POSTs, and guests hold no
    csrftoken, so enforcing the token there would break guest carts.
    """

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
            return
        if not any(name in request.COOKIES for name in AUTH_COOKIE_NAMES):
            return

        check = CSRFCheck(lambda req: None)
        check.process_request(request)
        reason = check.process_view(request, None, (), {})
        if reason:
            logger.warning("CSRF validation failed on cart endpoint (%s): %s", request.path, reason)
            raise PermissionDenied(f"CSRF Failed: {reason}")


def finalize_cart_response(request, response: Response) -> Response:
    """
    Appends strict cache prevention and Vary headers to prevent CDN or Next.js
    intermediate caching of user/guest cart data, and persists a newly issued guest
    identifier so the next request addresses the same cart.
    """
    response["Cache-Control"] = "no-cache, no-store, must-revalidate, private"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    response["Vary"] = "Cookie, X-CART-UUID, Authorization"

    issued_uuid = getattr(request, "_issued_cart_uuid", None)
    if issued_uuid:
        response.set_cookie(
            CART_UUID_COOKIE,
            issued_uuid,
            max_age=CART_UUID_TTL_SECONDS,
            samesite="Lax",
            secure=getattr(settings, "COOKIE_SECURE", False),
            path="/",
        )

    return response


class CartAPIView(CartCSRFProtectionMixin, APIView):
    """
    Authoritative Shopping Cart API Endpoint.
    Accessible by both authenticated users and anonymous guests.
    """

    permission_classes = [permissions.AllowAny]

    def get(self, request, *args, **kwargs):
        """
        Retrieves cart items, total counts, and calculated subtotals.
        Silently merges guest items if user is authenticated with a guest UUID.
        """
        merge_guest_cart_if_needed(request)
        cart = get_cart_for_request(request)
        summary = cart.get_summary()

        response = Response(
            {
                "success": True,
                "cart": summary,
            },
            status=status.HTTP_200_OK,
        )
        return finalize_cart_response(request, response)

    def post(self, request, *args, **kwargs):
        """
        Adds or increments an item in the cart.
        Payload: { "product_id": int, "quantity": int (optional, default 1), "metadata": dict (optional) }
        """
        merge_guest_cart_if_needed(request)
        cart = get_cart_for_request(request)

        product_id = request.data.get("product_id")
        if not product_id:
            return Response(
                {"success": False, "error": "product_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            product_id = int(product_id)
            quantity = int(request.data.get("quantity", 1))
        except (ValueError, TypeError):
            return Response(
                {"success": False, "error": "product_id and quantity must be valid integers."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        metadata = request.data.get("metadata")

        try:
            cart.add_item(
                product_id=product_id,
                quantity=quantity,
                metadata=metadata,
                verify_stock=True,
            )
        except ValidationError as exc:
            return Response(
                {"success": False, "error": str(exc.message if hasattr(exc, 'message') else exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        summary = cart.get_summary()
        response = Response(
            {
                "success": True,
                "message": "Item added to cart.",
                "cart": summary,
            },
            status=status.HTTP_201_CREATED,
        )
        return finalize_cart_response(request, response)

    def patch(self, request, *args, **kwargs):
        """
        Updates the explicit quantity of an existing item in the cart.
        If quantity <= 0, the item is removed.
        Payload: { "product_id": int, "quantity": int }
        """
        merge_guest_cart_if_needed(request)
        cart = get_cart_for_request(request)

        product_id = request.data.get("product_id")
        if not product_id:
            return Response(
                {"success": False, "error": "product_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            product_id = int(product_id)
            quantity = int(request.data.get("quantity", 0))
        except (ValueError, TypeError):
            return Response(
                {"success": False, "error": "product_id and quantity must be valid integers."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            cart.update_quantity(
                product_id=product_id,
                quantity=quantity,
                verify_stock=True,
            )
        except ValidationError as exc:
            return Response(
                {"success": False, "error": str(exc.message if hasattr(exc, 'message') else exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        summary = cart.get_summary()
        response = Response(
            {
                "success": True,
                "message": "Cart item updated.",
                "cart": summary,
            },
            status=status.HTTP_200_OK,
        )
        return finalize_cart_response(request, response)

    def delete(self, request, *args, **kwargs):
        """
        Removes an item from the cart, or clears the entire cart if no product_id is specified.
        Query / Body Param: product_id (optional)
        """
        merge_guest_cart_if_needed(request)
        cart = get_cart_for_request(request)

        product_id = request.data.get("product_id") or request.query_params.get("product_id")

        if product_id:
            try:
                product_id = int(product_id)
                cart.remove_item(product_id)
                message = f"Product {product_id} removed from cart."
            except (ValueError, TypeError):
                return Response(
                    {"success": False, "error": "Invalid product_id."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            cart.clear()
            message = "Cart cleared successfully."

        summary = cart.get_summary()
        response = Response(
            {
                "success": True,
                "message": message,
                "cart": summary,
            },
            status=status.HTTP_200_OK,
        )
        return finalize_cart_response(request, response)
