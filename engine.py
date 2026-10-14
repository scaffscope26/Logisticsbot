import csv, io, json, sqlite3, datetime, hashlib
from pathlib import Path
from openpyxl import load_workbook
DB=Path(__file__).parent/'logistics.db'
SCHEMAS={
 'inventory':['facility','part_number','description','quantity_available'],
 'projects':['project_id','customer','facility','part_number','quantity_on_rent','expected_return_date'],
 'reservations':['reservation_id','facility','part_number','quantity_required','required_date'],
 'returns':['project_id','facility','part_number','quantity_returning','return_date']}
ALIASES={'branch':'facility','yard':'facility','location':'facility','part':'part_number','item':'part_number','item_number':'part_number','qty':'quantity_available','available':'quantity_available','job':'project_id','job_number':'project_id','order_id':'reservation_id','order_number':'reservation_id','ship_date':'required_date','delivery_date':'required_date','off_rent_date':'expected_return_date','pickup_date':'return_date'}
def norm(s):return str(s or '').strip().lower().replace(' ','_').replace('-','_').replace('/','_')
def db():
 c=sqlite3.connect(DB);c.row_factory=sqlite3.Row
 c.executescript('CREATE TABLE IF NOT EXISTS records (kind TEXT NOT NULL, record_key TEXT NOT NULL, payload TEXT NOT NULL, batch_id TEXT NOT NULL, PRIMARY KEY(kind,record_key));CREATE TABLE IF NOT EXISTS imports (batch_id TEXT PRIMARY KEY,kind TEXT,filename TEXT,created_at TEXT,rows INTEGER);CREATE TABLE IF NOT EXISTS decisions (opportunity_id TEXT PRIMARY KEY,status TEXT,owner TEXT,note TEXT,updated_at TEXT);')
 return c
def parse(data,filename):
 if filename.lower().endswith('.csv'):
  s=data.decode('utf-8-sig');return list(csv.DictReader(io.StringIO(s)))
 if filename.lower().endswith('.xlsx'):
  wb=load_workbook(io.BytesIO(data),read_only=True,data_only=True);ws=wb.active;rows=ws.iter_rows(values_only=True);headers=next(rows,None)
  return [dict(zip(headers,r)) for r in rows if any(v is not None for v in r)] if headers else []
 raise ValueError('Only .csv and .xlsx are supported')
def canonical(row,mapping):
 r={};normalized={norm(k):v for k,v in row.items()}
 for target in mapping:
  src=norm(mapping[target]);r[target]=normalized.get(src,'')
 for key,value in normalized.items():
  t=ALIASES.get(key,key)
  if t not in r:r[t]=value
 return r
def ingest(kind,data,filename,mapping):
 if kind not in SCHEMAS:raise ValueError('Unknown import type')
 rows=parse(data,filename)
 if not rows:raise ValueError('File has no data rows')
 fields=SCHEMAS[kind];missing=[f for f in fields if not mapping.get(f)]
 if missing:raise ValueError('Map required fields: '+', '.join(missing))
 batch=hashlib.sha256(data+kind.encode()).hexdigest()[:16]
 clean=[];errors=[]
 for i,row in enumerate(rows,2):
  r=canonical(row,mapping)
  if any(r.get(f) is None or str(r.get(f)).strip()=='' for f in fields):errors.append(f'Row {i}: missing required values');continue
  try:
   for k in ['quantity_available','quantity_on_rent','quantity_required','quantity_returning']:
    if k in r:r[k]=float(r[k]);assert r[k]>=0
   for k in ['expected_return_date','required_date','return_date']:
    if k in r:
     v=r[k];r[k]=v.date().isoformat() if isinstance(v,datetime.datetime) else v.isoformat() if isinstance(v,datetime.date) else str(v).strip()[:10]
     datetime.date.fromisoformat(r[k])
  except Exception:errors.append(f'Row {i}: invalid quantity or date (use YYYY-MM-DD)');continue
  clean.append(r)
 if errors:return {'ok':False,'errors':errors[:30],'accepted':len(clean),'rejected':len(errors)}
 c=db()
 with c:
  # Each import replaces the current snapshot for its type, not other types.
  c.execute('DELETE FROM records WHERE kind=?',(kind,))
  for idx,r in enumerate(clean):
   key=str(idx)+'-'+hashlib.sha1(json.dumps(r,sort_keys=True,default=str).encode()).hexdigest()[:12]
   c.execute('INSERT INTO records VALUES (?,?,?,?)',(kind,key,json.dumps(r,default=str),batch))
  c.execute('INSERT OR REPLACE INTO imports VALUES (?,?,?,?,?)',(batch,kind,filename,datetime.datetime.now(datetime.timezone.utc).isoformat(),len(clean)))
 return {'ok':True,'accepted':len(clean),'rejected':0,'batch':batch}
