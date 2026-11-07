"""Create a target-only working view; never modify the original Apple backup."""
import hashlib
import json
import os
import pathlib
import re
import shutil
import sqlite3
import sys
import zstandard

task = pathlib.Path(sys.argv[1]).resolve()
from common import backup_for, config, decode_body, TimeWindow, media_message_id
backup = backup_for(task)
options = config(task)
window = TimeWindow.from_config(options)
where, parameters = window.sql()
identity = json.loads((task / 'work/target-identification.json').read_text(encoding='utf-8'))
inventory = json.loads((task / 'work/source-table-inventory.json').read_text(encoding='utf-8'))
assert len(identity['accounts']) == len(identity['matches']) == len(inventory['databases']) == 1
match = identity['matches'][0]
assert match['wechat_id_match'] and match['nickname_match'] and match['remark_match']
account = identity['accounts'][0]
assert account['hash'] == match['account_hash']
owner = account['username']
target = match['username']
prefix = 'Documents/' + account['hash']
target_hash = hashlib.md5(target.encode()).hexdigest()
table = inventory['target_table']
view = task / 'work/target-backup-view'
view.mkdir(exist_ok=False)
domain = 'AppDomain-com.tencent.xin'


def ro(path):
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)


def payload(fid, root=backup):
    assert re.fullmatch('[0-9a-fA-F]{40}', fid)
    return root / fid[:2] / fid


with ro(backup / 'Manifest.db') as source:
    columns = [r[1] for r in source.execute('PRAGMA table_info(Files)')]
    all_rows = source.execute('SELECT * FROM Files WHERE domain IN (?, ?)',
                              (domain, 'AppDomainGroup-group.com.tencent.xin')).fetchall()
    schema = source.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='Files'").fetchone()[0]
rows = [dict(zip(columns, row)) for row in all_rows]
index = {(r['domain'], r['relativePath']): r for r in rows}
with sqlite3.connect(view / 'Manifest.db') as destination:
    destination.execute(schema)
    destination.executemany('INSERT INTO Files VALUES (' + ','.join('?' for _ in columns) + ')', all_rows)
for name in ('Info.plist', 'Manifest.plist', 'Status.plist'):
    if (backup / name).is_file():
        shutil.copy2(backup / name, view / name)

entry = inventory['databases'][0]
raw_database = task / 'work/target-only-raw.sqlite'
original_payload = payload(entry['fileID'])
source_hash = hashlib.file_digest(original_payload.open('rb'), 'sha256').hexdigest()
with ro(original_payload) as source, sqlite3.connect(raw_database) as destination:
    schema = source.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0]
    destination.execute(schema)
    names = [r[1] for r in source.execute('PRAGMA table_info("' + table + '")')]
    records = source.execute('SELECT * FROM "' + table + '"' + where + ' ORDER BY CreateTime,MesLocalID', parameters).fetchall()
    destination.executemany('INSERT INTO "' + table + '" VALUES (' + ','.join('?' for _ in names) + ')', records)

canonical = []
refs = {target_hash}
body_refs = set()
dict_ids = {}
for sequence, row in enumerate(records, 1):
    record = dict(zip(names, row))
    value = record['Message']
    decoded,dictionary=decode_body(value,record.get('WCDB_CT_Message',0),config(task))
    missing=decoded is None
    if dictionary is not None: dict_ids[str(dictionary)]=dict_ids.get(str(dictionary),0)+1
    digest=hashlib.sha256(value.encode('utf-8') if isinstance(value,str) else value).hexdigest()
    if missing:
        text=f'【正文未解析：Zstd 字典 {dictionary} 未配置；源类型 {record["Type"]}；本地消息 ID {record["MesLocalID"]}；原始字节已保留。】'
    else:
        text=decoded
        found_refs = {value.lower() for value in re.findall(r'(?i)(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])',text)} - {target_hash}
        body_refs.update(found_refs)
        refs.update(found_refs)
    canonical.append({'seq': sequence, 'id': record['MesLocalID'], 'server_id': str(record['MesSvrID']),
                      'epoch': record['CreateTime'], 'direction': record['Des'], 'type': record['Type'],
                      'unparsed': missing, 'recovered_from_compression': isinstance(value,bytes) and not missing, 'dictionary_id': dictionary, 'body': text, 'source_body_sha256': digest})
with (task / 'work/target-records.jsonl').open('w', encoding='utf-8', newline='\n') as handle:
    for record in canonical:
        handle.write(json.dumps(record, ensure_ascii=False) + '\n')
