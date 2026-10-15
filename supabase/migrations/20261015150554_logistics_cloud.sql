-- Report snapshots remain JSON to preserve flexible Quantify mappings during the pilot.
-- Private tables are never exposed by PostgREST. All mutations are server-only.
create schema logistics_private;
revoke all on schema logistics_private from public, anon, authenticated;
grant usage on schema logistics_private to authenticated, service_role;

create table logistics_private.workspaces (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  revision bigint not null default 0,
  reports jsonb not null default '{}'::jsonb,
  imports jsonb not null default '{}'::jsonb
);
create table logistics_private.members (
  workspace_id uuid references logistics_private.workspaces on delete cascade,
  user_id uuid references auth.users on delete cascade,
  role text not null check (role in ('viewer','editor','approver')),
  primary key (workspace_id,user_id)
);
create index logistics_members_user on logistics_private.members(user_id);
create table logistics_private.decisions (
  workspace_id uuid references logistics_private.workspaces on delete cascade,
  opportunity_id text not null,
  opportunity jsonb not null,
  plan_day date not null,
  status text not null check (status in ('Proposed','Investigating','Approved (internal only)','Rejected','Completed')),
  owner text not null,
  note text not null,
  updated_by uuid references auth.users,
  updated_at timestamptz not null default now(),
  primary key (workspace_id,opportunity_id)
);
create table logistics_private.events (
  id bigint generated always as identity primary key,
  workspace_id uuid references logistics_private.workspaces,
  actor uuid references auth.users,
  event_type text not null,
  payload jsonb not null,
  created_at timestamptz not null default now()
);
create index logistics_events_workspace on logistics_private.events(workspace_id,created_at);
alter table logistics_private.workspaces enable row level security;
alter table logistics_private.members enable row level security;
alter table logistics_private.decisions enable row level security;
alter table logistics_private.events enable row level security;
-- No client table grants or policies. Only the narrow, authorized read function
-- below bypasses RLS; server writes use service_role after checking membership.
revoke all on all tables in schema logistics_private from public, anon, authenticated;
grant all on all tables in schema logistics_private to service_role;
grant usage, select on all sequences in schema logistics_private to service_role;

create function logistics_private.snapshot(p_workspace uuid) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare result jsonb;
begin
  if auth.uid() is null or not exists (
    select 1 from logistics_private.members where workspace_id=p_workspace and user_id=auth.uid()
  ) then raise exception 'workspace_access' using errcode='42501'; end if;
  select jsonb_build_object('revision', w.revision, 'reports', w.reports, 'imports', w.imports,
    'decisions', coalesce((select jsonb_agg(to_jsonb(d) order by d.opportunity_id)
      from logistics_private.decisions d where d.workspace_id=w.id),'[]'::jsonb))
    into result from logistics_private.workspaces w where w.id=p_workspace;
  return result;
end $$;
revoke all on function logistics_private.snapshot(uuid) from public, anon, authenticated;
grant execute on function logistics_private.snapshot(uuid) to authenticated;
create function public.logistics_snapshot(p_workspace uuid) returns jsonb
language sql security invoker set search_path = '' as $$
  select logistics_private.snapshot(p_workspace)
$$;
revoke all on function public.logistics_snapshot(uuid) from public, anon, authenticated;
grant execute on function public.logistics_snapshot(uuid) to authenticated;

create function public.logistics_replace(p_workspace uuid,p_actor uuid,p_revision bigint,
  p_kind text,p_rows jsonb,p_filename text) returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare w logistics_private.workspaces; new_revision bigint;