def records(kind):
 c=db();out=[json.loads(x['payload']) for x in c.execute('SELECT payload FROM records WHERE kind=?',(kind,))];c.close();return out
def matches():
 today=datetime.date.today();end=today+datetime.timedelta(days=30)
 inv=records('inventory');returns=records('returns');projects=records('projects');demands=records('reservations')
 supply=[]
 for i,r in enumerate(inv):supply.append({'id':f'inv{i}','part':str(r['part_number']).strip().upper(),'facility':r['facility'],'qty':float(r['quantity_available']),'date':today,'type':'yard','confidence':'confirmed','source':r})
 for i,r in enumerate(returns):
  date=datetime.date.fromisoformat(r['return_date']);
  if date<=end:supply.append({'id':f'ret{i}','part':str(r['part_number']).strip().upper(),'facility':r['facility'],'qty':float(r['quantity_returning']),'date':date+datetime.timedelta(days=2),'type':'return','confidence':'pending inspection','source':r})
 # Projects are potential leads only; never allocate them as guaranteed supply.
 forecast=[]
 for r in projects:
  date=datetime.date.fromisoformat(r['expected_return_date'])
  if today<=date<=end:forecast.append({'facility':r['facility'],'part':r['part_number'],'qty':r['quantity_on_rent'],'date':date.isoformat(),'project':r['project_id'],'confidence':'unconfirmed'})
 supply.sort(key=lambda x:(x['date'],x['facility'],x['id']))
 results=[];remaining={s['id']:s['qty'] for s in supply}
 for i,d in enumerate(sorted(demands,key=lambda r:r['required_date'])):
  due=datetime.date.fromisoformat(d['required_date']);need=float(d['quantity_required']);
  if due<today or due>end:continue
  part=str(d['part_number']).strip().upper();candidates=[s for s in supply if s['part']==part and s['date']<=due and remaining[s['id']]>0]
  # Same facility first; cross-facility is a proposal requiring transport validation.
  candidates.sort(key=lambda s:(s['facility']!=d['facility'],s['date']))
  for s in candidates:
   if need<=0:break
   qty=min(need,remaining[s['id']]);remaining[s['id']]-=qty;need-=qty
   oid=hashlib.sha1(f"{d['reservation_id']}|{d['facility']}|{part}|{s['id']}".encode()).hexdigest()[:14]
   results.append({'id':oid,'reservation':d['reservation_id'],'part':part,'quantity':qty,'from':s['facility'],'to':d['facility'],'needed':due.isoformat(),'available':s['date'].isoformat(),'source_type':s['type'],'confidence':s['confidence'],'cross_branch':s['facility']!=d['facility'],'status':'Proposed','warning':'Confirm transport and inspection before approval' if s['facility']!=d['facility'] or s['type']=='return' else 'Confirm reservation remains open'})
  if need>0:results.append({'id':'short-'+str(i),'reservation':d['reservation_id'],'part':part,'quantity':need,'from':'Unmatched','to':d['facility'],'needed':due.isoformat(),'available':'','source_type':'shortage','confidence':'unmatched','cross_branch':False,'status':'Shortage','warning':'Review forecast projects and purchasing options'})
 c=db();decisions={r['opportunity_id']:dict(r) for r in c.execute('SELECT * FROM decisions')};c.close()
 for r in results:
  if r['id'] in decisions:r['status']=decisions[r['id']]['status'];r['owner']=decisions[r['id']]['owner'];r['note']=decisions[r['id']]['note']
 return {'opportunities':results,'forecast':forecast,'summary':{'inventory_rows':len(inv),'project_rows':len(projects),'reservation_rows':len(demands),'return_rows':len(returns),'matches':sum(r['source_type']!='shortage' for r in results),'shortages':sum(r['source_type']=='shortage' for r in results)}}
def decision(oid,status,owner,note):
 if status not in ['Proposed','Investigating','Approved (internal only)','Rejected','Completed']:raise ValueError('Invalid status')
 c=db()
 with c:c.execute('INSERT OR REPLACE INTO decisions VALUES (?,?,?,?,?)',(oid,status,owner,note,datetime.datetime.now(datetime.timezone.utc).isoformat()))
