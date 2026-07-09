-- Turnjoy multi-tenant SaaS overhaul.
-- Apply this in Supabase before deploying the application code.

alter table public.tenants
    add column if not exists setup_completed boolean not null default false;

alter table public.users
    add column if not exists school_generated_id text;

update public.users
set school_generated_id = custom_id
where school_generated_id is null
  and custom_id is not null;

create unique index if not exists users_school_generated_id_key
    on public.users (school_generated_id)
    where school_generated_id is not null;

create table if not exists public.class_levels (
    id bigserial primary key,
    tenant_id bigint not null references public.tenants(id) on delete cascade,
    name text not null,
    category text not null,
    sort_order integer not null default 0,
    created_at timestamptz not null default now(),
    constraint unique_tenant_class_level unique (tenant_id, name)
);

create index if not exists idx_class_levels_tenant_id
    on public.class_levels(tenant_id);

create index if not exists idx_class_levels_category
    on public.class_levels(tenant_id, category);

create table if not exists public.class_arms (
    id bigserial primary key,
    tenant_id bigint not null references public.tenants(id) on delete cascade,
    class_level_id bigint not null references public.class_levels(id) on delete cascade,
    name text not null,
    created_at timestamptz not null default now(),
    constraint unique_tenant_class_arm unique (tenant_id, class_level_id, name)
);

create index if not exists idx_class_arms_tenant_id
    on public.class_arms(tenant_id);

create index if not exists idx_class_arms_class_level_id
    on public.class_arms(class_level_id);

alter table public.classes
    add column if not exists class_level_id bigint references public.class_levels(id) on delete set null,
    add column if not exists class_arm_id bigint references public.class_arms(id) on delete set null;

alter table public.classes
    alter column arm type text;

create index if not exists idx_classes_class_level_id
    on public.classes(class_level_id);

create index if not exists idx_classes_class_arm_id
    on public.classes(class_arm_id);

alter table public.subjects
    add column if not exists class_level_id bigint references public.class_levels(id) on delete set null;

create index if not exists idx_subjects_class_level_id
    on public.subjects(class_level_id);

create index if not exists idx_subjects_tenant_level_name
    on public.subjects(tenant_id, class_level_id, lower(name));

-- Defense-in-depth for Supabase Data API exposure. Application queries still scope by tenant_id.
alter table public.class_levels enable row level security;
alter table public.class_arms enable row level security;

comment on column public.tenants.setup_completed is 'True after the tenant school admin finishes first-time setup.';
comment on column public.users.school_generated_id is 'Tenant-scoped generated matrix/admin identifier; regular users still authenticate by email.';
comment on table public.class_levels is 'Tenant-owned base class levels such as Primary 1, JSS 1, and SSS 3.';
comment on table public.class_arms is 'Tenant-owned class streams/arms linked to a base class level.';
