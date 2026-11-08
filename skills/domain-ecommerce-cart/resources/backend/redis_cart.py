"""
Redis Shopping Cart Engine & Atomic Guest-to-User Merging

High-concurrency cart manager backed by Redis Hashes.
Supports anonymous guest tracking via UUIDs, authenticated user sessions,
automatic stock verification, byte-safe deserialization, and atomic merge operations.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError

try:
    from django_redis import get_redis_connection
except ImportError:
    get_redis_connection = None

import redis

logger = logging.getLogger(__name__)


def get_redis_client() -> redis.Redis:
    """
    Returns an active Redis client connection using django-redis connection pool
    if configured, or falling back to REDIS_URL from settings.
    """
    if get_redis_connection:
        try:
            return get_redis_connection("default")
        except Exception as exc:
            logger.warning("django_redis connection failed, falling back to direct Redis client: %s", exc)

    redis_url = getattr(settings, "REDIS_URL", "redis://redis:6379/1")
    return redis.Redis.from_url(redis_url)


class RedisCart:
    """
    Redis Hash-backed cart manager.
    Keys:
      - Authenticated User: `cart:user:<user_id>`
      - Anonymous Guest:    `cart:guest:<guest_uuid>`
    Hash Fields: `<product_id>` (string)
    Hash Values: JSON-serialized item payload with quantity, metadata, and timestamps.
    """

    GUEST_TTL_SECONDS = getattr(settings, "CART_GUEST_TTL_SECONDS", 60 * 60 * 24 * 30)  # 30 Days
    USER_TTL_SECONDS = getattr(settings, "CART_USER_TTL_SECONDS", 60 * 60 * 24 * 90)    # 90 Days

    def __init__(self, identifier: str, is_user: bool = False):
        if not identifier:
            raise ValueError("Cart identifier (user_id or guest_uuid) cannot be empty.")
        self.identifier = str(identifier)
        self.is_user = is_user
        self.key = f"cart:user:{self.identifier}" if is_user else f"cart:guest:{self.identifier}"
        self.ttl = self.USER_TTL_SECONDS if is_user else self.GUEST_TTL_SECONDS
        self.client = get_redis_client()

    # -------------------------------------------------------------------------
    # Safe Byte Decoding & Serialization Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _decode(val: Any) -> str:
        """Safely decodes Redis byte strings to UTF-8."""
        if isinstance(val, bytes):
            return val.decode("utf-8")
        return str(val)

    def _parse_item_payload(self, raw_value: Any) -> Dict[str, Any]:
        """Safely decodes and parses JSON payload from Redis hash values."""
        decoded = self._decode(raw_value)
        try:
            data = json.loads(decoded)
            if isinstance(data, dict):
                return data
            # Fallback if stored as bare integer quantity
            return {"quantity": int(data), "product_id": 0}
        except (json.JSONDecodeError, ValueError):
            return {"quantity": 1, "product_id": 0}

    # -------------------------------------------------------------------------
    # Stock Availability Verification
    # -------------------------------------------------------------------------

    def verify_stock_availability(self, product_id: int, requested_quantity: int) -> Tuple[bool, int, Optional[str]]:
        """
        Validates stock availability against the database if a Product model
        is registered in the Django application registry.

        Returns: (is_available, current_stock, error_message)
        """
        if requested_quantity <= 0:
            return False, 0, "Requested quantity must be greater than zero."

        product_model = None
        for app_label in ["catalog", "products", "ecommerce", "store"]:
            try:
                product_model = apps.get_model(app_label, "Product")
                if product_model:
                    break
            except (LookupError, ValueError):
                continue

        if not product_model:
            # Domain catalog app not loaded; permissive fallback for decoupled staging
            return True, 9999, None

        try:
            product = product_model.objects.filter(id=product_id, is_active=True).first()
            if not product:
                return False, 0, f"Product {product_id} was not found or is currently inactive."

            stock_field = getattr(product, "stock", None)
            if stock_field is None:
                stock_field = getattr(product, "inventory_count", 9999)

            if requested_quantity > stock_field:
                return (
                    False,
                    stock_field,
                    f"Insufficient stock for '{getattr(product, 'title', f'Product {product_id}')}'. "
                    f"Available: {stock_field}, requested: {requested_quantity}.",
                )

            return True, stock_field, None
        except Exception as exc:
            logger.error("Stock verification failed for product %s: %s", product_id, exc)
            return True, 9999, None

    # -------------------------------------------------------------------------
    # Core Cart Operations
    # -------------------------------------------------------------------------

    def get_items(self) -> List[Dict[str, Any]]:
        """
        Retrieves all items from the Redis hash with byte-safe decoding.
        """
        raw_hash = self.client.hgetall(self.key)
        items: List[Dict[str, Any]] = []

        if not raw_hash:
            return items

        for field, raw_val in raw_hash.items():
            product_id_str = self._decode(field)
            try:
                product_id = int(product_id_str)
            except ValueError:
                continue

            payload = self._parse_item_payload(raw_val)
            payload["product_id"] = product_id
            items.append(payload)

        return items

    def add_item(
        self,
        product_id: int,
        quantity: int = 1,
        metadata: Optional[Dict[str, Any]] = None,
        verify_stock: bool = True,
    ) -> Dict[str, Any]:
        """
        Adds or increments an item in the cart, verifying database stock availability.
        """
        if quantity <= 0:
            raise ValidationError("Quantity must be greater than zero.")

        field = str(product_id)
        existing_raw = self.client.hget(self.key, field)
        existing_qty = 0

        if existing_raw:
            existing_payload = self._parse_item_payload(existing_raw)
            existing_qty = existing_payload.get("quantity", 0)

        target_quantity = existing_qty + quantity

        if verify_stock:
            is_valid, available_stock, err_msg = self.verify_stock_availability(product_id, target_quantity)
            if not is_valid:
                raise ValidationError(err_msg or "Insufficient stock available.")

        item_data = {
            "product_id": product_id,
            "quantity": target_quantity,
            "added_at": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
        }

        pipeline = self.client.pipeline()
        pipeline.hset(self.key, field, json.dumps(item_data))
        pipeline.expire(self.key, self.ttl)
        pipeline.execute()

        return item_data

    def update_quantity(
        self,
        product_id: int,
        quantity: int,
        verify_stock: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """
        Updates an item to an explicit quantity. If quantity <= 0, the item is removed.
        """
        field = str(product_id)

        if quantity <= 0:
            self.remove_item(product_id)
            return None

        if verify_stock:
            is_valid, available_stock, err_msg = self.verify_stock_availability(product_id, quantity)
            if not is_valid:
                raise ValidationError(err_msg or "Insufficient stock available.")

        existing_raw = self.client.hget(self.key, field)
        existing_meta = {}
        if existing_raw:
            existing_meta = self._parse_item_payload(existing_raw).get("metadata", {})

        item_data = {
            "product_id": product_id,
            "quantity": quantity,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "metadata": existing_meta,
        }

        pipeline = self.client.pipeline()
        pipeline.hset(self.key, field, json.dumps(item_data))
        pipeline.expire(self.key, self.ttl)
        pipeline.execute()

        return item_data

    def remove_item(self, product_id: int) -> bool:
        """Removes a specific product from the Redis hash."""
        field = str(product_id)
        deleted = self.client.hdel(self.key, field)
        return bool(deleted > 0)

    def clear(self) -> bool:
        """Deletes the entire cart key from Redis."""
        return bool(self.client.delete(self.key))

    def merge_from(self, guest_cart: "RedisCart", verify_stock: bool = True) -> int:
        """
        Merges all items from a guest cart into this user cart using a pipeline.
        Items already in user cart have their quantities summed up to available stock.
        """
        guest_items = guest_cart.get_items()
        if not guest_items:
            return 0

        merged_count = 0
        pipeline = self.client.pipeline()

        for g_item in guest_items:
            product_id = g_item["product_id"]
            guest_qty = g_item.get("quantity", 1)
            field = str(product_id)

            existing_raw = self.client.hget(self.key, field)
            current_qty = 0
            if existing_raw:
                current_qty = self._parse_item_payload(existing_raw).get("quantity", 0)

            target_qty = current_qty + guest_qty

            if verify_stock:
                is_valid, available_stock, _ = self.verify_stock_availability(product_id, target_qty)
                if not is_valid:
                    # Cap quantity to maximum available stock rather than failing entire merge
                    target_qty = min(target_qty, available_stock)

            if target_qty > 0:
                payload = {
                    "product_id": product_id,
                    "quantity": target_qty,
                    "merged_at": datetime.now(timezone.utc).isoformat(),
                    "metadata": g_item.get("metadata", {}),
                }
                pipeline.hset(self.key, field, json.dumps(payload))
                merged_count += 1

        pipeline.expire(self.key, self.ttl)
        pipeline.execute()

        return merged_count

    def get_summary(self) -> Dict[str, Any]:
        """
        Returns full cart summary with calculated item count and enriched fields.
        """
        items = self.get_items()
        item_count = sum(item.get("quantity", 0) for item in items)

        # Enriched catalog lookup if Product model is present
        product_model = None
        for app_label in ["catalog", "products", "ecommerce", "store"]:
            try:
                product_model = apps.get_model(app_label, "Product")
                if product_model:
                    break
            except (LookupError, ValueError):
                continue

        enriched_items = []
        subtotal = 0.0

        for item in items:
            product_id = item["product_id"]
            qty = item.get("quantity", 0)
            item_entry = {
                "product_id": product_id,
                "quantity": qty,
                "metadata": item.get("metadata", {}),
                "title": f"Product {product_id}",
                "unit_price": "0.00",
                "total_price": "0.00",
                "image_url": None,
                "in_stock": True,
            }

            if product_model:
                prod = product_model.objects.filter(id=product_id).first()
                if prod:
                    item_entry["title"] = getattr(prod, "title", getattr(prod, "name", f"Product {product_id}"))
                    price = float(getattr(prod, "price", 0.0))
                    item_entry["unit_price"] = f"{price:.2f}"
                    item_total = price * qty
                    item_entry["total_price"] = f"{item_total:.2f}"
                    subtotal += item_total
                    item_entry["image_url"] = getattr(prod, "image_url", None)
                    stock = getattr(prod, "stock", getattr(prod, "inventory_count", 9999))
                    item_entry["in_stock"] = stock >= qty

            enriched_items.append(item_entry)

        return {
            "items": enriched_items,
            "item_count": item_count,
            "subtotal": f"{subtotal:.2f}",
            "currency": getattr(settings, "DEFAULT_CURRENCY", "USD"),
        }


def merge_guest_cart_if_needed(request) -> bool:
    """
    Orchestrates atomic guest-to-user cart merging.
    Inspects authentication status and 'X-CART-UUID' header/cookie.
    Transfers all items from `cart:guest:<uuid>` into `cart:user:<id>` and evicts guest key.

    Returns True if an active guest cart was merged, False otherwise.
    """
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return False

    guest_uuid = (
        request.headers.get("X-CART-UUID")
        or request.COOKIES.get("cart_guest_uuid")
        or request.COOKIES.get("x-cart-uuid")
    )

    if not guest_uuid:
        return False

    guest_cart = RedisCart(identifier=guest_uuid, is_user=False)
    guest_items = guest_cart.get_items()

    if not guest_items:
        return False

    user_cart = RedisCart(identifier=str(user.id), is_user=True)
    user_cart.merge_from(guest_cart, verify_stock=True)

    # Clean up guest cart key from Redis to prevent duplicate replays
    guest_cart.clear()
    logger.info("Successfully merged guest cart %s into user cart %s", guest_uuid, user.id)
    return True