begin
  if not exists (select 1 from logistics_private.members where workspace_id=p_workspace
    and user_id=p_actor and role in ('editor','approver')) then
    raise exception 'workspace_access' using errcode='42501'; end if;
  select * into w from logistics_private.workspaces where id=p_workspace for update;
  if p_revision is null or w.revision<>p_revision then
    raise exception 'stale_revision' using errcode='40001'; end if;
  if p_kind not in ('inventory','projects','reservations','returns')
    or jsonb_typeof(p_rows)<>'array' or jsonb_array_length(p_rows)>20000 then
    raise exception 'Invalid snapshot'; end if;
  if exists(select 1 from logistics_private.decisions where workspace_id=p_workspace
    and status='Approved (internal only)') then
    raise exception 'approved_commitments' using errcode='40001'; end if;
  update logistics_private.workspaces set
    reports=jsonb_set(reports,array[p_kind],p_rows,true),
    imports=jsonb_set(imports,array[p_kind],jsonb_build_object(
      'filename',p_filename,'rows',jsonb_array_length(p_rows),'created_at',now(),'actor',p_actor),true),
    revision=revision+1 where id=p_workspace returning revision into new_revision;
  -- Old decisions stay in the audit log; they cannot silently attach to new reports.
  insert into logistics_private.events(workspace_id,actor,event_type,payload)
    select p_workspace,p_actor,'decision_archived',to_jsonb(d)
      from logistics_private.decisions d where workspace_id=p_workspace;
  delete from logistics_private.decisions where workspace_id=p_workspace;
  insert into logistics_private.events(workspace_id,actor,event_type,payload)
    values(p_workspace,p_actor,'import',jsonb_build_object('kind',p_kind,'filename',p_filename,
      'rows',jsonb_array_length(p_rows),'revision',new_revision));
  return jsonb_build_object('revision',new_revision);
end $$;
revoke all on function public.logistics_replace(uuid,uuid,bigint,text,jsonb,text) from public,anon,authenticated;
grant execute on function public.logistics_replace(uuid,uuid,bigint,text,jsonb,text) to service_role;

create function public.logistics_decide(p_workspace uuid,p_actor uuid,p_revision bigint,
  p_opportunity jsonb,p_status text,p_owner text,p_note text,p_day date) returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare w logistics_private.workspaces; member_role text; old_status text;
begin
  select role into member_role from logistics_private.members
    where workspace_id=p_workspace and user_id=p_actor;
  if member_role is null or member_role='viewer' then
    raise exception 'workspace_access' using errcode='42501'; end if;
  select * into w from logistics_private.workspaces where id=p_workspace for update;
  if p_revision is null or w.revision<>p_revision or p_day<>(now() at time zone 'America/New_York')::date then
    raise exception 'stale_revision' using errcode='40001'; end if;
  select status into old_status from logistics_private.decisions
    where workspace_id=p_workspace and opportunity_id=p_opportunity->>'id';
  if (p_status='Approved (internal only)' or old_status='Approved (internal only)')
    and member_role<>'approver' then raise exception 'workspace_access' using errcode='42501'; end if;
  if p_status='Approved (internal only)' and exists(
    select 1 from logistics_private.decisions where workspace_id=p_workspace
      and status='Approved (internal only)' and plan_day<>p_day
  ) then raise exception 'approved_commitments' using errcode='40001'; end if;
  if p_status not in ('Proposed','Investigating','Approved (internal only)','Rejected','Completed')
    or p_opportunity->>'id' is null or p_opportunity->>'source_type'='shortage' then
    raise exception 'Invalid decision'; end if;
  insert into logistics_private.decisions as d
    (workspace_id,opportunity_id,opportunity,plan_day,status,owner,note,updated_by)
    values(p_workspace,p_opportunity->>'id',p_opportunity,p_day,p_status,p_owner,p_note,p_actor)
    on conflict(workspace_id,opportunity_id) do update set opportunity=excluded.opportunity,
      plan_day=excluded.plan_day,status=excluded.status,owner=excluded.owner,note=excluded.note,
      updated_by=excluded.updated_by,updated_at=now();
  update logistics_private.workspaces set revision=revision+1 where id=p_workspace;
  insert into logistics_private.events(workspace_id,actor,event_type,payload)
    values(p_workspace,p_actor,'decision',jsonb_build_object('opportunity',p_opportunity,
      'status',p_status,'owner',p_owner,'note',p_note,'plan_day',p_day,'revision',p_revision+1));
  return jsonb_build_object('ok',true,'revision',p_revision+1);
end $$;
revoke all on function public.logistics_decide(uuid,uuid,bigint,jsonb,text,text,text,date) from public,anon,authenticated;
grant execute on function public.logistics_decide(uuid,uuid,bigint,jsonb,text,text,text,date) to service_role;
