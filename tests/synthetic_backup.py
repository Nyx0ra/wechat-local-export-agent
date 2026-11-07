"""Generate a tiny fictional backup; no captured chat, device or contact data."""
import hashlib
from contextlib import closing
import plistlib
import sqlite3
import zstandard
from pathlib import Path
from PIL import Image

DOMAIN = 'AppDomain-com.tencent.xin'
OWNER = 'synthetic_owner'
TARGET = 'synthetic_friend'
ACCOUNT = hashlib.md5(OWNER.encode()).hexdigest()
TARGET_HASH = hashlib.md5(TARGET.encode()).hexdigest()
TABLE = 'Chat_' + TARGET_HASH
BASE = 'Documents/' + ACCOUNT


def field(number, text):
    value = text.encode()
    assert len(value) < 128
    return bytes([number * 8 + 2, len(value)]) + value


def build_backup(root):
    root = Path(root)
    root.mkdir()
    rows = []
    def add(relative, content):
        fid = hashlib.sha1((DOMAIN + '-' + relative).encode()).hexdigest()
        physical = root / fid[:2] / fid
        physical.parent.mkdir(exist_ok=True)
        if callable(content):
            content(physical)
        else:
            physical.write_bytes(content)
        rows.append((fid, DOMAIN, relative, 1, b''))
        return physical

    settings = {'$objects': ['$null', {'UsrName': plistlib.UID(2), 'NickName': plistlib.UID(3), 'AliasName': plistlib.UID(4)}, OWNER, 'Synthetic Owner', 'synthetic_owner_id']}
    add(BASE + '/mmsetting.archive', plistlib.dumps(settings, fmt=plistlib.FMT_BINARY))
    def contacts(path):
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE Friend(userName TEXT, dbContactRemark BLOB)')
            db.execute('INSERT INTO Friend VALUES (?,?)', (TARGET, field(1, 'Synthetic Friend') + field(2, 'synthetic_friend_id') + field(3, 'Demo Contact')))
            db.execute('INSERT INTO Friend VALUES (?,?)', ('synthetic_other', field(1, 'Other Demo')))
    contact_db = add(BASE + '/DB/WCDB_Contact.sqlite', contacts)
    def sessions(path):
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE SessionAbstract(UsrName TEXT,ConStrRes1 TEXT)')
            db.execute('INSERT INTO SessionAbstract VALUES (?,?)', (TARGET, ''))
    add(BASE + '/session/session.db', sessions)
    def messages(path):
        with closing(sqlite3.connect(path)) as db, db:
            schema = '(MesLocalID INTEGER PRIMARY KEY,MesSvrID INTEGER,CreateTime INTEGER,Des INTEGER,Type INTEGER,Message,WCDB_CT_Message INTEGER)'
            db.execute('CREATE TABLE "' + TABLE + '"' + schema)
            data = [
                (1, 101, 1704124799, 0, 3, 'BEFORE_WINDOW_SENTINEL', 0),
                (2, 102, 1704124800, 0, 1, 'Synthetic <script>alert(1)</script> & text\n第二行', 0),
                (3, 103, 1704124800, 1, 3, 'Synthetic picture', 0),
                (4, 104, 1704128399, 1, 1, zstandard.ZstdCompressor().compress(b'Synthetic compressed body'), 2),
                (5, 105, 1704128400, 0, 3, 'EXCLUSIVE_END_SENTINEL', 0),
                (6, 106, 1704128401, 1, 34, 'AFTER_WINDOW_SENTINEL', 0),
                (7, 107, 1704125000, 1, 34, 'Synthetic missing audio', 0),
            ]
            db.executemany('INSERT INTO "' + TABLE + '" VALUES (?,?,?,?,?,?,?)', data)
            other = 'Chat_' + hashlib.md5(b'synthetic_other').hexdigest()
            db.execute('CREATE TABLE "' + other + '"' + schema)
            db.execute('INSERT INTO "' + other + '" VALUES (900,900,1704125000,1,1,?,0)', ('OTHER_CONTACT_SENTINEL',))
    message_db = add(BASE + '/DB/message_1.sqlite', messages)
    for id_ in (1, 3, 5):
        add(BASE + '/Img/' + TARGET_HASH + '/' + str(id_) + '.png', lambda path: Image.new('RGB', (4, 4), (20, 60, 100)).save(path, format='PNG'))
    add(BASE + '/Img/' + TARGET_HASH + '/unassociated.bin', b'Synthetic unassociated media')
    with closing(sqlite3.connect(root / 'Manifest.db')) as db, db:
        db.execute('CREATE TABLE Files(fileID TEXT PRIMARY KEY,domain TEXT,relativePath TEXT,flags INTEGER,file BLOB)')
        db.executemany('INSERT INTO Files VALUES (?,?,?,?,?)', rows)
    for name, data in [('Status.plist', {'SnapshotState': 'finished'}), ('Manifest.plist', {'IsEncrypted': False}), ('Info.plist', {'Device Name': 'Synthetic Device'})]:
        (root / name).write_bytes(plistlib.dumps(data))
    return {'message_db': message_db, 'contact_db': contact_db, 'table': TABLE}
