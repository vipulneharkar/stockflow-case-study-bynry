# buggy_code.py
# Original code written by previous intern
# This code compiles but has multiple issues in production
# Issues are identified and fixed in fixed_code.py

from flask import request
from models import Product, Inventory
from database import db

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
    db.session.commit()
    # BUG 1: First commit here — not atomic
    # If the next block fails, product is saved but inventory is not
    
    # Update inventory count
    inventory = Inventory(
        product_id=product.id,
        warehouse_id=data['warehouse_id'],
        quantity=data['initial_quantity']
        # BUG 2: No validation — initial_quantity might not exist in request
    )
    
    db.session.add(inventory)
    db.session.commit()
    # BUG 3: Second commit — should be one single atomic transaction
    
    return {"message": "Product created", "product_id": product.id}
    # BUG 4: Returns 200 OK instead of 201 Created
    # BUG 5: No input validation anywhere
    # BUG 6: No SKU uniqueness check
    # BUG 7: No error handling / try-except block
    # BUG 8: warehouse_id not validated against database
    # BUG 9: No authentication or authorization check
    # BUG 10: Price not validated as a proper decimal value


# ============================================================
# ISSUES SUMMARY
# ============================================================

# Issue 1: No Input Validation
# data['name'], data['sku'], data['price'] etc. are accessed directly
# If any field is missing → KeyError → unhandled 500 error

# Issue 2: No SKU Uniqueness Check
# No check if SKU already exists in database
# Leads to duplicate SKUs breaking product lookups

# Issue 3: Two Separate Commits (Non-Atomic)
# db.session.commit() called twice
# If second commit fails → orphaned product with no inventory record

# Issue 4: No Error Handling
# No try/except block anywhere
# Any error = unhandled 500 with no useful message

# Issue 5: warehouse_id Not Validated
# No check that warehouse_id exists in database
# Leads to foreign key violation error instead of clean 404

# Issue 6: No Authentication or Authorization
# Any user can call this endpoint
# No check that user belongs to the company owning the warehouse

# Issue 7: Wrong HTTP Status Code
# Returns default 200 OK instead of 201 Created
# Breaks REST conventions and API client expectations

# Issue 8: Price Not Validated as Decimal
# Price could be a string or negative number
# Leads to data corruption in financial records
