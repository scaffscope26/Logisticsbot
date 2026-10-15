\set ON_ERROR_STOP on
begin;
insert into auth.users values ('00000000-0000-0000-0000-000000000001'),('00000000-0000-0000-0000-000000000002');
insert into logistics_private.workspaces(id,name) values('10000000-0000-0000-0000-000000000001','Test');
insert into logistics_private.members values ('10000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000001','approver');

set local role anon;
do $$begin
  begin perform public.logistics_snapshot('10000000-0000-0000-0000-000000000001');
    raise exception 'Anonymous read unexpectedly allowed';
  exception when insufficient_privilege then null; end;
end$$;
reset role;
set local role authenticated;
select set_config('request.jwt.claim.sub','00000000-0000-0000-0000-000000000002',true);
do $$begin
  begin perform public.logistics_snapshot('10000000-0000-0000-0000-000000000001');
    raise exception 'Nonmember read unexpectedly allowed';
  exception when insufficient_privilege then null; end;
end$$;
select set_config('request.jwt.claim.sub','00000000-0000-0000-0000-000000000001',true);
do $$begin
  if public.logistics_snapshot('10000000-0000-0000-0000-000000000001')->>'revision'<>'0' then
    raise exception 'Snapshot read failed'; end if;
  begin perform public.logistics_replace('10000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000001',0,'inventory','[]','test.csv');
    raise exception 'Client direct write unexpectedly allowed';
  exception when insufficient_privilege then null; end;
end$$;
reset role;
set local role service_role;
select public.logistics_replace('10000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000001',0,'inventory','[]','test.csv');
do $$begin
  begin perform public.logistics_replace('10000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000001',0,'inventory','[]','stale.csv');
    raise exception 'Stale write unexpectedly allowed';
  exception when serialization_failure then null; end;
  begin perform public.logistics_replace('10000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000002',1,'inventory','[]','forbidden.csv');
    raise exception 'Nonmember write unexpectedly allowed';
  exception when insufficient_privilege then null; end;
end$$;
select public.logistics_decide('10000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000001',1,'{"id":"test","source_type":"yard","quantity":10}',
  'Approved (internal only)','Owner','Confirmed',(now() at time zone 'America/New_York')::date);
do $$begin
  begin perform public.logistics_replace('10000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000001',2,'inventory','[]','blocked.csv');
    raise exception 'Approved commitment was overwritten';
  exception when serialization_failure then null; end;
end$$;
select public.logistics_decide('10000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000001',2,'{"id":"test","source_type":"yard","quantity":10}',
  'Completed','Owner','Executed',(now() at time zone 'America/New_York')::date);
select public.logistics_replace('10000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000001',3,'inventory','[]','new.csv');
reset role;
do $$begin
  if (select count(*) from logistics_private.decisions)<>0 then raise exception 'Decision not archived'; end if;
  if (select count(*) from logistics_private.events)<5 then raise exception 'Audit missing'; end if;
end$$;
rollback;
