-- ============================================================
-- StockFlow - Inventory Management System
-- Database Schema Design
-- Author: Vipul Ratan Neharkar
-- Date: 6th April 2026
-- ============================================================

-- ============================================================
-- DESIGN DECISIONS
-- ============================================================

-- 1. SKU uniqueness is scoped per company (not global)
--    Companies operate independently on a B2B platform
--    Two companies may use the same SKU codes internally

-- 2. inventory_transactions is an immutable audit log
--    Every stock change is recorded as a new row
--    Never update quantity directly — always insert a transaction
--    This gives full history and supports stockout calculations

-- 3. reserved_qty in inventory separates available stock
--    from stock committed to pending orders
--    Prevents overselling without a full order management system

-- 4. low_stock_threshold is per product
--    Different products have different reorder urgency
--    Fast-moving goods vs slow-moving spare parts

-- 5. product_suppliers junction table with is_preferred flag
--    A product can be sourced from multiple suppliers
--    Tracks cost and preferred status per relationship

-- 6. bundle_items is a self-referencing products table
--    Keeps schema clean and supports nested bundles in future

-- 7. Indexes added on all foreign keys and date columns
--    inventory_transactions will be the largest table
--    Indexing (product_id, created_at) makes velocity calculations fast

-- 8. Soft delete used instead of hard delete (is_active flag)
--    Products with sales history should never be hard deleted
--    Preserves reporting and audit trail integrity

-- ============================================================
-- DROP TABLES (for clean re-runs during development)
-- ============================================================

DROP TABLE IF EXISTS bundle_items CASCADE;
DROP TABLE IF EXISTS inventory_transactions CASCADE;
DROP TABLE IF EXISTS inventory CASCADE;
DROP TABLE IF EXISTS product_suppliers CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TABLE IF EXISTS suppliers CASCADE;
DROP TABLE IF EXISTS warehouses CASCADE;
DROP TABLE IF EXISTS companies CASCADE;


-- ============================================================
-- TABLE: companies
-- Top-level tenants on the platform
-- Every warehouse, product, and user belongs to a company
-- ============================================================

CREATE TABLE companies (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    email           VARCHAR(255) UNIQUE NOT NULL,
    phone           VARCHAR(50),
    address         TEXT,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);


-- ============================================================
-- TABLE: warehouses
-- Physical storage locations owned by a company
-- A company can have multiple warehouses
-- ============================================================

CREATE TABLE warehouses (
    id              SERIAL PRIMARY KEY,
    company_id      INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    location        TEXT,
    city            VARCHAR(100),
    country         VARCHAR(100),
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);


-- ============================================================
-- TABLE: suppliers
-- External vendors who supply products to companies
-- A supplier can supply products to multiple companies
-- ============================================================

CREATE TABLE suppliers (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    contact_email   VARCHAR(255),
    contact_phone   VARCHAR(50),
    address         TEXT,
    city            VARCHAR(100),
    country         VARCHAR(100),
    lead_time_days  INT,            -- average days to fulfil a reorder
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);


-- ============================================================
-- TABLE: users
-- Staff members belonging to a company
-- Role controls what actions they can perform
-- ============================================================

CREATE TABLE users (
    id              SERIAL PRIMARY KEY,
    company_id      INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    email           VARCHAR(255) UNIQUE NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    role            VARCHAR(50) DEFAULT 'staff',    -- 'admin', 'staff', 'viewer'
    is_active       BOOLEAN DEFAULT TRUE,
    last_login      TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);


-- ============================================================
-- TABLE: products
-- Product catalog scoped per company
-- SKU is unique within a company (not globally)
-- product_type distinguishes standard vs bundle products
-- ============================================================

CREATE TABLE products (
    id                   SERIAL PRIMARY KEY,
    company_id           INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name                 VARCHAR(255) NOT NULL,
    sku                  VARCHAR(100) NOT NULL,
    description          TEXT,
    price                NUMERIC(12, 2) NOT NULL CHECK (price >= 0),
    product_type         VARCHAR(50) DEFAULT 'standard',    -- 'standard' | 'bundle'
    low_stock_threshold  INT NOT NULL DEFAULT 10,           -- alert when stock goes below this
    unit_of_measure      VARCHAR(50) DEFAULT 'unit',        -- 'unit', 'kg', 'litre', etc.
    weight_kg            NUMERIC(8, 3),                     -- optional, for shipping calculations
    is_active            BOOLEAN DEFAULT TRUE,
    created_by           INT REFERENCES users(id),
    created_at           TIMESTAMP DEFAULT NOW(),
    updated_at           TIMESTAMP DEFAULT NOW(),

    -- SKU must be unique within a company
    UNIQUE (company_id, sku)
);


