CREATE TABLE IF NOT EXISTS global_subject_repository (
    id SERIAL PRIMARY KEY,
    name VARCHAR(120) NOT NULL UNIQUE,
    category VARCHAR(40) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_global_subject_repository_name
    ON global_subject_repository (name);

CREATE INDEX IF NOT EXISTS ix_global_subject_repository_category
    ON global_subject_repository (category);

CREATE TABLE IF NOT EXISTS tenant_subjects (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    global_subject_id INTEGER NOT NULL REFERENCES global_subject_repository(id),
    class_level_id INTEGER NOT NULL REFERENCES classes(id),
    assigned_teacher_id INTEGER REFERENCES users(id),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_tenant_global_subject_class
        UNIQUE (tenant_id, global_subject_id, class_level_id)
);

CREATE INDEX IF NOT EXISTS ix_tenant_subjects_tenant_id
    ON tenant_subjects (tenant_id);

CREATE TABLE IF NOT EXISTS student_subject_registrations (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    student_id INTEGER NOT NULL REFERENCES users(id),
    tenant_subject_id INTEGER NOT NULL REFERENCES tenant_subjects(id),
    registration_date TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_student_tenant_subject
        UNIQUE (student_id, tenant_subject_id)
);

CREATE INDEX IF NOT EXISTS ix_student_subject_registrations_tenant_id
    ON student_subject_registrations (tenant_id);

CREATE TABLE IF NOT EXISTS cbt_exams (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    title VARCHAR(200) NOT NULL,
    class_id INTEGER REFERENCES classes(id),
    subject_id INTEGER REFERENCES subjects(id),
    term_id INTEGER REFERENCES terms(id),
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_cbt_exams_tenant_id
    ON cbt_exams (tenant_id);

CREATE TABLE IF NOT EXISTS cbt_questions (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    exam_id INTEGER NOT NULL REFERENCES cbt_exams(id),
    question_text TEXT NOT NULL,
    option_a VARCHAR(500) NOT NULL,
    option_b VARCHAR(500) NOT NULL,
    option_c VARCHAR(500) NOT NULL,
    option_d VARCHAR(500) NOT NULL,
    correct_option VARCHAR(1) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_cbt_questions_tenant_id
    ON cbt_questions (tenant_id);

CREATE INDEX IF NOT EXISTS ix_cbt_questions_exam_id
    ON cbt_questions (exam_id);
