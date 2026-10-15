-- Run manually in the intended Supabase project's SQL editor, not as a migration.
-- Invite the account first and replace this email. Re-running creates a NEW workspace.
do $$
declare member_id uuid; workspace uuid;
begin
  select id into member_id from auth.users where email='REPLACE_WITH_INVITED_EMAIL';
  if member_id is null then raise exception 'Invite the intended user before bootstrap'; end if;
  insert into logistics_private.workspaces(name) values('Florida') returning id into workspace;
  insert into logistics_private.members(workspace_id,user_id,role) values(workspace,member_id,'approver');
  raise notice 'Set LOGISTICS_WORKSPACE_ID to %',workspace;
end $$;
-- Add later users to logistics_private.members using this same workspace UUID.
-- Supported roles: viewer, editor, approver. Never grant self-enrollment.
