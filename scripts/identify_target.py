"""Identify account/contact metadata only after an Apple backup is finished."""
import hashlib
import json
import pathlib
import plistlib
import re
import sqlite3
import sys


def varint(data, pos):
    value = 0
    for shift in range(0, 70, 7):
        if pos >= len(data):
            raise ValueError('truncated protobuf varint')
        byte = data[pos]
        pos += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, pos
    raise ValueError('oversized protobuf varint')


def proto(data):
    fields = {}
    pos = 0
    while pos < len(data):
        tag, pos = varint(data, pos)
        number, wire = tag >> 3, tag & 7
        if not number:
            raise ValueError('invalid protobuf field')
        if wire == 0:
            value, pos = varint(data, pos)
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4
            value, pos = data[pos:pos + size], pos + size
        elif wire == 2:
            size, pos = varint(data, pos)
            value, pos = data[pos:pos + size], pos + size
        else:
            raise ValueError('unsupported protobuf wire type')
        if pos > len(data):
            raise ValueError('truncated protobuf field')
        fields.setdefault(number, []).append(value)
    return fields


def string(fields, number):
    values = fields.get(number, [])
    return values[0].decode('utf-8', 'strict') if values and isinstance(values[0], bytes) else ''


def ro(path):
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)


def identify(backup, output, options):
    target_info=options["target"]
    terms={v for k,v in target_info.items() if k in ("remark","nickname","wechat_id") and v}
    if not terms: raise ValueError("Specify at least one target identity field")
    with (backup / 'Status.plist').open('rb') as handle:
        status = plistlib.load(handle)
    with (backup / 'Manifest.plist').open('rb') as handle:
        manifest = plistlib.load(handle)
    if status.get('SnapshotState') != 'finished' or manifest.get('IsEncrypted', True):
        raise ValueError('backup must be finished and unencrypted')
    with ro(backup / 'Manifest.db') as con:
        rows = con.execute("SELECT fileID, domain, relativePath FROM Files WHERE domain IN (?, ?)",
                           ('AppDomain-com.tencent.xin', 'AppDomainGroup-group.com.tencent.xin')).fetchall()
    index = {(domain, relative): fileid for fileid, domain, relative in rows}
    domain = 'AppDomain-com.tencent.xin'

    def physical(relative):
        fileid = index.get((domain, relative))
        if not fileid or not re.fullmatch('[0-9a-fA-F]{40}', fileid):
            return None
        path = backup / fileid[:2] / fileid
        return path if path.is_file() else None

    result = {'accounts': [], 'matches': [], 'errors': [], 'wechat_manifest_entries': len(rows),
              'database_inventory': [relative for _, d, relative in rows if d == domain and re.search(r'/DB/.*\.sqlite$', relative)]}
    login = physical('Documents/LoginInfo2.dat')
    if login:
        try:
            packed = proto(login.read_bytes()).get(1, [b''])[0]
            pos = 0
            while pos < len(packed):
                size, pos = varint(packed, pos)
                block = proto(packed[pos:pos + size])
                pos += size
                username = string(block, 1)
                result['accounts'].append({'username': username, 'alias': string(block, 2),
                                           'nickname': string(block, 3),
                                           'hash': hashlib.md5(username.encode()).hexdigest()})
        except Exception as error:
            result['errors'].append({'stage': 'LoginInfo2', 'type': type(error).__name__})
    contact_paths = sorted(relative for _, d, relative in rows if d == domain and
                           re.fullmatch(r'Documents/[0-9a-f]{32}/DB/WCDB_Contact\.sqlite', relative))
    for relative in contact_paths:
        account_hash = relative.split('/')[1]
        if not any(a['hash'] == account_hash for a in result['accounts']):
            account = {'hash': account_hash, 'username': '', 'nickname': '', 'alias': ''}
            settings = physical(f'Documents/{account_hash}/mmsetting.archive')
            if settings:
                try:
                    objects = plistlib.loads(settings.read_bytes())['$objects']
                    settings_dict = objects[1]
                    for key, name in [('UsrName', 'username'), ('NickName', 'nickname'), ('AliasName', 'alias')]:
                        ref = settings_dict.get(key)
                        if isinstance(ref, plistlib.UID) and isinstance(objects[ref.data], str):
                            account[name] = objects[ref.data]
                except Exception as error:
                    result['errors'].append({'stage': 'account_settings', 'type': type(error).__name__})
            result['accounts'].append(account)
        path = physical(relative)
        if not path:
            result['errors'].append({'stage': 'contact_payload_missing', 'account_hash': account_hash})
            continue
        try:
            with ro(path) as con:
                tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for table in ('Friend', 'OpenIMContact'):
                    if table not in tables:
                        continue
                    for username, remark_blob in con.execute(f'SELECT userName,dbContactRemark FROM "{table}"'):
                        try:
                            fields = proto(remark_blob or b'')
                            nick, alias, remark = (string(fields, number) for number in (1, 2, 3))
                        except Exception:
                            continue
                        values = {username, nick, alias, remark}
                        if values.intersection(terms):
                            result['matches'].append({'account_hash': account_hash, 'table': table,
                                                      'username': username, 'nickname': nick, 'alias': alias,
                                                      'remark': remark, 'contact_database': relative,
                                                      'wechat_id_match': (not target_info.get('wechat_id') or target_info['wechat_id'] in (username,alias)),
                                                      'nickname_match': (not target_info.get('nickname') or nick == target_info['nickname']), 'remark_match': (not target_info.get('remark') or remark == target_info['remark'])})
        except Exception as error:
            result['errors'].append({'stage': 'contact_database', 'account_hash': account_hash, 'type': type(error).__name__})
    selected=options.get('account_hash')
    if selected:
        result['accounts']=[a for a in result['accounts'] if a['hash']==selected]
        result['matches']=[m for m in result['matches'] if m['account_hash']==selected]
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'accounts': len(result['accounts']), 'target_candidates': len(result['matches']),
                      'exact_wechat_id_matches': sum(m['wechat_id_match'] for m in result['matches']),
                      'errors': len(result['errors'])}))


if __name__ == '__main__':
    identify(pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), json.loads(pathlib.Path(sys.argv[3]).read_text(encoding='utf-8-sig')))
