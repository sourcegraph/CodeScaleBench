-- -------------------------------------------------------------------------------------------------
-- CommerceSphere Enterprise Suite
-- Flyway Migration: V1__Initial_Schema.sql
--
-- Description:
--   Creates the initial relational schema required for the unified CommerceSphere platform.
--   The schema embraces PostgreSQL-specific features (e.g., UUID, JSONB) and follows strict
--   referential integrity rules to guarantee audit-grade traceability and data correctness.
--
--   All tables are created in the dedicated “commerce” schema to avoid clashes with existing
--   databases on the same server instance.
--
--   NOTE:
--   • All primary keys are UUIDs generated in the application layer to ensure cross-node
--     uniqueness in clustered deployments.
--   • Timestamps are in UTC and set by the database to provide consistent audit data.
--   • Soft-deletion is implemented via the “deleted_at” column, allowing point-in-time recovery.
-- -------------------------------------------------------------------------------------------------

-- -------------------------------------------------------------------------------------------------
-- 1. SCHEMA & EXTENSIONS
-- -------------------------------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE SCHEMA IF NOT EXISTS commerce AUTHORIZATION CURRENT_USER;

SET search_path TO commerce;

-- -------------------------------------------------------------------------------------------------
-- 2. ENUM TYPES
-- -------------------------------------------------------------------------------------------------
CREATE TYPE payment_status AS ENUM (
    'INITIATED',
    'AUTHORIZED',
    'CAPTURED',
    'DECLINED',
    'REFUNDED',
    'VOIDED'
);

CREATE TYPE order_status AS ENUM (
    'PENDING_APPROVAL',
    'APPROVED',
    'REJECTED',
    'IN_FULFILLMENT',
    'SHIPPED',
    'CLOSED',
    'CANCELLED'
);

CREATE TYPE inventory_action AS ENUM (
    'ALLOCATE',
    'RELEASE',
    'ADJUST'
);

-- -------------------------------------------------------------------------------------------------
-- 3. CORE REFERENCE TABLES
-- -------------------------------------------------------------------------------------------------
CREATE TABLE role (
    id           UUID PRIMARY KEY,
    code         VARCHAR(64)  NOT NULL UNIQUE,
    name         VARCHAR(128) NOT NULL,
    description  TEXT,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at   TIMESTAMPTZ
);

CREATE TABLE account (
    id               UUID PRIMARY KEY,
    parent_account_id UUID        REFERENCES account (id) ON DELETE SET NULL,
    legal_name       VARCHAR(256) NOT NULL,
    contact_email    VARCHAR(256) NOT NULL,
    contact_phone    VARCHAR(32),
    billing_address  JSONB,
    shipping_address JSONB,
    is_active        BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at       TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_account_email ON account (contact_email);

CREATE TABLE app_user (
    id             UUID PRIMARY KEY,
    account_id     UUID         NOT NULL REFERENCES account (id) ON DELETE CASCADE,
    username       VARCHAR(128) NOT NULL UNIQUE,
    email          VARCHAR(256) NOT NULL UNIQUE,
    password_hash  VARCHAR(256) NOT NULL,
    is_locked      BOOLEAN      NOT NULL DEFAULT FALSE,
    last_login_at  TIMESTAMPTZ,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at     TIMESTAMPTZ
);

CREATE TABLE user_role (
    user_id      UUID NOT NULL REFERENCES app_user (id) ON DELETE CASCADE,
    role_id      UUID NOT NULL REFERENCES role (id)      ON DELETE CASCADE,
    assigned_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, role_id)
);

-- -------------------------------------------------------------------------------------------------
-- 4. PRODUCT CATALOG
-- -------------------------------------------------------------------------------------------------
CREATE TABLE category (
    id           UUID PRIMARY KEY,
    parent_id    UUID REFERENCES category (id) ON DELETE SET NULL,
    name         VARCHAR(128) NOT NULL,
    slug         VARCHAR(128) NOT NULL UNIQUE,
    path         TEXT         NOT NULL,
    description  TEXT,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at   TIMESTAMPTZ
);

