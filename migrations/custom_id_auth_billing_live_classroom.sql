-- Custom ID auth, platform billing controls, and tenant-prefixed IDs.
-- In this codebase, public.tenants is the school table.

alter table public.tenants
    add column if not exists school_prefix text not null default 'SCH',
    add column if not exists is_active boolean not null default true,
    add column if not exists billing_type text not null default 'school_pay';

alter table public.tenants
    drop constraint if exists tenants_billing_type_check,
    add constraint tenants_billing_type_check
        check (billing_type in ('student_pay', 'school_pay'));

comment on table public.tenants is 'Schools/tenants for the multi-tenant LMS. Equivalent to the schools table in product specs.';
comment on column public.tenants.school_prefix is 'Short school prefix used for generated IDs, e.g. TJ.';
comment on column public.tenants.is_active is 'False means the school is locked/suspended by the platform owner.';
comment on column public.tenants.billing_type is 'school_pay blocks the whole school when inactive; student_pay blocks unpaid learners.';

alter table public.users
    add column if not exists custom_id text,
    alter column email drop not null,
    alter column password_hash drop not null,
    add column if not exists phone_number text,
    add column if not exists is_first_login boolean not null default true,
    add column if not exists payment_status text not null default 'unpaid';

alter table public.users
    drop constraint if exists users_payment_status_check,
    add constraint users_payment_status_check
        check (payment_status in ('unpaid', 'paid', 'waived', 'pending'));

create unique index if not exists users_custom_id_key on public.users (custom_id) where custom_id is not null;
create index if not exists idx_users_tenant_role on public.users (tenant_id, role);
create index if not exists idx_users_tenant_contact on public.users (tenant_id, lower(email), lower(phone_number));

do $$
begin
    if not exists (
        select 1
        from information_schema.columns
        where table_schema = 'public'
          and table_name = 'users'
          and column_name = 'school_id'
    ) then
        alter table public.users
            add column school_id integer generated always as (tenant_id) stored;
    end if;
end $$;

create or replace function public.assign_tenant_custom_id()
returns trigger
language plpgsql
as $$
declare
    v_prefix text;
    v_year text;
    v_kind text;
    v_next integer;
begin
    if new.custom_id is not null or new.tenant_id is null or new.role = 'super_admin' then
        return new;
    end if;

    select upper(coalesce(nullif(trim(school_prefix), ''), 'SCH'))
    into v_prefix
    from public.tenants
    where id = new.tenant_id
    for update;

    if v_prefix is null then
        raise exception 'Cannot assign custom_id: tenant % was not found', new.tenant_id;
    end if;

    v_year := to_char(current_date, 'YYYY');
    v_kind := case when new.role = 'student' then 'STU' else 'STF' end;

    select count(*) + 1
    into v_next
    from public.users
    where tenant_id = new.tenant_id
      and custom_id like v_prefix || '/' || v_kind || '/' || v_year || '/%';

    new.custom_id := v_prefix || '/' || v_kind || '/' || v_year || '/' || lpad(v_next::text, 3, '0');
    return new;
end;
$$;

drop trigger if exists trg_assign_tenant_custom_id on public.users;
create trigger trg_assign_tenant_custom_id
before insert on public.users
for each row
execute function public.assign_tenant_custom_id();

with ranked_users as (
    select
        u.id,
        upper(coalesce(nullif(trim(t.school_prefix), ''), 'SCH')) as prefix,
        case when u.role = 'student' then 'STU' else 'STF' end as kind,
        to_char(coalesce(u.created_at, now())::date, 'YYYY') as created_year,
        row_number() over (
            partition by u.tenant_id, case when u.role = 'student' then 'STU' else 'STF' end, to_char(coalesce(u.created_at, now())::date, 'YYYY')
            order by u.created_at, u.id
        ) as sequence_number
    from public.users u
    join public.tenants t on t.id = u.tenant_id
    where u.custom_id is null
      and u.tenant_id is not null
      and u.role <> 'super_admin'
)
update public.users u
set custom_id = ranked_users.prefix || '/' || ranked_users.kind || '/' || ranked_users.created_year || '/' || lpad(ranked_users.sequence_number::text, 3, '0')
from ranked_users
where ranked_users.id = u.id;

update public.users
set payment_status = 'paid'
where role not in ('student', 'parent')
  and payment_status = 'unpaid';