-- ============================================================
-- TABLE: product_suppliers
-- Many-to-many relationship between products and suppliers
-- A product can have multiple suppliers
-- is_preferred flags the default supplier for reordering
-- ============================================================

CREATE TABLE product_suppliers (
    id              SERIAL PRIMARY KEY,
    product_id      INT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    supplier_id     INT NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    supplier_sku    VARCHAR(100),       -- supplier's own product code
    unit_cost       NUMERIC(12, 2),     -- cost price from this supplier
    min_order_qty   INT DEFAULT 1,      -- minimum order quantity
    is_preferred    BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW(),

    -- A supplier can only be linked once per product
    UNIQUE(product_id, supplier_id)
);


-- ============================================================
-- TABLE: inventory
-- Current stock level per product per warehouse
-- reserved_qty tracks stock committed to pending orders
-- available stock = quantity - reserved_qty
-- ============================================================

CREATE TABLE inventory (
    id              SERIAL PRIMARY KEY,
    product_id      INT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    warehouse_id    INT NOT NULL REFERENCES warehouses(id) ON DELETE CASCADE,
    quantity        INT NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    reserved_qty    INT NOT NULL DEFAULT 0 CHECK (reserved_qty >= 0),
    updated_at      TIMESTAMP DEFAULT NOW(),

    -- One inventory record per product per warehouse
    UNIQUE(product_id, warehouse_id)
);


-- ============================================================
-- TABLE: inventory_transactions
-- Immutable audit log of every stock change
-- Never update inventory.quantity directly
-- Always insert a transaction and update inventory accordingly
-- transaction_type values:
--   'sale'       — stock reduced due to a customer order
--   'restock'    — stock increased due to a supplier delivery
--   'adjustment' — manual correction by warehouse staff
--   'transfer'   — stock moved between warehouses
--   'return'     — customer return increasing stock
-- ============================================================

CREATE TABLE inventory_transactions (
    id                SERIAL PRIMARY KEY,
    product_id        INT NOT NULL REFERENCES products(id),
    warehouse_id      INT NOT NULL REFERENCES warehouses(id),
    change_qty        INT NOT NULL,             -- positive = stock in, negative = stock out
    transaction_type  VARCHAR(50) NOT NULL,     -- see values above
    reference_id      INT,                      -- links to order_id, transfer_id, etc.
    notes             TEXT,
    created_by        INT REFERENCES users(id),
    created_at        TIMESTAMP DEFAULT NOW(),

    -- Ensure transaction_type is always a valid value
    CHECK (transaction_type IN ('sale', 'restock', 'adjustment', 'transfer', 'return'))
);


-- ============================================================
-- TABLE: bundle_items
-- Defines which products make up a bundle product
-- bundle_id references the parent bundle product
-- component_id references a child component product
-- A bundle cannot contain itself (CHECK constraint)
-- ============================================================

CREATE TABLE bundle_items (
    id              SERIAL PRIMARY KEY,
    bundle_id       INT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    component_id    INT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    quantity        INT NOT NULL DEFAULT 1 CHECK (quantity > 0),
    created_at      TIMESTAMP DEFAULT NOW(),

    -- A bundle cannot reference itself
    CHECK (bundle_id <> component_id),

    -- Same component cannot appear twice in same bundle
    UNIQUE(bundle_id, component_id)
);


-- ============================================================
-- INDEXES
-- Added for performance on most common query patterns
-- ============================================================

-- Products
CREATE INDEX idx_products_company
    ON products(company_id);

CREATE INDEX idx_products_sku
    ON products(sku);

CREATE INDEX idx_products_type
    ON products(product_type);

-- Warehouses
CREATE INDEX idx_warehouses_company
    ON warehouses(company_id);

-- Inventory
CREATE INDEX idx_inventory_product
    ON inventory(product_id);

CREATE INDEX idx_inventory_warehouse
    ON inventory(warehouse_id);

-- Inventory Transactions (most critical — largest table)
CREATE INDEX idx_inv_txn_product_date
    ON inventory_transactions(product_id, created_at);

CREATE INDEX idx_inv_txn_warehouse
    ON inventory_transactions(warehouse_id);

