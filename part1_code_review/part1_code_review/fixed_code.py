# fixed_code.py
# Corrected version of the buggy create_product endpoint
# All issues identified in buggy_code.py have been fixed
# Each fix is clearly commented with the issue it resolves

from flask import request, jsonify
from sqlalchemy.exc import IntegrityError
from decimal import Decimal, InvalidOperation
from models import Product, Inventory, Warehouse
from database import db
from auth import require_auth, authorize_warehouse
import logging

logger = logging.getLogger(__name__)


@app.route('/api/products', methods=['POST'])
@require_auth  # FIX 9: Added authentication decorator
def create_product():
    """
    Creates a new product and its initial inventory record.

    Request Body (JSON):
    {
        "name": "Widget A",               (required)
        "sku": "WID-001",                 (required, must be unique)
        "price": 19.99,                   (required, must be non-negative decimal)
        "warehouse_id": 1,                (required, must exist in database)
        "initial_quantity": 100,          (required, must be non-negative integer)
        "description": "A great widget"   (optional)
    }

    Returns:
        201 Created — product created successfully
        400 Bad Request — missing or invalid fields
        403 Forbidden — user not authorized for this warehouse
        404 Not Found — warehouse does not exist
        409 Conflict — SKU already exists or DB integrity error
        500 Internal Server Error — unexpected error
    """

    data = request.get_json()

    # ----------------------------------------------------------------
    # FIX 1: Validate all required fields are present
    # Original code accessed fields directly causing KeyError on missing fields
    # ----------------------------------------------------------------
    required_fields = ['name', 'sku', 'price', 'warehouse_id', 'initial_quantity']
    missing = [f for f in required_fields if f not in data or data[f] is None]
    if missing:
        return jsonify({
            "error": f"Missing required fields: {', '.join(missing)}"
        }), 400

    # ----------------------------------------------------------------
    # FIX 8: Validate price is a valid non-negative decimal
    # Original code accepted strings or negative numbers without checks
    # ----------------------------------------------------------------
    try:
        price = Decimal(str(data['price']))
        if price < 0:
            raise ValueError("Price cannot be negative")
    except (InvalidOperation, ValueError) as e:
        return jsonify({
            "error": "Price must be a non-negative number",
            "detail": str(e)
        }), 400

    # ----------------------------------------------------------------
    # Validate initial_quantity is a non-negative integer
    # ----------------------------------------------------------------
    try:
        initial_quantity = int(data['initial_quantity'])
        if initial_quantity < 0:
            raise ValueError("Quantity cannot be negative")
    except (ValueError, TypeError) as e:
        return jsonify({
            "error": "initial_quantity must be a non-negative integer",
            "detail": str(e)
        }), 400

    # ----------------------------------------------------------------
    # Validate name is not empty
    # ----------------------------------------------------------------
    if not data['name'].strip():
        return jsonify({
            "error": "Product name cannot be empty"
        }), 400

    # ----------------------------------------------------------------
    # Validate SKU is not empty
    # ----------------------------------------------------------------
    if not data['sku'].strip():
        return jsonify({
            "error": "SKU cannot be empty"
        }), 400

    # ----------------------------------------------------------------
    # FIX 5: Validate warehouse exists before proceeding
    # Original code assumed warehouse_id was valid causing DB errors
    # ----------------------------------------------------------------
    warehouse = Warehouse.query.get(data['warehouse_id'])
    if not warehouse:
        return jsonify({
            "error": f"Warehouse with id {data['warehouse_id']} not found"
        }), 404

    # ----------------------------------------------------------------
    # FIX 9: Authorization check
    # Ensure the authenticated user belongs to the company
    # that owns this warehouse
    # ----------------------------------------------------------------
    if not authorize_warehouse(warehouse):
        return jsonify({
            "error": "You are not authorized to add products to this warehouse"
        }), 403

    # ----------------------------------------------------------------
    # FIX 2: Check SKU uniqueness before inserting
    # Original code had no uniqueness check causing duplicate SKUs
    # ----------------------------------------------------------------
    normalized_sku = data['sku'].strip().upper()
    if Product.query.filter_by(sku=normalized_sku).first():
        return jsonify({
            "error": f"SKU '{normalized_sku}' already exists in the system"
        }), 409

    # ----------------------------------------------------------------
    # FIX 3 & 4: Single atomic transaction with full error handling
    # Original code had two separate commits and no error handling
    # Using db.session.flush() to get product.id before committing
    # If anything fails, db.session.rollback() undoes everything
    # ----------------------------------------------------------------
    try:
        # Create the product
        product = Product(
            name=data['name'].strip(),
            sku=normalized_sku,
            price=price,
            warehouse_id=data['warehouse_id'],
            description=data.get('description', '').strip()  # optional field
        )
        db.session.add(product)

        # flush() assigns product.id from DB sequence
        # without committing the transaction yet
        db.session.flush()

        # Create the inventory record linked to the product
        inventory = Inventory(
            product_id=product.id,
            warehouse_id=data['warehouse_id'],
            quantity=initial_quantity,
            reserved_qty=0
        )
        db.session.add(inventory)

        # Single commit — both product and inventory saved atomically
        # If this fails, nothing is saved (no orphaned records)
        db.session.commit()

    except IntegrityError as e:
        # Handles DB-level constraint violations
        db.session.rollback()
        logger.error(f"Integrity error creating product: {e}")
        return jsonify({
            "error": "Database integrity error",
            "detail": str(e.orig)
        }), 409

    except Exception as e:
        # Handles any other unexpected errors
        db.session.rollback()
        logger.error(f"Unexpected error creating product: {e}")
        return jsonify({
            "error": "An unexpected error occurred. Please try again."
        }), 500

    # ----------------------------------------------------------------
    # FIX 7: Return 201 Created instead of default 200 OK
    # REST standard for successful resource creation is 201
    # ----------------------------------------------------------------
    return jsonify({
        "message": "Product created successfully",
        "product_id": product.id,
        "sku": product.sku,
        "warehouse_id": data['warehouse_id']
    }), 201


# ============================================================
# FIXES SUMMARY
# ============================================================

# Fix 1: Input Validation
# Added check for all required fields upfront
# Returns 400 with clear message if any field is missing

# Fix 2: SKU Uniqueness Check
# Query DB before insert to check if SKU already exists
# Returns 409 Conflict if duplicate found
# Also normalized SKU to uppercase for consistency

# Fix 3: Atomic Transaction
# Replaced two separate commits with one single commit
# Used db.session.flush() to get product.id before committing
# If inventory creation fails, product creation is also rolled back

# Fix 4: Error Handling
# Wrapped entire DB operation in try/except
# IntegrityError caught separately for DB constraint violations
# All exceptions trigger db.session.rollback() to prevent dirty data
# Errors logged server-side, safe message returned to client

# Fix 5: Warehouse Validation
# Query warehouse before use
# Returns clean 404 if warehouse not found

# Fix 6: Name and SKU Empty String Validation
# Added strip() checks to prevent empty strings being saved

# Fix 7: HTTP Status Code
# Changed return to 201 Created (correct REST standard)
# Added more useful fields in response body

# Fix 8: Price Validation
# Cast price to Decimal with proper error handling
# Rejects negative values and non-numeric strings

# Fix 9: Authentication and Authorization
# Added @require_auth decorator for token validation
# Added authorize_warehouse() check to prevent cross-company access