CREATE TABLE product (
    id              UUID PRIMARY KEY,
    sku             VARCHAR(64)  NOT NULL UNIQUE,
    name            VARCHAR(256) NOT NULL,
    description     TEXT,
    attributes      JSONB,
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);

CREATE TABLE product_category (
    product_id  UUID NOT NULL REFERENCES product (id)  ON DELETE CASCADE,
    category_id UUID NOT NULL REFERENCES category (id) ON DELETE CASCADE,
    PRIMARY KEY (product_id, category_id)
);

CREATE TABLE price_tier (
    id            UUID PRIMARY KEY,
    product_id    UUID        NOT NULL REFERENCES product (id) ON DELETE CASCADE,
    min_quantity  INTEGER     NOT NULL CHECK (min_quantity > 0),
    currency      CHAR(3)     NOT NULL,
    list_price    NUMERIC(12, 2) NOT NULL CHECK (list_price >= 0),
    contract_price NUMERIC(12, 2),
    valid_from    DATE        NOT NULL,
    valid_to      DATE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (product_id, min_quantity, currency, valid_from)
);

-- -------------------------------------------------------------------------------------------------
-- 5. INVENTORY
-- -------------------------------------------------------------------------------------------------
CREATE TABLE inventory (
    id             UUID PRIMARY KEY,
    product_id     UUID     NOT NULL REFERENCES product (id) ON DELETE CASCADE,
    warehouse_code VARCHAR(64) NOT NULL,
    quantity_on_hand INTEGER  NOT NULL DEFAULT 0,
    quantity_reserved INTEGER NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (product_id, warehouse_code)
);

