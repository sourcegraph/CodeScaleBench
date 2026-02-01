-- ---------------------------------------------------------------------------
--   Flyway Migration: V2__Add_Pricing_Contracts.sql
--   Project          : CommerceSphere Enterprise Suite
--   Description      : Introduces contract-driven pricing infrastructure,
--                      including master/line tables, account associations,
--                      audit metadata, constraints, indexes, and triggers.
-- ---------------------------------------------------------------------------
--   NOTE: Script assumes PostgreSQL ≥ 10 and existing tables:
--         - account(id)
--         - product(id)
--         - lookup_status(type, code, description)      (optional; see inserts)
--         - "user"(id)                                  (auditing reference)
-- ---------------------------------------------------------------------------
--   All DDL is idempotent to allow safe re-runs in lower environments.
-- ---------------------------------------------------------------------------

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. SEQUENCES
-- ---------------------------------------------------------------------------
CREATE SEQUENCE IF NOT EXISTS seq_pricing_contract
    START WITH 1000
    INCREMENT BY 1
    CACHE 20;

CREATE SEQUENCE IF NOT EXISTS seq_pricing_contract_item
    START WITH 100000
    INCREMENT BY 1
    CACHE 50;

-- ---------------------------------------------------------------------------
-- 2. MASTER TABLE: pricing_contract
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pricing_contract (
    id            BIGINT           PRIMARY KEY        DEFAULT nextval('seq_pricing_contract'),
    contract_code VARCHAR(50)      NOT NULL,
    description   TEXT,
    start_date    DATE             NOT NULL,
    end_date      DATE             NOT NULL,
    status        VARCHAR(20)      NOT NULL           DEFAULT 'DRAFT',
    currency      CHAR(3)          NOT NULL,
    created_at    TIMESTAMP WITH TIME ZONE NOT NULL   DEFAULT NOW(),
    updated_at    TIMESTAMP WITH TIME ZONE NOT NULL   DEFAULT NOW(),
    created_by    BIGINT           NOT NULL,
    updated_by    BIGINT,
    version       INTEGER          NOT NULL           DEFAULT 0,
    CONSTRAINT uk_pricing_contract_code UNIQUE (contract_code),
    CONSTRAINT chk_pricing_contract_period CHECK (end_date >= start_date),
    CONSTRAINT chk_pricing_contract_status CHECK (status IN ('DRAFT','ACTIVE','EXPIRED','CANCELLED')),
    CONSTRAINT fk_pricing_contract_created_by FOREIGN KEY (created_by) REFERENCES "user"(id),
    CONSTRAINT fk_pricing_contract_updated_by FOREIGN KEY (updated_by) REFERENCES "user"(id)
);

COMMENT ON TABLE  pricing_contract                 IS 'Stores contract-level pricing agreements.';
COMMENT ON COLUMN pricing_contract.contract_code   IS 'ERP or manual identifier for the contract.';
COMMENT ON COLUMN pricing_contract.status          IS 'Lifecycle stage: DRAFT, ACTIVE, EXPIRED, CANCELLED.';

-- ---------------------------------------------------------------------------
-- 3. LINE TABLE: pricing_contract_item
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pricing_contract_item (
    id               BIGINT           PRIMARY KEY      DEFAULT nextval('seq_pricing_contract_item'),
    contract_id      BIGINT           NOT NULL,
    product_id       BIGINT           NOT NULL,
    min_quantity     INTEGER          NOT NULL         DEFAULT 1,
    price            NUMERIC(18,4)    NOT NULL,
    uom              VARCHAR(10)      NOT NULL         DEFAULT 'EA',
    discount_percent NUMERIC(5,2),
    created_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    version          INTEGER          NOT NULL         DEFAULT 0,
    CONSTRAINT fk_prc_item_contract FOREIGN KEY (contract_id)
        REFERENCES pricing_contract(id) ON DELETE CASCADE,
    CONSTRAINT fk_prc_item_product  FOREIGN KEY (product_id)
        REFERENCES product(id)         ON DELETE RESTRICT,
    CONSTRAINT chk_prc_item_price      CHECK (price  >= 0),
    CONSTRAINT chk_prc_item_quantity   CHECK (min_quantity > 0)
);

