# ============================================================
# StockFlow - Inventory Management System
# Part 3: Low Stock Alerts API Implementation
# Author: Vipul Ratan Neharkar
# Date: 6th April 2026
# ============================================================

# ============================================================
# ASSUMPTIONS MADE
# ============================================================

# Assumption 1: "Recent Sales Activity" = last 30 days
#   Any product with at least one sale transaction in the
#   last 30 days is considered active and included in alerts

# Assumption 2: Days Until Stockout Formula
#   avg_daily_sales = total_units_sold_in_last_30_days / 30
#   days_until_stockout = current_stock / avg_daily_sales

# Assumption 3: Low Stock Condition
#   current_stock < product.low_stock_threshold

# Assumption 4: Supplier Selection
#   Return preferred supplier (is_preferred = TRUE)
#   If no preferred supplier → return first available supplier
#   If no supplier linked at all → supplier field = null

# Assumption 5: Warehouse Scope
#   All active warehouses (is_active = TRUE) for the company
#   Inactive warehouses are excluded from alerts

# Assumption 6: Bundle Products
#   Included in alerts and treated same as standard products
#   Stock tracked at inventory level same as standard products

# Assumption 7: Authentication
#   @require_auth decorator validates token and sets g.current_user
#   g.current_user.company_id used for authorization check

# Assumption 8: Alerts Sorting
#   Sorted by days_until_stockout ascending
#   Most urgent (fewest days) appears first

# Assumption 9: reserved_qty not factored into stockout
#   Only current quantity used for simplicity
#   Future improvement: use (quantity - reserved_qty)

# Assumption 10: Sales window is fixed at 30 days
#   Future improvement: make it a configurable query parameter


# ============================================================
# IMPORTS
# ============================================================

from flask import jsonify, g
from sqlalchemy import func
from datetime import datetime, timedelta
from functools import wraps
from models import (
    Company,
    Warehouse,
    Product,
    Inventory,
    InventoryTransaction,
    ProductSupplier,
    Supplier
)
from database import db
import logging

logger = logging.getLogger(__name__)


# ============================================================
# CONSTANTS
# ============================================================

# Number of days to look back for sales activity
# Can be made configurable via query param in future
RECENT_SALES_WINDOW_DAYS = 30


# ============================================================
# HELPER DECORATORS
# ============================================================

