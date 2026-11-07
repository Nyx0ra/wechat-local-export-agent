import hashlib,json,pathlib,sqlite3,sys
from common import backup_for, config, TimeWindow
task=pathlib.Path(sys.argv[1]).resolve();backup=backup_for(task)
window=TimeWindow.from_config(config(task))
where,parameters=window.sql()
identity=json.loads((task/'work/target-identification.json').read_text(encoding='utf-8'))
if len(identity['accounts'])!=1 or len(identity['matches'])!=1:
    raise ValueError('Select exactly one account and one contact; no automatic first match')
m=identity['matches'][0]
if not all(m[k] for k in ('wechat_id_match','nickname_match','remark_match')):
    raise ValueError('Configured identity fields disagree; review metadata locally')
table='Chat_'+hashlib.md5(m['username'].encode()).hexdigest()
with sqlite3.connect((backup/'Manifest.db').as_uri()+'?mode=ro',uri=True) as con:
    rows=con.execute('SELECT fileID,relativePath FROM Files WHERE domain=? AND relativePath LIKE ?',
                     ('AppDomain-com.tencent.xin','Documents/'+m['account_hash']+'/DB/%.sqlite')).fetchall()
out=[]
for fid,relative in rows:
    p=backup/fid[:2]/fid
    if not p.is_file():continue
    with p.open('rb') as handle: signature=handle.read(16)
    if signature!=b'SQLite format 3\x00':
        raise ValueError('Non-readable SQLite input; SQLCipher/backup decryption is not implemented')
    with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True) as db:
        if not db.execute('SELECT 1 FROM sqlite_master WHERE type=? AND name=?',('table',table)).fetchone():continue
        cols=[r[1] for r in db.execute('PRAGMA table_info("'+table+'")')]
        required={'MesLocalID','MesSvrID','CreateTime','Des','Type','Message','WCDB_CT_Message'}
        if not required.issubset(cols):raise ValueError('Unsupported message table schema')
        stats=db.execute('SELECT count(*),min(CreateTime),max(CreateTime) FROM "'+table+'"').fetchone()
        selected=db.execute('SELECT count(*),min(CreateTime),max(CreateTime) FROM "'+table+'"'+where,parameters).fetchone()
        out.append({'relative':relative,'fileID':fid,'columns':cols,'count':stats[0],
                    'earliest_epoch':stats[1],'latest_epoch':stats[2],
                    'selected_count':selected[0], 'selected_earliest_epoch':selected[1], 'selected_latest_epoch':selected[2],
                    'types':db.execute('SELECT Type,count(*) FROM "'+table+'" GROUP BY Type').fetchall()})
if len(out)!=1:raise ValueError('Exactly one target message database is required; multi-shard merge is not implemented')
(task/'work/source-table-inventory.json').write_text(json.dumps({'target_table':table,'databases':out,'time_range':window.describe()},indent=2),encoding='utf-8')
print(json.dumps({'target_databases':len(out),'source_records':sum(r['count'] for r in out)}))