required = {'Documents/LoginInfo2.dat', 'Library/Preferences/com.tencent.xin.plist',
            prefix + '/mmsetting.archive', prefix + '/session/session.db', match['contact_database'], entry['relative']}
for relative in index:
    d, path = relative
    if d == domain and path.startswith('Documents/MMappedKV/mmsetting.archive.' + owner):
        required.add(path)


def restricted_database(relative, selectors):
    metadata = index.get((domain, relative))
    if not metadata or not payload(metadata['fileID']).is_file():
        return
    dest = payload(metadata['fileID'], view)
    dest.parent.mkdir(exist_ok=True)
    with ro(payload(metadata['fileID'])) as source, sqlite3.connect(dest) as destination:
        for name, condition, parameters in selectors:
            schema_row = source.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
            if not schema_row:
                continue
            destination.execute(schema_row[0])
            selected = source.execute('SELECT * FROM "' + name + '"' + condition, parameters).fetchall()
            if selected:
                destination.executemany('INSERT INTO "' + name + '" VALUES (' + ','.join('?' for _ in selected[0]) + ')', selected)


restricted_database(match['contact_database'], [('Friend', ' WHERE userName IN (?,?)', (owner, target)),
                                               ('OpenIMContact', ' WHERE userName IN (?,?)', (owner, target))])
restricted_database(prefix + '/session/session.db', [('SessionAbstract', ' WHERE UsrName=?', (target,))])
session_meta = index.get((domain, prefix + '/session/session.db'))
if session_meta:
    with ro(payload(session_meta['fileID'])) as con:
        ext = con.execute('SELECT ConStrRes1 FROM SessionAbstract WHERE UsrName=?', (target,)).fetchall()
    for item in ext:
        if item[0]:
            path = item[0].replace('\\', '/').lstrip('/')
            required.add(path if path.startswith('Documents/') else prefix + '/' + path)
required.add(prefix + '/session/data/' + target_hash[:2] + '/' + target_hash[2:])
message_dest = payload(entry['fileID'], view)
message_dest.parent.mkdir(exist_ok=True)
shutil.copy2(raw_database, message_dest)
copied = linked = missing = 0
excluded_unassociated = 0
selected_ids = {record['id'] for record in canonical}
selected_media = []
for metadata in rows:
    relative = metadata['relativePath']
    if metadata['flags'] != 1:
        continue
    known_hashes = set(re.findall(r'(?i)[0-9a-f]{32}', relative))
    is_target_media = (metadata['domain'] == domain and relative.startswith(prefix + '/') and
                       (target_hash in relative or bool(known_hashes.intersection(refs))))
    message_id = media_message_id(relative, target_hash)
    if window.bounded and is_target_media:
        reliable = message_id in selected_ids or bool(known_hashes.intersection(body_refs))
        if not reliable:
            excluded_unassociated += 1
            is_target_media = False
    if metadata['domain'] == domain and relative.startswith(prefix + '/DB/'):
        is_target_media = False
    if not (metadata['domain'] == domain and relative in required) and not is_target_media:
        continue
    original = payload(metadata['fileID'])
    destination = payload(metadata['fileID'], view)
    if destination.exists():
        continue
    if not original.is_file():
        missing += 1
        continue
    destination.parent.mkdir(exist_ok=True)
    if relative in required:
        shutil.copy2(original, destination)
        copied += 1
    else:
        shutil.copy2(original, destination)
        linked += 1
    if is_target_media and relative not in required:
        selected_media.append({'fileID': metadata['fileID'], 'domain': metadata['domain'], 'relative': relative,
                               'bytes': original.stat().st_size})
(task / 'work/target-media-source-index.json').write_text(json.dumps(selected_media, ensure_ascii=False, indent=2), encoding='utf-8')
plan = {'view': str(view), 'raw_database': str(raw_database), 'message_payload': str(message_dest),
        'table': table, 'account': account, 'target': match, 'record_count': len(canonical),
        'unparsed_count': sum(r['unparsed'] for r in canonical), 'dictionary_ids': dict_ids,
        'original_message_database_sha256': source_hash, 'metadata_copied': copied,
        'media_hardlinks': 0, 'media_independent_copies': linked, 'missing_selected_payloads': missing,
        'time_range': window.describe(), 'bounded_media_excluded_unassociated': excluded_unassociated,
        'conversion': options.get('conversion', 'disabled')}
(task / 'work/target-view-state.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({key: plan[key] for key in ('record_count', 'unparsed_count', 'dictionary_ids', 'metadata_copied', 'media_hardlinks', 'missing_selected_payloads')}))