CREATE TABLE inventory_ledger (
    id              UUID PRIMARY KEY,
    inventory_id    UUID NOT NULL REFERENCES inventory (id) ON DELETE CASCADE,
    action          inventory_action NOT NULL,
    delta           INTEGER          NOT NULL,
    reference_id    UUID,
    reference_type  VARCHAR(64),
    created_at      TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

-- -------------------------------------------------------------------------------------------------
-- 6. QUOTE & CART
-- -------------------------------------------------------------------------------------------------
CREATE TABLE cart (
    id          UUID PRIMARY KEY,
    account_id  UUID         NOT NULL REFERENCES account (id) ON DELETE CASCADE,
    user_id     UUID         REFERENCES app_user (id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE cart_item (
    id          UUID PRIMARY KEY,
    cart_id     UUID        NOT NULL REFERENCES cart (id) ON DELETE CASCADE,
    product_id  UUID        NOT NULL REFERENCES product (id) ON DELETE CASCADE,
    quantity    INTEGER     NOT NULL CHECK (quantity > 0),
    added_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (cart_id, product_id)
);

CREATE TABLE quote (
    id              UUID PRIMARY KEY,
    account_id      UUID         NOT NULL REFERENCES account (id) ON DELETE CASCADE,
    created_by      UUID         NOT NULL REFERENCES app_user (id) ON DELETE SET NULL,
    status          order_status NOT NULL DEFAULT 'PENDING_APPROVAL',
    valid_until     DATE         NOT NULL,
    total_amount    NUMERIC(14,2) NOT NULL DEFAULT 0,
    currency        CHAR(3)      NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    approved_at     TIMESTAMPTZ,
    rejected_at     TIMESTAMPTZ
);

CREATE TABLE quote_item (
    id           UUID PRIMARY KEY,
    quote_id     UUID        NOT NULL REFERENCES quote (id)    ON DELETE CASCADE,
    product_id   UUID        NOT NULL REFERENCES product (id)  ON DELETE CASCADE,
    description  TEXT,
    unit_price   NUMERIC(12,2) NOT NULL CHECK (unit_price >= 0),
    quantity     INTEGER       NOT NULL CHECK (quantity > 0),
    subtotal     NUMERIC(14,2) NOT NULL CHECK (subtotal >= 0),
    UNIQUE (quote_id, product_id)
);

-- -------------------------------------------------------------------------------------------------
-- 7. ORDER MANAGEMENT
-- -------------------------------------------------------------------------------------------------
CREATE TABLE customer_order (
    id                UUID PRIMARY KEY,
    account_id        UUID         NOT NULL REFERENCES account (id) ON DELETE CASCADE,
    originating_quote UUID         REFERENCES quote (id),
    status            order_status NOT NULL DEFAULT 'PENDING_APPROVAL',
    currency          CHAR(3)      NOT NULL,
    total_amount      NUMERIC(14,2) NOT NULL DEFAULT 0,
    placed_at         TIMESTAMPTZ,
    approved_at       TIMESTAMPTZ,
    cancelled_at      TIMESTAMPTZ,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE order_item (
    id              UUID PRIMARY KEY,
    order_id        UUID        NOT NULL REFERENCES customer_order (id) ON DELETE CASCADE,
    product_id      UUID        NOT NULL REFERENCES product (id)        ON DELETE CASCADE,
    description     TEXT,
    unit_price      NUMERIC(12,2) NOT NULL,
    quantity        INTEGER       NOT NULL CHECK (quantity > 0),
    subtotal        NUMERIC(14,2) NOT NULL,
    UNIQUE (order_id, product_id)
);

-- -------------------------------------------------------------------------------------------------
-- 8. PAYMENT & TRANSACTIONS
-- -------------------------------------------------------------------------------------------------
CREATE TABLE payment_transaction (
    id                 UUID PRIMARY KEY,
    order_id           UUID            NOT NULL REFERENCES customer_order (id) ON DELETE CASCADE,
    external_reference VARCHAR(128),
    status             payment_status  NOT NULL DEFAULT 'INITIATED',
    amount             NUMERIC(14,2)   NOT NULL CHECK (amount >= 0),
    currency           CHAR(3)         NOT NULL,
    metadata           JSONB,
    processed_at       TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_payment_order_status ON payment_transaction (order_id, status);

-- -------------------------------------------------------------------------------------------------
-- 9. SHIPMENT
-- -------------------------------------------------------------------------------------------------
CREATE TABLE shipment (
    id                UUID PRIMARY KEY,
    order_id          UUID NOT NULL REFERENCES customer_order (id) ON DELETE CASCADE,
    carrier_code      VARCHAR(64),
    tracking_number   VARCHAR(128),
    shipped_at        TIMESTAMPTZ,
    delivered_at      TIMESTAMPTZ,
    shipping_address  JSONB,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -------------------------------------------------------------------------------------------------
-- 10. AUDIT & LOGGING
-- -------------------------------------------------------------------------------------------------
CREATE TABLE audit_log (
    id            UUID PRIMARY KEY,
    entity_name   VARCHAR(128) NOT NULL,
    entity_id     UUID,
    action        VARCHAR(64)  NOT NULL,
    performed_by  UUID REFERENCES app_user (id),
    old_value     JSONB,
    new_value     JSONB,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- -------------------------------------------------------------------------------------------------
-- 11. AUTOMATIC TIMESTAMP UPDATES
-- -------------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION trg_update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- list of tables requiring automatic updated_at changes
DO $$
DECLARE
    t_record RECORD;
BEGIN
    FOR t_record IN 
        SELECT table_name
        FROM information_schema.columns
        WHERE table_schema = 'commerce'
          AND column_name = 'updated_at'
    LOOP
        EXECUTE format(
            'CREATE TRIGGER trg_%I_updated_at
             BEFORE UPDATE ON %I
             FOR EACH ROW
             WHEN (OLD IS DISTINCT FROM NEW)
             EXECUTE PROCEDURE trg_update_timestamp();',
             t_record.table_name, t_record.table_name
        );
    END LOOP;
END;
$$;

-- -------------------------------------------------------------------------------------------------
-- 12. DEFAULT ADMIN SEED DATA
-- -------------------------------------------------------------------------------------------------
INSERT INTO role (id, code, name, description)
VALUES (uuid_generate_v4(), 'ADMIN', 'Platform Administrator', 'Superuser with full platform access')
ON CONFLICT (code) DO NOTHING;

-- -------------------------------------------------------------------------------------------------
-- END OF FILE
-- -------------------------------------------------------------------------------------------------