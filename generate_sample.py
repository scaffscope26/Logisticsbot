import csv,datetime
from pathlib import Path
from engine import SCHEMAS
p=Path(__file__).parent/'sample_data';p.mkdir(exist_ok=True)
today=datetime.date.today();date=lambda n:(today+datetime.timedelta(days=n)).isoformat()
data={
'inventory':[['Orlando','FR-100','Scaffold frame',2500],['Jacksonville','PL-200','Steel plank',8000],['Fort Myers','FR-100','Scaffold frame',1000],['Lakeland','BR-300','Cross brace',4000]],
'projects':[['JOB-101','Sample Construction','Orlando','FR-100',7000,date(9)],['JOB-102','Sample Industrial','Tampa','PL-200',9000,date(16)]],
'reservations':[['RES-201','Fort Myers','FR-100',4500,date(14)],['RES-202','Pompano','PL-200',6000,date(12)],['RES-203','Tampa','BR-300',3000,date(21)]],
'returns':[['JOB-101','Orlando','FR-100',3500,date(8)]]}
for kind,rows in data.items():
 with open(p/(kind+'.csv'),'w',newline='') as f:w=csv.writer(f);w.writerow(SCHEMAS[kind]);w.writerows(rows)
print('Sample CSVs created')
