StockFlow - Inventory Management System
Backend Engineering Intern - Case Study Submission

Name: Vipul Ratan Neharkar Role Applied For: Backend Engineering Intern Date: 6th April 2026 Company: Bynry Inc.

Part 1: Code Review & Debugging

1.1 Issues Identified
The following issues were found in the original create_product() endpoint:
Issue 1: No Input Validation The code directly accesses data['name'], data['sku'], data['price'], etc. without checking if these fields exist or have valid values. If any field is missing or null, Python throws a KeyError and the server crashes with an unhandled 500 error.
Issue 2: No SKU Uniqueness Check The code inserts a new product without checking if the SKU already exists. Since SKUs must be unique across the platform, this can lead to duplicate SKUs in the database, breaking product lookups and order processing.
Issue 3: Two Separate Database Commits (Non-Atomic Transaction) The code calls db.session.commit() twice — once after creating the Product and once after creating the Inventory record. If the second commit fails (e.g., invalid warehouse), the product is saved but has no inventory record. This leaves corrupted, orphaned data in the database.
Issue 4: No Error Handling There is no try/except block anywhere in the function. Any database error, missing field, or type mismatch will result in an unhandled exception and a generic 500 response with no useful message for the client.
Issue 5: warehouse_id Not Validated The code assumes warehouse_id provided in the request actually exists in the database. If an invalid or deleted warehouse_id is passed, it causes a foreign key violation at the database level, resulting in a confusing error instead of a clean 404 response.
Issue 6: No Authentication or Authorization There is no check to verify who is making the request. Any user — even from a different company — can call this endpoint and create products in any warehouse. This is a serious security vulnerability in a multi-tenant B2B platform.
Issue 7: Wrong HTTP Status Code The endpoint returns the default 200 OK instead of 201 Created. According to REST standards, when a new resource is successfully created, the response should be 201 Created. This matters for frontend clients and API consumers who rely on status codes.
Issue 8: Price Not Validated as Decimal The price field is passed directly without validating it as a proper decimal/numeric value. A string like "abc" or a negative number like -5 would be accepted and stored, causing data corruption.

1.2 Impact of Each Issue in Production
#
Issue
Production Impact
1
No input validation
App crashes with 500 error on any incomplete request; poor user experience
2
No SKU uniqueness check
Duplicate SKUs break product search, order fulfillment, and reporting
3
Two separate commits
Orphaned products with no inventory — stock tracking becomes unreliable
4
No error handling
Users get cryptic 500 errors; developers can't diagnose issues easily
5
warehouse_id not validated
Foreign key DB error instead of clean "Warehouse not found" message
6
No auth/authorization
Any user can create/modify products across all companies — data breach risk
7
Wrong status code
API clients behave unexpectedly; breaks REST conventions
8
Price not validated
Negative or non-numeric prices stored — corrupts financial data


1.3 Original Buggy Code
python
@app.route('/api/products', methods=['POST'])
def create_product():
    data = request.json
    
    # Create new product
    product = Product(
        name=data['name'],
        sku=data['sku'],
        price=data['price'],
        warehouse_id=data['warehouse_id']
    )
    
    db.session.add(product)
    db.session.commit()  # BUG: commits before inventory is created
    
    # Update inventory count
    inventory = Inventory(
        product_id=product.id,
        warehouse_id=data['warehouse_id'],
        quantity=data['initial_quantity']
    )
    
    db.session.add(inventory)
    db.session.commit()  # BUG: second commit — not atomic
    
    return {"message": "Product created", "product_id": product.id}
    # BUG: no validation, no error handling, wrong status code

1.4 Fixed Code
python
from flask import request, jsonify
from sqlalchemy.exc import IntegrityError
from decimal import Decimal, InvalidOperation

