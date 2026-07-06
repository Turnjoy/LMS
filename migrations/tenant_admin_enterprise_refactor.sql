ALTER TABLE users
    ALTER COLUMN tenant_id DROP NOT NULL;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS is_approved BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE users
SET is_approved = TRUE
WHERE role NOT IN ('admin', 'primary_admin', 'secondary_admin')
   OR is_approved IS NULL;

ALTER TABLE classes
    ADD COLUMN IF NOT EXISTS section VARCHAR(20),
    ADD COLUMN IF NOT EXISTS arm VARCHAR(1),
    ADD COLUMN IF NOT EXISTS track VARCHAR(30);

CREATE INDEX IF NOT EXISTS ix_classes_section ON classes(section);
CREATE INDEX IF NOT EXISTS ix_classes_arm ON classes(arm);
CREATE INDEX IF NOT EXISTS ix_classes_track ON classes(track);

CREATE TABLE IF NOT EXISTS fee_categories (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    name VARCHAR(100) NOT NULL,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_tenant_fee_category UNIQUE (tenant_id, name)
);

CREATE INDEX IF NOT EXISTS ix_fee_categories_tenant_id
    ON fee_categories(tenant_id);

CREATE TABLE IF NOT EXISTS fee_installment_plans (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    fee_category_id INTEGER NOT NULL REFERENCES fee_categories(id),
    class_id INTEGER REFERENCES classes(id),
    term_id INTEGER REFERENCES terms(id),
    amount DOUBLE PRECISION DEFAULT 0,
    installments_enabled BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_fee_installment_plans_tenant_id
    ON fee_installment_plans(tenant_id);

CREATE TABLE IF NOT EXISTS fee_installment_milestones (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    plan_id INTEGER NOT NULL REFERENCES fee_installment_plans(id),
    label VARCHAR(80) NOT NULL,
    percentage DOUBLE PRECISION NOT NULL,
    due_date DATE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_fee_installment_milestones_tenant_id
    ON fee_installment_milestones(tenant_id);

CREATE TABLE IF NOT EXISTS payment_transactions (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    student_id INTEGER NOT NULL REFERENCES users(id),
    term_id INTEGER REFERENCES terms(id),
    provider VARCHAR(40) NOT NULL,
    reference VARCHAR(120) NOT NULL,
    amount DOUBLE PRECISION DEFAULT 0,
    status VARCHAR(30) DEFAULT 'pending',
    raw_payload JSONB,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_payment_provider_reference UNIQUE (provider, reference)
);

CREATE INDEX IF NOT EXISTS ix_payment_transactions_tenant_id
    ON payment_transactions(tenant_id);

CREATE INDEX IF NOT EXISTS ix_payment_transactions_reference
    ON payment_transactions(reference);

ALTER TABLE assignment_submissions
    ADD COLUMN IF NOT EXISTS client_sync_id VARCHAR(120);

CREATE INDEX IF NOT EXISTS ix_assignment_submissions_client_sync_id
    ON assignment_submissions(client_sync_id);

CREATE UNIQUE INDEX IF NOT EXISTS unique_assignment_client_sync_id
    ON assignment_submissions(tenant_id, client_sync_id)
    WHERE client_sync_id IS NOT NULL;
