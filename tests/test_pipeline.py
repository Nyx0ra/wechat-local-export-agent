import hashlib
from contextlib import closing
import json
import pathlib
import plistlib
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from tests.synthetic_backup import build_backup, TABLE

ROOT = pathlib.Path(__file__).resolve().parents[1]


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='wxsynthetic-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.backup = self.root / 'backup'
        self.source = build_backup(self.backup)
        self.case = self.root / 'case'
        self.cfg = {'backup_dir': str(self.backup), 'case_dir': str(self.case),
                    'target': {'wechat_id': 'synthetic_friend_id'},
                    'conversion': 'disabled', 'display_timezone': '+08:00',
                    'time_range': {'start': '2024-01-02T00:00:00+08:00', 'end': '2024-01-02T01:00:00+08:00'}}
        self.cfgpath = self.root / 'config.json'

    def stage(self, stage, success=True):
        self.assertTrue((ROOT / 'wxlocal.py').is_file(), 'CLI has not been implemented')
        self.cfgpath.write_text(json.dumps(self.cfg), encoding='utf-8')
        result = subprocess.run([sys.executable, str(ROOT / 'wxlocal.py'), '--config', str(self.cfgpath), stage], capture_output=True, text=True, encoding='utf-8')
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def pipeline(self):
        return self.stage('run')

    def test_filtered_pipeline_isolated_and_verified(self):
        before = hashlib.sha256(self.source['message_db'].read_bytes()).hexdigest()
        self.pipeline()
        records = [json.loads(line) for line in (self.case / 'work/target-records.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual([r['id'] for r in records], [2, 3, 7, 4])
        with closing(sqlite3.connect(self.case / 'work/target-only-raw.sqlite')) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM "' + TABLE + '"').fetchone()[0], 4)
        text = (self.case / 'exports/txt/chat.txt').read_text(encoding='utf-8')
        page = (self.case / 'exports/html/index.html').read_text(encoding='utf-8')
        for sentinel in ('BEFORE_WINDOW_SENTINEL', 'EXCLUSIVE_END_SENTINEL', 'AFTER_WINDOW_SENTINEL', 'OTHER_CONTACT_SENTINEL'):
            self.assertNotIn(sentinel, text + page)
        self.assertIn('&lt;script&gt;', page)
        self.assertNotIn('<script>alert', page)
        self.assertIn('正文未解析', text)
        self.assertIn('未找到', text)
        media = json.loads((self.case / 'exports/html/media-index.json').read_text(encoding='utf-8'))
        self.assertEqual(len(media), 1)
        self.assertEqual(media[0]['id'], 3)
        self.assertTrue(media[0]['valid'])
        verify = json.loads((self.case / 'work/export-verification.json').read_text(encoding='utf-8'))
        self.assertEqual(verify['source_records'], 4)
        self.assertEqual(verify['explicit_unparsed_records'], 1)
        self.assertEqual(verify['media_files_hash_verified'], 1)
        self.assertEqual(before, hashlib.sha256(self.source['message_db'].read_bytes()).hexdigest())
        self.assertTrue((self.case / 'export-report.txt').is_file())

    def test_empty_window(self):
        self.cfg['time_range'] = {'start': '2030-01-01T00:00:00Z'}
        self.pipeline()
        result = json.loads((self.case / 'work/export-verification.json').read_text(encoding='utf-8'))
        self.assertEqual(result['source_records'], 0)
        self.assertEqual(result['media_files_hash_verified'], 0)

    def test_bad_range_fails_before_case_creation(self):
        self.cfg['time_range'] = {'start': '2024-01-01'}
        self.stage('identify', success=False)
        self.assertFalse(self.case.exists())

    def test_config_change_requires_new_case(self):
        self.stage('identify')
        self.cfg['time_range'] = None
        self.stage('inventory', success=False)

    def test_ambiguous_contact_stops(self):
        with closing(sqlite3.connect(self.source['contact_db'])) as db, db:
            row = db.execute('SELECT dbContactRemark FROM Friend WHERE userName=?', ('synthetic_friend',)).fetchone()
            db.execute('INSERT INTO Friend VALUES (?,?)', ('synthetic_duplicate', row[0]))
        self.stage('identify', success=False)

    def test_backup_and_case_overlap_rejected(self):
        self.cfg['case_dir'] = str(self.backup / 'nested')
        self.stage('identify', success=False)
        self.assertFalse((self.backup / 'nested').exists())

    def test_tampered_html_rejected(self):
        self.pipeline()
        path = self.case / 'exports/html/index.html'
        path.write_text(path.read_text(encoding='utf-8').replace('Synthetic &lt;script&gt;', 'Altered &lt;script&gt;'), encoding='utf-8')
        self.stage('verify', success=False)

    def test_tampered_media_rejected(self):
        self.pipeline()
        media = next((self.case / 'exports/html/media/original').iterdir())
        media.write_bytes(b'bad media')
        self.stage('verify', success=False)

    def test_all_time_export_preserves_all_target_records(self):
        self.cfg['time_range'] = None
        self.pipeline()
        result = json.loads((self.case / 'work/export-verification.json').read_text(encoding='utf-8'))
        self.assertEqual(result['source_records'], 7)
        self.assertNotIn('OTHER_CONTACT_SENTINEL', (self.case / 'exports/txt/chat.txt').read_text(encoding='utf-8'))

    def test_encrypted_and_unfinished_backup_rejected(self):
        (self.backup / 'Manifest.plist').write_bytes(plistlib.dumps({'IsEncrypted': True}))
        self.stage('identify', success=False)
        self.assertFalse((self.case / 'work/target-records.jsonl').exists())

    def test_unfinished_backup_rejected(self):
        (self.backup / 'Status.plist').write_bytes(plistlib.dumps({'SnapshotState': 'in-progress'}))
        self.stage('identify', success=False)

    def test_output_in_source_project_rejected(self):
        self.cfg['case_dir'] = str(ROOT / 'private-case-must-not-exist')
        self.stage('identify', success=False)
        self.assertFalse((ROOT / 'private-case-must-not-exist').exists())

    def test_stage_order_enforced(self):
        self.stage('identify')
        self.stage('render', success=False)

    def test_group_contact_rejected_before_content_access(self):
        with closing(sqlite3.connect(self.source['contact_db'])) as db, db:
            db.execute('UPDATE Friend SET userName=? WHERE userName=?', ('synthetic_room@chatroom', 'synthetic_friend'))
        self.stage('identify', success=False)

    def test_unsupported_schema_rejected(self):
        with closing(sqlite3.connect(self.source['message_db'])) as db, db:
            db.execute('ALTER TABLE "' + TABLE + '" RENAME COLUMN Message TO UnsupportedBody')
        self.stage('identify')
        self.stage('inventory', success=False)

    def test_unknown_direction_not_invented(self):
        with closing(sqlite3.connect(self.source['message_db'])) as db, db:
            db.execute('UPDATE "' + TABLE + '" SET Des=9 WHERE MesLocalID=2')
        self.pipeline()
        text = (self.case / 'exports/txt/chat.txt').read_text(encoding='utf-8')
        self.assertIn('未知方向（源值 9）', text)

    def test_synthetic_mp3_decoded_and_linked(self):
        import av
        for stage in ('identify', 'inventory', 'prepare'):
            self.stage(stage)
        directory = self.case / 'work/official-raw-export/synthetic'
        directory.mkdir(parents=True)
        path = directory / '7.mp3'
        with av.open(str(path), mode='w', format='mp3') as output:
            stream = output.add_stream('libmp3lame', rate=8000)
            stream.layout = 'mono'
            frame = av.AudioFrame(format='s16', layout='mono', samples=800)
            frame.sample_rate = 8000
            frame.planes[0].update(bytes(frame.planes[0].buffer_size))
            for packet in stream.encode(frame):
                output.mux(packet)
            for packet in stream.encode(None):
                output.mux(packet)
        for stage in ('media', 'render', 'verify'):
            self.stage(stage)
        result = json.loads((self.case / 'work/media-verification.json').read_text(encoding='utf-8'))
        self.assertEqual(result['message_coverage']['audio']['with_verified_media'], 1)
        self.assertIn('<audio controls', (self.case / 'exports/html/index.html').read_text(encoding='utf-8'))

    def test_selected_missing_payload_reported(self):
        with closing(sqlite3.connect(self.backup / 'Manifest.db')) as db:
            fid = db.execute("SELECT fileID FROM Files WHERE relativePath LIKE '%/3.png'").fetchone()[0]
        (self.backup / fid[:2] / fid).unlink()
        self.pipeline()
        report = json.loads((self.case / 'work/media-verification.json').read_text(encoding='utf-8'))
        self.assertEqual(report['missing_selected_payloads'], 1)
        self.assertEqual(report['original_files'], 0)

    def test_other_account_media_not_copied(self):
        from tests.synthetic_backup import TARGET_HASH
        fid = 'e' * 40
        relative = 'Documents/' + 'd' * 32 + '/Img/' + TARGET_HASH + '/3.png'
        with closing(sqlite3.connect(self.backup / 'Manifest.db')) as db, db:
            selected = db.execute("SELECT fileID FROM Files WHERE relativePath LIKE '%/3.png'").fetchone()[0]
            db.execute('INSERT INTO Files VALUES (?,?,?,?,?)', (fid, 'AppDomain-com.tencent.xin', relative, 1, b''))
        destination = self.backup / 'ee' / fid
        destination.parent.mkdir(exist_ok=True)
        destination.write_bytes((self.backup / selected[:2] / selected).read_bytes())
        self.pipeline()
        media = json.loads((self.case / 'exports/html/media-index.json').read_text(encoding='utf-8'))
        self.assertEqual(len(media), 1)

    def test_unsupported_outside_window_body_not_processed(self):
        with closing(sqlite3.connect(self.source['message_db'])) as db, db:
            db.execute('UPDATE "' + TABLE + '" SET Message=?,WCDB_CT_Message=99 WHERE MesLocalID=1', (b'unsupported synthetic encoding',))
        self.pipeline()

    def test_sender_and_timezone_display(self):
        self.cfg['display_timezone'] = '+00:00'
        self.pipeline()
        text = (self.case / 'exports/txt/chat.txt').read_text(encoding='utf-8')
        self.assertIn('2024-01-01 16:00:00 | Synthetic Owner', text)
        self.assertIn('2024-01-01 16:00:00 | Demo Contact', text)

    def test_multi_shard_rejected(self):
        # Another manifest entry pointing at a valid database containing the same target table.
        with closing(sqlite3.connect(self.backup / 'Manifest.db')) as db, db:
            row = db.execute("SELECT * FROM Files WHERE relativePath LIKE '%/message_1.sqlite'").fetchone()
            db.execute('INSERT INTO Files VALUES (?,?,?,?,?)', ('f' * 40, row[1], row[2].replace('message_1', 'message_2'), 1, b''))
        extra = self.backup / 'ff' / ('f' * 40)
        extra.parent.mkdir(exist_ok=True)
        extra.write_bytes(self.source['message_db'].read_bytes())
        self.stage('identify')
        self.stage('inventory', success=False)


if __name__ == '__main__':
    unittest.main()