CREATE INDEX idx_inv_txn_type
    ON inventory_transactions(transaction_type);

CREATE INDEX idx_inv_txn_reference
    ON inventory_transactions(reference_id);

-- Product Suppliers
CREATE INDEX idx_product_suppliers_product
    ON product_suppliers(product_id);

CREATE INDEX idx_product_suppliers_supplier
    ON product_suppliers(supplier_id);

-- Users
CREATE INDEX idx_users_company
    ON users(company_id);


-- ============================================================
-- SAMPLE DATA (for testing purposes)
-- ============================================================

-- Insert a sample company
INSERT INTO companies (name, email, phone)
VALUES ('Demo Corp', 'admin@democorp.com', '+91-9876543210');

-- Insert sample warehouses
INSERT INTO warehouses (company_id, name, location, city, country)
VALUES
    (1, 'Main Warehouse', '123 Industrial Area', 'Mumbai', 'India'),
    (1, 'North Warehouse', '456 Storage Lane', 'Delhi', 'India');

-- Insert a sample supplier
INSERT INTO suppliers (name, contact_email, contact_phone, lead_time_days)
VALUES ('Supplier Corp', 'orders@suppliercorp.com', '+91-9123456789', 7);

-- Insert a sample admin user
INSERT INTO users (company_id, name, email, password_hash, role)
VALUES (1, 'Admin User', 'admin@democorp.com', 'hashed_password_here', 'admin');

-- Insert sample products
INSERT INTO products (company_id, name, sku, price, product_type, low_stock_threshold)
VALUES
    (1, 'Widget A', 'WID-001', 19.99, 'standard', 20),
    (1, 'Widget B', 'WID-002', 34.99, 'standard', 15),
    (1, 'Widget Bundle', 'WID-BUNDLE-001', 49.99, 'bundle', 10);

-- Insert inventory records
INSERT INTO inventory (product_id, warehouse_id, quantity, reserved_qty)
VALUES
    (1, 1, 5, 0),    -- Widget A in Main Warehouse — LOW STOCK
    (2, 1, 50, 5),   -- Widget B in Main Warehouse — OK
    (1, 2, 8, 0),    -- Widget A in North Warehouse — LOW STOCK
    (3, 1, 3, 0);    -- Widget Bundle in Main Warehouse — LOW STOCK

-- Link product to supplier
INSERT INTO product_suppliers (product_id, supplier_id, unit_cost, is_preferred)
VALUES
    (1, 1, 10.00, TRUE),
    (2, 1, 20.00, TRUE);

-- Insert sample inventory transactions
INSERT INTO inventory_transactions
    (product_id, warehouse_id, change_qty, transaction_type, notes)
VALUES
    (1, 1, 100, 'restock', 'Initial stock'),
    (1, 1, -10, 'sale', 'Order #1001'),
    (1, 1, -15, 'sale', 'Order #1002'),
    (1, 1, -20, 'sale', 'Order #1003'),
    (1, 1, -25, 'sale', 'Order #1004'),
    (1, 1, -25, 'sale', 'Order #1005');

-- Define bundle composition
INSERT INTO bundle_items (bundle_id, component_id, quantity)
VALUES
    (3, 1, 1),    -- Bundle contains 1x Widget A
    (3, 2, 1);    -- Bundle contains 1x Widget B


-- ============================================================
-- GAPS AND QUESTIONS FOR PRODUCT TEAM
-- ============================================================

-- 1. Are SKUs unique globally or per company?
--    Assumed: per company using UNIQUE(company_id, sku)

-- 2. What defines "recent sales activity"?
--    Last 7 days? 30 days? Should it be configurable?

-- 3. Is low_stock_threshold per product, per category, or per warehouse?
--    Assumed: per product

-- 4. Can inventory go negative for backorders or pre-orders?
--    Assumed: no — CHECK (quantity >= 0)

-- 5. Can a product have multiple preferred suppliers?
--    Assumed: one preferred, others as fallback

-- 6. How is bundle stock calculated?
--    Is it the minimum available across all component products?

-- 7. Can two companies share the same warehouse?
--    Assumed: no — warehouse belongs to one company only

-- 8. Are transfers between warehouses one transaction or two?
--    Assumed: two transactions (stock-out + stock-in)

-- 9. Should deleted products be soft-deleted or hard-deleted?
--    Assumed: soft-delete using is_active = FALSE

-- 10. Is pricing per warehouse or global per product?
--     Assumed: global per product