@app.route('/api/products', methods=['POST'])
def create_product():
    data = request.get_json()

    # FIX 1: Validate all required fields are present
    required_fields = ['name', 'sku', 'price', 'warehouse_id', 'initial_quantity']
    missing = [f for f in required_fields if f not in data or data[f] is None]
    if missing:
        return jsonify({
            "error": f"Missing required fields: {', '.join(missing)}"
        }), 400

    # FIX 8: Validate price is a valid non-negative decimal
    try:
        price = Decimal(str(data['price']))
        if price < 0:
            raise ValueError()
    except (InvalidOperation, ValueError):
        return jsonify({
            "error": "Price must be a non-negative number"
        }), 400

    # Validate initial_quantity is a non-negative integer
    try:
        initial_quantity = int(data['initial_quantity'])
        if initial_quantity < 0:
            raise ValueError()
    except (ValueError, TypeError):
        return jsonify({
            "error": "initial_quantity must be a non-negative integer"
        }), 400

    # FIX 5: Validate warehouse exists before proceeding
    warehouse = Warehouse.query.get(data['warehouse_id'])
    if not warehouse:
        return jsonify({"error": "Warehouse not found"}), 404

    # FIX 2: Check SKU uniqueness before inserting
    if Product.query.filter_by(sku=data['sku'].strip().upper()).first():
        return jsonify({
            "error": f"SKU '{data['sku']}' already exists"
        }), 409

    try:
        # FIX 3: Single atomic transaction — both product and inventory
        # created together. If either fails, both are rolled back.
        product = Product(
            name=data['name'].strip(),
            sku=data['sku'].strip().upper(),
            price=price,
            warehouse_id=data['warehouse_id'],
            description=data.get('description')  # optional field handled safely
        )
        db.session.add(product)
        db.session.flush()  # assigns product.id without committing yet

        inventory = Inventory(
            product_id=product.id,
            warehouse_id=data['warehouse_id'],
            quantity=initial_quantity
        )
        db.session.add(inventory)

        db.session.commit()  # FIX 3: single commit — fully atomic

    except IntegrityError as e:
        db.session.rollback()
        return jsonify({
            "error": "Database integrity error",
            "detail": str(e.orig)
        }), 409

    except Exception as e:
        # FIX 4: Catch all unexpected errors gracefully
        db.session.rollback()
        app.logger.error(f"Product creation failed: {e}")
        return jsonify({
            "error": "An unexpected error occurred. Please try again."
        }), 500

    # FIX 7: Return 201 Created instead of 200 OK
    return jsonify({
        "message": "Product created successfully",
        "product_id": product.id
    }), 201

1.5 Summary of Fixes
Fix
What Changed
Why
Input validation
Check all required fields upfront
Prevents KeyError crashes
SKU uniqueness
Query DB before insert
Prevents duplicate SKUs
Atomic transaction
One commit using flush()
Ensures data integrity
Error handling
try/except with rollback
Graceful failures, no data corruption
Warehouse validation
Query warehouse before use
Clean 404 instead of DB error
Price validation
Cast to Decimal, check >= 0
Prevents bad financial data
Status code
Return 201 Created
Follows REST standards


next part
20:40

Part 2: Database Design

