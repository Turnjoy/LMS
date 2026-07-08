-- Store school onboarding applications on the tenants table.
-- Pending applications are inactive until the Super Admin accepts them.

alter table public.tenants
    add column if not exists application_website text,
    add column if not exists application_contact_name text,
    add column if not exists application_contact_email text,
    add column if not exists application_contact_phone text,
    add column if not exists application_note text;

create index if not exists idx_tenants_application_contact_email
    on public.tenants(lower(application_contact_email))
    where application_contact_email is not null;

create index if not exists idx_tenants_application_website
    on public.tenants(lower(application_website))
    where application_website is not null;

comment on column public.tenants.application_website is 'Website/domain submitted by a school applying for LMS access.';
comment on column public.tenants.application_contact_name is 'Contact person submitted with the school LMS application.';
comment on column public.tenants.application_contact_email is 'Contact email submitted with the school LMS application.';
comment on column public.tenants.application_contact_phone is 'Contact phone submitted with the school LMS application.';
comment on column public.tenants.application_note is 'Optional notes submitted with the school LMS application.';
