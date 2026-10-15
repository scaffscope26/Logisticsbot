-- Completed movements consume the proposal until a fresh operational snapshot arrives.
create or replace function public.logistics_decide(p_workspace uuid,p_actor uuid,p_revision bigint,
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
  if old_status='Completed' then raise exception 'Completed movement requires refreshed reports'; end if;
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