COMMENT ON TABLE pricing_contract_item IS 'Line-level price definitions within a contract.';

-- ---------------------------------------------------------------------------
-- 4. LINK TABLE: account_pricing_contract
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS account_pricing_contract (
    account_id  BIGINT  NOT NULL,
    contract_id BIGINT  NOT NULL,
    assigned_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (account_id, contract_id),
    CONSTRAINT fk_acct_prc_contract_account  FOREIGN KEY (account_id)
        REFERENCES account(id)          ON DELETE CASCADE,
    CONSTRAINT fk_acct_prc_contract_master   FOREIGN KEY (contract_id)
        REFERENCES pricing_contract(id) ON DELETE CASCADE
);

COMMENT ON TABLE account_pricing_contract IS 'Associates customer accounts with pricing contracts.';

-- ---------------------------------------------------------------------------
-- 5. INDEXES
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_pricing_contract_status
    ON pricing_contract (status);

CREATE INDEX IF NOT EXISTS idx_pricing_contract_period
    ON pricing_contract (start_date, end_date);

CREATE INDEX IF NOT EXISTS idx_pricing_contract_item_product
    ON pricing_contract_item (product_id);

CREATE INDEX IF NOT EXISTS idx_pricing_contract_item_contract
    ON pricing_contract_item (contract_id);

-- ---------------------------------------------------------------------------
-- 6. TRIGGER FUNCTION FOR AUDIT FIELDS & OPTIMISTIC LOCKING
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION trg_set_timestamp_and_version()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := NOW();
    NEW.version     := COALESCE(OLD.version, 0) + 1;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Attach to master
DROP TRIGGER IF EXISTS tg_prc_master_upd ON pricing_contract;
CREATE TRIGGER tg_prc_master_upd
    BEFORE UPDATE ON pricing_contract
    FOR EACH ROW
    EXECUTE PROCEDURE trg_set_timestamp_and_version();

-- Attach to line
DROP TRIGGER IF EXISTS tg_prc_item_upd ON pricing_contract_item;
CREATE TRIGGER tg_prc_item_upd
    BEFORE UPDATE ON pricing_contract_item
    FOR EACH ROW
    EXECUTE PROCEDURE trg_set_timestamp_and_version();

-- ---------------------------------------------------------------------------
-- 7. OPTIONAL LOOKUP SEED DATA
-- ---------------------------------------------------------------------------
INSERT INTO lookup_status(type, code, description)
SELECT 'PRICING_CONTRACT_STATUS', 'DRAFT', 'Contract initialized but not yet active'
WHERE NOT EXISTS (
    SELECT 1 FROM lookup_status WHERE type = 'PRICING_CONTRACT_STATUS' AND code = 'DRAFT'
);

INSERT INTO lookup_status(type, code, description)
SELECT 'PRICING_CONTRACT_STATUS', 'ACTIVE', 'Contract currently in effect'
WHERE NOT EXISTS (
    SELECT 1 FROM lookup_status WHERE type = 'PRICING_CONTRACT_STATUS' AND code = 'ACTIVE'
);

INSERT INTO lookup_status(type, code, description)
SELECT 'PRICING_CONTRACT_STATUS', 'EXPIRED', 'Contract whose end date has passed'
WHERE NOT EXISTS (
    SELECT 1 FROM lookup_status WHERE type = 'PRICING_CONTRACT_STATUS' AND code = 'EXPIRED'
);

INSERT INTO lookup_status(type, code, description)
SELECT 'PRICING_CONTRACT_STATUS', 'CANCELLED', 'Contract revoked before end date'
WHERE NOT EXISTS (
    SELECT 1 FROM lookup_status WHERE type = 'PRICING_CONTRACT_STATUS' AND code = 'CANCELLED'
);

-- ---------------------------------------------------------------------------
COMMIT;

-- ---------------------------------------------------------------------------
--  End of V2__Add_Pricing_Contracts.sql
-- ---------------------------------------------------------------------------