def require_auth(f):
    """
    Authentication decorator.
    Validates the request token and sets g.current_user.

    In production this would:
    1. Extract JWT token from Authorization header
    2. Decode and validate the token
    3. Load the user from database and set g.current_user
    4. Return 401 if token is missing or invalid
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # TODO: Implement JWT validation
        # token = request.headers.get('Authorization', '').replace('Bearer ', '')
        # if not token:
        #     return jsonify({"error": "Authorization token required"}), 401
        # try:
        #     payload = jwt.decode(token, app.config['SECRET_KEY'])
        #     g.current_user = User.query.get(payload['user_id'])
        # except jwt.ExpiredSignatureError:
        #     return jsonify({"error": "Token has expired"}), 401
        # except jwt.InvalidTokenError:
        #     return jsonify({"error": "Invalid token"}), 401
        return f(*args, **kwargs)
    return decorated


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def authorize_company(company_id):
    """
    Checks that the authenticated user belongs to the
    requested company. Prevents cross-company data access.

    Args:
        company_id (int): Company ID from the URL parameter

    Returns:
        bool: True if authorized, False otherwise
    """
    return g.current_user.company_id == company_id


def get_preferred_supplier(product_id):
    """
    Returns the preferred supplier for a product.
    Falls back to first available supplier if none is preferred.
    Returns None if no supplier is linked.

    Args:
        product_id (int): Product ID to look up supplier for

    Returns:
        dict or None: Supplier data dictionary or None
    """
    # Try to get preferred supplier first
    supplier_link = (
        ProductSupplier.query
        .filter_by(product_id=product_id, is_preferred=True)
        .first()
    )

    # Fallback to first available supplier
    if not supplier_link:
        supplier_link = (
            ProductSupplier.query
            .filter_by(product_id=product_id)
            .first()
        )

    # No supplier linked at all
    if not supplier_link:
        return None

    supplier = supplier_link.supplier
    return {
        "id": supplier.id,
        "name": supplier.name,
        "contact_email": supplier.contact_email,
        "lead_time_days": supplier.lead_time_days,
        "min_order_qty": supplier_link.min_order_qty,
        "unit_cost": float(supplier_link.unit_cost) if supplier_link.unit_cost else None
    }


def calculate_days_until_stockout(current_stock, total_sold, window_days):
    """
    Calculates how many days until stock runs out
    based on average daily sales velocity.

    Args:
        current_stock (int): Current quantity in warehouse
        total_sold (int): Total units sold in the window period
        window_days (int): Number of days in the sales window

    Returns:
        int or None: Days until stockout, or None if no sales velocity
    """
    if total_sold == 0 or window_days == 0:
        return None

    avg_daily_sales = total_sold / window_days

    if avg_daily_sales == 0:
        return None

    return int(current_stock / avg_daily_sales)


# ============================================================
# API ENDPOINT
# ============================================================

@app.route('/api/companies/<int:company_id>/alerts/low-stock', methods=['GET'])
@require_auth
def get_low_stock_alerts(company_id):
    """
    Returns low-stock alerts for all active warehouses in a company.

    URL Parameters:
        company_id (int): The company to get alerts for

    Query Parameters (future improvements):
        warehouse_id (int): Filter by specific warehouse
        window (int): Sales activity window in days (default 30)
        limit (int): Max number of alerts to return
        offset (int): Pagination offset

    Business Rules Applied:
        - Only products with sales in last 30 days are included
        - Low stock = current_stock < product.low_stock_threshold
        - days_until_stockout = current_stock / avg_daily_sales
        - Alerts sorted by urgency (fewest days first)
        - Preferred supplier included for reordering reference
        - Inactive warehouses and products are excluded

    Returns:
        200 OK — alerts retrieved successfully
        403 Forbidden — user not authorized for this company
        404 Not Found — company does not exist
        500 Internal Server Error — query failed
    """

    # --------------------------------------------------------
    # Step 1: Authorization
    # Ensure authenticated user belongs to this company
    # Prevents users from accessing another company's alerts
    # --------------------------------------------------------
    if not authorize_company(company_id):
        return jsonify({
            "error": "You are not authorized to access this company's alerts"
        }), 403

    # --------------------------------------------------------
    # Step 2: Validate company exists
    # --------------------------------------------------------
    company = Company.query.get(company_id)
    if not company:
        return jsonify({
            "error": f"Company with id {company_id} not found"
        }), 404

    # --------------------------------------------------------
    # Step 3: Check company is active
    # --------------------------------------------------------
    if not company.is_active:
        return jsonify({
            "error": "This company account is inactive"
        }), 403

    # --------------------------------------------------------
    # Step 4: Define the sales activity window
    # Only look at transactions from the last 30 days
    # --------------------------------------------------------
    cutoff_date = datetime.utcnow() - timedelta(days=RECENT_SALES_WINDOW_DAYS)

    try:
        # ----------------------------------------------------
        # Step 5: Get all active warehouse IDs for this company
        # Inactive warehouses are excluded from alerts
        # ----------------------------------------------------
        warehouses = Warehouse.query.filter_by(
            company_id=company_id,
            is_active=True
        ).all()

        # Edge case: company exists but has no active warehouses
        if not warehouses:
            logger.info(f"Company {company_id} has no active warehouses")
            return jsonify({
                "alerts": [],
                "total_alerts": 0,
                "message": "No active warehouses found for this company"
            }), 200

        warehouse_ids = [w.id for w in warehouses]

        # ----------------------------------------------------
        # Step 6: Calculate total units sold per product
        # per warehouse in the last 30 days
        #
        # Only 'sale' type transactions are counted
        # change_qty is negative for sales so we use abs()
        # This subquery is joined later to filter only
        # products with recent sales activity
        # ----------------------------------------------------
        sales_subquery = (
            db.session.query(
                InventoryTransaction.product_id,
                InventoryTransaction.warehouse_id,
                func.sum(
                    func.abs(InventoryTransaction.change_qty)
                ).label('total_sold')
            )
            .filter(
                InventoryTransaction.warehouse_id.in_(warehouse_ids),
                InventoryTransaction.transaction_type == 'sale',
                InventoryTransaction.created_at >= cutoff_date
            )
            .group_by(
                InventoryTransaction.product_id,
                InventoryTransaction.warehouse_id
            )
            .subquery()
        )

        # ----------------------------------------------------
        # Step 7: Main query
        # Join inventory + product + warehouse + sales data
        # Filter only products below their low stock threshold
        # Inner join with sales_subquery ensures only products
        # with recent sales activity are included
        # ----------------------------------------------------
        results = (
            db.session.query(
                Inventory,
                Product,
                Warehouse,
                sales_subquery.c.total_sold
            )
            .join(
                Product,
                Product.id == Inventory.product_id
            )
            .join(
                Warehouse,
                Warehouse.id == Inventory.warehouse_id
            )
            .join(
                sales_subquery,
                (sales_subquery.c.product_id == Inventory.product_id) &
                (sales_subquery.c.warehouse_id == Inventory.warehouse_id)
            )
            .filter(
                Inventory.warehouse_id.in_(warehouse_ids),
                Product.is_active == True,
                Product.company_id == company_id,

                # Core low-stock condition
                Inventory.quantity < Product.low_stock_threshold
            )
            .all()
        )

    except Exception as e:
        # Log full error server-side for debugging
        # Return safe generic message to client
        logger.error(
            f"Low stock query failed for company {company_id}: {e}",
            exc_info=True
        )
        return jsonify({
            "error": "Failed to retrieve alerts. Please try again later."
        }), 500

    # --------------------------------------------------------
    # Step 8: Build the alerts list
    # Process each result row into a structured alert object
    # --------------------------------------------------------
    alerts = []

    for inventory, product, warehouse, total_sold in results:

        # Calculate days until stockout
        days_until_stockout = calculate_days_until_stockout(
            current_stock=inventory.quantity,
            total_sold=total_sold,
            window_days=RECENT_SALES_WINDOW_DAYS
        )

        # Skip products with no real sales velocity
        # This handles edge case where total_sold = 0
        # (should not happen due to inner join but added as safety)
        if days_until_stockout is None:
            continue

        # Get supplier information for reordering
        supplier_data = get_preferred_supplier(product.id)

        # Build the alert object
        alert = {
            "product_id": product.id,
            "product_name": product.name,
            "sku": product.sku,
            "product_type": product.product_type,
            "warehouse_id": warehouse.id,
            "warehouse_name": warehouse.name,
            "current_stock": inventory.quantity,
            "reserved_stock": inventory.reserved_qty,
            "available_stock": inventory.quantity - inventory.reserved_qty,
            "threshold": product.low_stock_threshold,
            "days_until_stockout": days_until_stockout,
            "avg_daily_sales": round(total_sold / RECENT_SALES_WINDOW_DAYS, 2),
            "total_sold_last_30_days": total_sold,
            "supplier": supplier_data
        }

        alerts.append(alert)

    # --------------------------------------------------------
    # Step 9: Sort alerts by urgency
    # Fewest days until stockout = most critical = first
    # --------------------------------------------------------
    alerts.sort(key=lambda x: x['days_until_stockout'])

    # --------------------------------------------------------
    # Step 10: Return final response
    # --------------------------------------------------------
    return jsonify({
        "company_id": company_id,
        "alerts": alerts,
        "total_alerts": len(alerts),
        "generated_at": datetime.utcnow().isoformat(),
        "sales_window_days": RECENT_SALES_WINDOW_DAYS
    }), 200


# ============================================================
# EDGE CASES HANDLED
# ============================================================

# 1. Company does not exist
#    → Returns 404 Not Found

# 2. Company account is inactive
#    → Returns 403 Forbidden

# 3. User accessing another company's data
#    → Returns 403 Forbidden

# 4. Company has no active warehouses
#    → Returns empty alerts list with 200 OK

# 5. Product has zero sales in last 30 days
#    → Excluded via inner join with sales_subquery

# 6. Division by zero in stockout calculation
#    → Handled in calculate_days_until_stockout()
#    → Returns None and product is skipped

# 7. Product has no supplier linked
#    → supplier field returned as null in response

# 8. Product has multiple suppliers
#    → Preferred supplier selected
#    → Falls back to first available if none preferred

# 9. Database query failure
#    → Returns 500 with logged error
#    → Safe generic message returned to client

# 10. Inactive products
#     → Filtered out via Product.is_active == True

# 11. Inactive warehouses
#     → Filtered out via Warehouse.is_active == True

# 12. Bundle products
#     → Included and treated same as standard products

# 13. reserved_qty greater than quantity
#     → available_stock could be negative
#     → Future fix: add CHECK constraint at DB level


# ============================================================
# FUTURE IMPROVEMENTS
# ============================================================

# 1. Caching
#    Cache results per company for 5 minutes using Redis
#    Avoids expensive joins on every request
#    Invalidate cache when inventory is updated

# 2. Pagination
#    Add limit and offset query parameters
#    Large companies with many products need pagination
#    Example: GET /alerts/low-stock?limit=20&offset=0

# 3. Configurable Sales Window
#    Make RECENT_SALES_WINDOW_DAYS a query parameter
#    Example: GET /alerts/low-stock?window=7
#    Different teams may need different windows

# 4. Warehouse Filter
#    Allow filtering alerts by specific warehouse
#    Example: GET /alerts/low-stock?warehouse_id=456

# 5. Proactive Alerting
#    Scheduled background job using Celery + Redis
#    Runs daily, checks low stock, sends email/webhook
#    No need to poll the endpoint manually

# 6. Weighted Sales Velocity
#    Recent weeks weighted more heavily than older weeks
#    More accurate stockout prediction than simple average

# 7. Factor in reserved_qty
#    Use (quantity - reserved_qty) for stockout calculation
#    Committed stock should not count as available

# 8. Reorder Suggestion
#    Calculate recommended reorder quantity based on
#    lead_time_days from supplier and avg daily sales
#    reorder_qty = avg_daily_sales * lead_time_days

# 9. Alert Severity Levels
#    critical: days_until_stockout <= 3
#    high: days_until_stockout <= 7
#    medium: days_until_stockout <= 14
#    low: days_until_stockout > 14