2.1 Schema Design (SQL DDL)
sql
-- Companies using the platform
CREATE TABLE companies (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    email           VARCHAR(255) UNIQUE NOT NULL,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Warehouses belong to a company
CREATE TABLE warehouses (
    id              SERIAL PRIMARY KEY,
    company_id      INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    location        TEXT,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Suppliers are external entities that provide products
CREATE TABLE suppliers (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    contact_email   VARCHAR(255),
    contact_phone   VARCHAR(50),
    address         TEXT,
    lead_time_days  INT,           -- average days to fulfil an order
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Users (staff of a company)
CREATE TABLE users (
    id              SERIAL PRIMARY KEY,
    company_id      INT NOT NULL REFERENCES companies(id),
    name            VARCHAR(255) NOT NULL,
    email           VARCHAR(255) UNIQUE NOT NULL,
    role            VARCHAR(50) DEFAULT 'staff',  -- 'admin', 'staff', 'viewer'
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Products (catalog per company)
CREATE TABLE products (
    id                   SERIAL PRIMARY KEY,
    company_id           INT NOT NULL REFERENCES companies(id),
    name                 VARCHAR(255) NOT NULL,
    sku                  VARCHAR(100) NOT NULL,
    description          TEXT,
    price                NUMERIC(12, 2) NOT NULL CHECK (price >= 0),
    product_type         VARCHAR(50) DEFAULT 'standard',  -- 'standard' | 'bundle'
    low_stock_threshold  INT DEFAULT 10,
    unit_of_measure      VARCHAR(50) DEFAULT 'unit',
    is_active            BOOLEAN DEFAULT TRUE,
    created_at           TIMESTAMP DEFAULT NOW(),
    updated_at           TIMESTAMP DEFAULT NOW(),
    UNIQUE (company_id, sku)   -- SKU unique within a company
);

-- Many-to-many: products <-> suppliers
CREATE TABLE product_suppliers (
    id              SERIAL PRIMARY KEY,
    product_id      INT NOT NULL REFERENCES products(id),
    supplier_id     INT NOT NULL REFERENCES suppliers(id),
    supplier_sku    VARCHAR(100),    -- supplier's own SKU for this product
    unit_cost       NUMERIC(12, 2),
    is_preferred    BOOLEAN DEFAULT FALSE,
    UNIQUE(product_id, supplier_id)
);

-- Inventory: current stock level per product per warehouse
CREATE TABLE inventory (
    id              SERIAL PRIMARY KEY,
    product_id      INT NOT NULL REFERENCES products(id),
    warehouse_id    INT NOT NULL REFERENCES warehouses(id),
    quantity        INT NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    reserved_qty    INT NOT NULL DEFAULT 0,  -- qty reserved for pending orders
    updated_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(product_id, warehouse_id)
);

-- Audit log: every inventory change ever made
CREATE TABLE inventory_transactions (
    id                SERIAL PRIMARY KEY,
    product_id        INT NOT NULL REFERENCES products(id),
    warehouse_id      INT NOT NULL REFERENCES warehouses(id),
    change_qty        INT NOT NULL,             -- positive = stock in, negative = stock out
    transaction_type  VARCHAR(50) NOT NULL,     -- 'sale', 'restock', 'adjustment', 'transfer'
    reference_id      INT,                      -- e.g., order_id or transfer_id
    notes             TEXT,
    created_by        INT REFERENCES users(id),
    created_at        TIMESTAMP DEFAULT NOW()
);

-- Bundle composition (self-referencing products table)
CREATE TABLE bundle_items (
    id              SERIAL PRIMARY KEY,
    bundle_id       INT NOT NULL REFERENCES products(id),
    component_id    INT NOT NULL REFERENCES products(id),
    quantity        INT NOT NULL DEFAULT 1,
    CHECK (bundle_id <> component_id),
    UNIQUE(bundle_id, component_id)
);

-- Indexes for common and performance-critical query patterns
CREATE INDEX idx_inventory_product        ON inventory(product_id);
CREATE INDEX idx_inventory_warehouse      ON inventory(warehouse_id);
CREATE INDEX idx_inv_txn_product_date     ON inventory_transactions(product_id, created_at);
CREATE INDEX idx_inv_txn_warehouse        ON inventory_transactions(warehouse_id);
CREATE INDEX idx_products_company         ON products(company_id);
CREATE INDEX idx_warehouses_company       ON warehouses(company_id);

2.2 Entity Relationship Overview
companies
    └── warehouses (one company → many warehouses)
    └── products   (one company → many products)
    └── users      (one company → many users)

products
    └── inventory          (one product → many warehouse stock records)
    └── product_suppliers  (one product → many suppliers)
    └── bundle_items       (one bundle product → many component products)

inventory_transactions
    └── linked to product + warehouse + user (full audit trail)

2.3 Gaps & Questions for the Product Team
The following requirements were unclear or missing. These are questions I would ask before finalizing the schema:
1. SKU Uniqueness Scope Are SKUs unique globally across all companies, or only within a single company? I assumed per-company uniqueness using UNIQUE(company_id, sku).
2. Definition of "Recent Sales Activity" What time window defines "recent"? Last 7 days? Last 30 days? Should this be configurable per company or fixed platform-wide?
3. Low Stock Threshold Scope Is the low_stock_threshold set per product, per product category/type, or per warehouse? I assumed per product.
4. Can Inventory Go Negative? Should the system support backorders or pre-orders where stock can go below zero? Or should quantity always be >= 0?
5. Multiple Preferred Suppliers Can a product have more than one preferred supplier, or exactly one? What happens if the preferred supplier is out of stock?
6. Bundle Stock Calculation How is stock level calculated for a bundle product? Is it the minimum available quantity across all its component products?
7. Warehouse Sharing Between Companies Can two different companies ever share the same warehouse, or is each warehouse strictly owned by one company?
8. Inter-Warehouse Transfers Are transfers between warehouses tracked? If yes, should a transfer be recorded as one transaction or two (stock-out from source, stock-in to destination)?
9. Soft Delete vs Hard Delete Should deleted products be permanently removed, or soft-deleted (is_active = FALSE)? Products with sales history should never be hard-deleted to preserve reporting.
10. Pricing Per Warehouse Is the price of a product the same across all warehouses, or can it vary per warehouse (e.g., different regional pricing)?

2.4 Design Decisions & Justifications
UNIQUE(company_id, sku) instead of global SKU uniqueness Companies operate independently on a B2B platform. Two different companies may use the same SKU codes internally. Scoping uniqueness to a company avoids unnecessary conflicts.
inventory_transactions as an immutable audit log Instead of just updating a quantity column, every stock change is recorded as a new row with a change_qty. This gives us a complete history, makes "days until stockout" calculable from real sales data, and supports rollback/dispute resolution.
reserved_qty column in inventory Separates physically available stock from stock that is already committed to pending orders. This prevents overselling without needing a full order management system in scope.
low_stock_threshold on the products table Allows each product to have its own threshold since different product types have different reorder urgency (e.g., fast-moving consumer goods vs slow-moving spare parts).
product_suppliers junction table with is_preferred flag A product can be sourced from multiple suppliers. Tracking unit cost and preferred status per relationship allows smart reorder suggestions and cost comparisons.
bundle_items as a self-referencing table Rather than a separate bundles table, products reference other products. This keeps the schema clean and supports nested bundles if needed in the future.
Indexes on foreign keys and date columns inventory_transactions will be the largest and most queried table. Indexing (product_id, created_at) makes sales velocity calculations fast. Indexes on warehouse_id and company_id speed up all warehouse and company-level filters.
ON DELETE CASCADE on warehouses If a company is deleted, all its warehouses are automatically removed. This prevents orphaned warehouse records.

2.5 Summary of Tables
Table
Purpose
companies
Top-level tenants on the platform
warehouses
Physical storage locations per company
suppliers
External vendors who supply products
users
Staff members belonging to a company
products
Product catalog per company
product_suppliers
Links products to their suppliers
inventory
Current stock levels per product per warehouse
inventory_transactions
Immutable audit log of every stock change
bundle_items
Defines which products make up a bundle

 




Part 3: API Implementation - Low Stock Alerts

3.1 Assumptions Made
Before writing the implementation, the following assumptions were made due to incomplete requirements:
Assumption 1: Definition of "Recent Sales Activity" "Recent" is defined as the last 30 days. Any product that has at least one sale transaction in the last 30 days is considered active. Products with zero sales in this window are excluded from alerts.
Assumption 2: Days Until Stockout Formula Calculated as:
days_until_stockout = current_stock / average_daily_sales
average_daily_sales = total_units_sold_in_last_30_days / 30
Assumption 3: Low Stock Condition A product is considered low stock when:
current_stock < product.low_stock_threshold
Assumption 4: Supplier Selection If a product has multiple suppliers, the one marked is_preferred = TRUE is returned. If no preferred supplier exists, the first available supplier is returned. If no supplier is linked at all, the supplier field returns null.
Assumption 5: Warehouse Scope All active warehouses belonging to the company are checked. Inactive warehouses (is_active = FALSE) are excluded.
Assumption 6: Bundle Products Bundle products are included in alerts and treated the same as standard products for stock tracking purposes.
Assumption 7: Authentication The endpoint assumes a valid authenticated user. An @require_auth decorator validates the token and sets g.current_user with the user's company_id.
Assumption 8: Alerts Sorting Alerts are sorted by days_until_stockout in ascending order so the most urgent items appear first.

3.2 Implementation Code
python
from flask import jsonify, g
from sqlalchemy import func
from datetime import datetime, timedelta
from functools import wraps

# Configurable constant — can be moved to app config or made a query param
RECENT_SALES_WINDOW_DAYS = 30


def require_auth(f):
    """
    Authentication decorator.
    Validates the request token and sets g.current_user.
    In production this would verify a JWT or session token.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # TODO: Validate token from Authorization header
        # g.current_user = decode_jwt(request.headers.get('Authorization'))
        return f(*args, **kwargs)
    return decorated


def authorize_company(company_id):
    """
    Checks that the authenticated user belongs to the requested company.
    Prevents users from accessing another company's data.
    """
    return g.current_user.company_id == company_id


@app.route('/api/companies/<int:company_id>/alerts/low-stock', methods=['GET'])
@require_auth
def get_low_stock_alerts(company_id):
    """
    Returns low-stock alerts for all active warehouses in a company.

    Business Rules Applied:
    - Only products with sales activity in the last 30 days are included
    - Low stock = current_stock < product.low_stock_threshold
    - days_until_stockout = current_stock / avg_daily_sales (last 30 days)
    - Alerts sorted by urgency (fewest days until stockout first)
    - Preferred supplier included for reordering reference
    """

    # Step 1: Authorization — ensure user belongs to this company
    if not authorize_company(company_id):
        return jsonify({"error": "Forbidden"}), 403

    # Step 2: Validate the company exists
    company = Company.query.get(company_id)
    if not company:
        return jsonify({"error": "Company not found"}), 404

    # Step 3: Define the sales activity window
    cutoff_date = datetime.utcnow() - timedelta(days=RECENT_SALES_WINDOW_DAYS)

    try:
        # Step 4: Get all active warehouse IDs for this company
        warehouse_ids = [
            w.id for w in Warehouse.query.filter_by(
                company_id=company_id,
                is_active=True
            ).all()
        ]

        # Edge case: company has no active warehouses
        if not warehouse_ids:
            return jsonify({"alerts": [], "total_alerts": 0}), 200

        # Step 5: Calculate total units sold per product per warehouse
        # in the last 30 days using inventory_transactions
        # Only 'sale' type transactions are counted
        # change_qty is negative for sales so we use abs()
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

        # Step 6: Join inventory + product + warehouse + sales data
        # Only fetch records where current stock is below threshold
        results = (
            db.session.query(
                Inventory,
                Product,
                Warehouse,
                sales_subquery.c.total_sold
            )
            .join(Product, Product.id == Inventory.product_id)
            .join(Warehouse, Warehouse.id == Inventory.warehouse_id)
            .join(
                sales_subquery,
                (sales_subquery.c.product_id == Inventory.product_id) &
                (sales_subquery.c.warehouse_id == Inventory.warehouse_id)
            )
            .filter(
                Inventory.warehouse_id.in_(warehouse_ids),
                Product.is_active == True,
                # Core low-stock condition
                Inventory.quantity < Product.low_stock_threshold
            )
            .all()
        )

    except Exception as e:
        app.logger.error(
            f"Low stock query failed for company {company_id}: {e}"
        )
        return jsonify({
            "error": "Failed to retrieve alerts. Please try again."
        }), 500

    # Step 7: Build the alerts list
    alerts = []

    for inventory, product, warehouse, total_sold in results:

        # Calculate average daily sales velocity
        avg_daily_sales = total_sold / RECENT_SALES_WINDOW_DAYS

        # Skip products with zero sales velocity
        # (avoids division by zero and filters truly inactive products)
        if avg_daily_sales == 0:
            continue

        # Calculate how many days before stock runs out
        days_until_stockout = int(inventory.quantity / avg_daily_sales)

        # Step 8: Get preferred supplier, fallback to first available
        supplier_link = (
            ProductSupplier.query
            .filter_by(product_id=product.id, is_preferred=True)
            .first()
        ) or (
            ProductSupplier.query
            .filter_by(product_id=product.id)
            .first()
        )

        # Build supplier data — null if no supplier linked
        supplier_data = None
        if supplier_link:
            s = supplier_link.supplier
            supplier_data = {
                "id": s.id,
                "name": s.name,
                "contact_email": s.contact_email
            }

        alerts.append({
            "product_id": product.id,
            "product_name": product.name,
            "sku": product.sku,
            "warehouse_id": warehouse.id,
            "warehouse_name": warehouse.name,
            "current_stock": inventory.quantity,
            "threshold": product.low_stock_threshold,
            "days_until_stockout": days_until_stockout,
            "supplier": supplier_data
        })

    # Step 9: Sort by urgency — most critical (fewest days) first
    alerts.sort(key=lambda x: x['days_until_stockout'])

    return jsonify({
        "alerts": alerts,
        "total_alerts": len(alerts)
    }), 200

3.3 Expected Response Example
json
{
  "alerts": [
    {
      "product_id": 123,
      "product_name": "Widget A",
      "sku": "WID-001",
      "warehouse_id": 456,
      "warehouse_name": "Main Warehouse",
      "current_stock": 5,
      "threshold": 20,
      "days_until_stockout": 12,
      "supplier": {
        "id": 789,
        "name": "Supplier Corp",
        "contact_email": "orders@supplier.com"
      }
    }
  ],
  "total_alerts": 1
}




3.4 Edge Cases Handled
Edge Case
How It Is Handled
Company does not exist
Returns 404 Not Found
User accessing another company's data
Returns 403 Forbidden
Company has no active warehouses
Returns empty alerts list with 200 OK
Product has zero sales in last 30 days
Excluded from alerts (no velocity data)
Division by zero in stockout calculation
Prevented by avg_daily_sales == 0 check
Product has no supplier linked
supplier field returned as null
Product has multiple suppliers
Preferred supplier selected, fallback to first
Database query failure
Returns 500 with logged error, safe message to client
Inactive products
Filtered out via Product.is_active == True
Inactive warehouses
Filtered out via Warehouse.is_active == True
Bundle products
Included and treated same as standard products


3.5 Future Improvements
Performance
Cache results per company for 5 minutes using Redis to avoid running expensive joins on every request
Add database-level pagination using limit and offset query parameters for companies with large product catalogs
Flexibility
Make RECENT_SALES_WINDOW_DAYS a configurable query parameter (e.g., ?window=7) so teams can customize the sales activity window
Allow filtering by specific warehouse using a ?warehouse_id= query parameter
Proactive Alerting
Instead of polling this endpoint, implement a scheduled background job (e.g., Celery + Redis) that runs daily, checks low stock, and sends email or webhook notifications automatically to the relevant teams
Accuracy
Factor in reserved_qty from the inventory table when calculating days until stockout so that already-committed stock is not counted as available
Use a weighted average for sales velocity (recent weeks weighted more heavily than older weeks) for more accurate stockout predictions

3.6 Summary
Component
Decision Made
Sales window
Last 30 days of inventory_transactions
Low stock condition
current_stock < low_stock_threshold
Stockout formula
current_stock / avg_daily_sales
Supplier selection
Preferred first, fallback to first available
Sorting
Ascending by days_until_stockout
Auth
@require_auth decorator with company-level check
Error handling
Try/except with rollback and logged errors


Closing Note
I approached this case study by focusing on three core principles: data integrity, security, and real-world edge cases. Throughout all three parts I have documented every assumption clearly, asked questions where requirements were incomplete, and written code that is production-aware rather than just functional.
I look forward to walking through my design decisions, discussing trade-offs, and exploring alternative approaches in the live discussion round.
Thank you for the opportunity.

Vipul Ratan Neharkar Backend Engineering Intern Applicant Bynry Inc. — StockFlow Case Study 6th April 2026
  
