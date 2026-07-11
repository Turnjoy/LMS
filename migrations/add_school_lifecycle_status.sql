-- Add lifecycle status controls for school/tenant onboarding.
-- In this codebase, public.tenants is the schools table.

alter table public.tenants
    add column if not exists status text not null default 'pending';

update public.tenants
set status = case
    when is_active then 'active'
    else 'rejected'
end
where status = 'pending';

alter table public.tenants
    drop constraint if exists tenants_status_check,
    add constraint tenants_status_check
        check (status in ('pending', 'active', 'approved', 'rejected'));

create index if not exists idx_tenants_status on public.tenants(status);

comment on column public.tenants.status is 'Lifecycle status for school onboarding: pending, active, or rejected. approved is accepted as a legacy active value.';
