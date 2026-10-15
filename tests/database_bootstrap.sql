-- Disposable CI Postgres only. Supabase supplies these roles/schema in real projects.
create role anon nologin;
create role authenticated nologin;
create role service_role nologin bypassrls;
create schema auth;
create table auth.users(id uuid primary key);
create function auth.uid() returns uuid language sql stable as $$
  select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid
$$;
grant usage on schema auth to authenticated, service_role;
grant execute on function auth.uid() to authenticated, service_role;

-- Model the default helper found by the hosted project's security advisor.
create function public.rls_auto_enable() returns event_trigger
language plpgsql security definer set search_path = '' as $$begin null; end$$;
