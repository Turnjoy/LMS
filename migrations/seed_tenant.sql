-- Seed the main Turnjoy tenant and its public profile for Render deployment.
-- Bind the domain lms-a5n7.onrender.com to the main tenant.

WITH main_tenant AS (
    INSERT INTO tenants (
        name,
        subdomain,
        custom_domain,
        logo_url,
        primary_color,
        secondary_color,
        created_at
    )
    VALUES (
        'Turnjoy LMS',
        'main',
        'lms-a5n7.onrender.com',
        '/static/images/turnjoy.png',
        '#0066cc',
        '#7b2cff',
        NOW()
    )
    ON CONFLICT (custom_domain)
    DO UPDATE
    SET
        name = EXCLUDED.name,
        subdomain = COALESCE(tenants.subdomain, EXCLUDED.subdomain),
        logo_url = EXCLUDED.logo_url,
        primary_color = EXCLUDED.primary_color,
        secondary_color = EXCLUDED.secondary_color
    RETURNING id
)

INSERT INTO tenant_public_profiles (
    tenant_id,
    headline,
    about,
    admission_message,
    admission_open,
    created_at,
    updated_at
)
SELECT
    id,
    'Welcome to the Turnjoy LMS Portal',
    'A branded school portal powered by Turnjoy, ready for staff, students, and parents.',
    'Admissions are open. Apply today to join our school community.',
    TRUE,
    NOW(),
    NOW()
FROM main_tenant
ON CONFLICT (tenant_id)
DO UPDATE
SET
    headline = EXCLUDED.headline,
    about = EXCLUDED.about,
    admission_message = EXCLUDED.admission_message,
    admission_open = EXCLUDED.admission_open,
    updated_at = NOW();
