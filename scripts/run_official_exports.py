"""Run the original exporter on a scoped view; preserve raw output and mark unreadable bodies."""
import collections
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import time

task = pathlib.Path(sys.argv[1]).resolve()
state = json.loads((task / 'work/target-view-state.json').read_text(encoding='utf-8'))
records = [json.loads(line) for line in (task / 'work/target-records.jsonl').read_text(encoding='utf-8').splitlines()]
from common import exporter_for
exe = exporter_for(task)
environment = os.environ.copy()
for key in ('http_proxy', 'https_proxy', 'ALL_PROXY'):
    environment[key] = 'http://127.0.0.1:1'
environment['NO_PROXY'] = ''


def export(name, format_, output):
    output.mkdir(parents=True, exist_ok=True)
    assert not any(output.iterdir()), 'Output must be fresh'
    args = [str(exe), '--backup=' + state['view'], '--output=' + str(output), '--format=' + format_,
            '--account=' + state['account']['nickname'], '--session=' + (state['target'].get('remark') or state['target'].get('nickname') or state['target']['username']),
            '--asyncloading=oninit']
    start = time.monotonic()
    with (task / 'work' / (name + '.log')).open('wb') as log:
        result = subprocess.run(args, cwd=exe.parent, env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=900)
    print(json.dumps({'stage': name, 'exit': result.returncode, 'seconds': round(time.monotonic() - start, 1),
                      'files': sum(1 for p in output.rglob('*') if p.is_file())}), flush=True)
    if result.returncode:
        raise RuntimeError('Original exporter returned nonzero; inspect local log')


if '--resume' not in sys.argv:
    export('official-raw-export', 'text', task / 'work/official-raw-export')
table = state['table']
with sqlite3.connect(state['message_payload']) as work, sqlite3.connect(state['raw_database']) as original:
    updates = [(r['body'], r['id']) for r in records if r['unparsed']]
    work.executemany('UPDATE "' + table + '" SET Message=?,Type=1,WCDB_CT_Message=0 WHERE MesLocalID=?', updates)
    recovered=[(r['body'],r['type'],r['id']) for r in records if r.get('recovered_from_compression')]
    work.executemany('UPDATE "'+table+'" SET Message=?,Type=?,WCDB_CT_Message=0 WHERE MesLocalID=?',recovered)
    work.commit()
    cols = [r[1] for r in work.execute('PRAGMA table_info("' + table + '")')]
    fixed = [c for c in cols if c not in ('Message', 'Type', 'WCDB_CT_Message')]
    quoted = ','.join('"' + c + '"' for c in fixed)
    before = original.execute('SELECT ' + quoted + ' FROM "' + table + '" ORDER BY CreateTime,MesLocalID').fetchall()
    after = work.execute('SELECT ' + quoted + ' FROM "' + table + '" ORDER BY CreateTime,MesLocalID').fetchall()
    assert before == after and len(after) == state['record_count']
    ordinary = {r['id']: r['body'] for r in records if not r['unparsed']}
    assert all(message == ordinary[id_] for id_, message in work.execute(
        'SELECT MesLocalID,Message FROM "' + table + '"') if id_ in ordinary)
print(json.dumps({'stage': 'explicit-placeholders-prepared', 'records': len(records),
                  'placeholders': len(updates), 'identity_time_id_fields_unchanged': True,
                  'unparsed_by_type': dict(collections.Counter(str(r['type']) for r in records if r['unparsed']))}), flush=True)
export('official-html', 'html', task / 'exports/html/tool-export')
# The released Windows CLI advertises --format but ignores it in its argument parser.
# UTF-8 TXT is therefore generated separately from the verified source records.
