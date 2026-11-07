"""Independently compare deliverables with original SQLite records; output statistics only."""
import datetime as dt
import hashlib
import html.parser
import json
import pathlib
import plistlib
import sqlite3
import sys
from urllib.parse import unquote, urlsplit

task = pathlib.Path(sys.argv[1]).resolve()
root = task / 'exports/html'
identity = json.loads((task / 'work/target-view-state.json').read_text(encoding='utf-8'))
inventory = json.loads((task / 'work/source-table-inventory.json').read_text(encoding='utf-8'))
from common import backup_for, config, decode_body, TimeWindow, display_timezone
backup = backup_for(task)
options = config(task)
window = TimeWindow.from_config(options)
where, parameters = window.sql()
source_file = backup / inventory['databases'][0]['fileID'][:2] / inventory['databases'][0]['fileID']
assert hashlib.file_digest(source_file.open('rb'), 'sha256').hexdigest() == identity['original_message_database_sha256']
with sqlite3.connect(source_file.as_uri() + '?mode=ro', uri=True) as con:
    original = con.execute('SELECT MesLocalID,CreateTime,Des,Type,Message FROM "' + identity['table'] + '"' + where + ' ORDER BY CreateTime,MesLocalID', parameters).fetchall()


class Reader(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.records, self.links = [], []
        self.current, self.body, self.meta = None, False, False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        for name in ('href', 'src'):
            if name in attributes:
                self.links.append(attributes[name])
        if tag == 'article':
            self.current = {key: attributes.get('data-' + key) for key in ('id', 'epoch', 'direction', 'type', 'unparsed')}
            self.current.update(body='', meta='')
        elif self.current and tag == 'div':
            self.body = attributes.get('class') == 'body'
            self.meta = attributes.get('class') == 'meta'

    def handle_data(self, data):
        if self.current and self.body:
            self.current['body'] += data
        if self.current and self.meta:
            self.current['meta'] += data

    def handle_endtag(self, tag):
        if tag == 'div':
            self.body = self.meta = False
        elif tag == 'article' and self.current:
            self.records.append(self.current)
            self.current = None


html_bytes = (root / 'index.html').read_bytes()
html_text = html_bytes.decode('utf-8', 'strict')
reader = Reader()
reader.feed(html_text)
assert len(reader.records) == len(original) == identity['record_count']
text_bytes = (task / 'exports/txt/chat.txt').read_bytes()
text_bytes.decode('utf-8', 'strict')
text_index = json.loads((task / 'work/txt-byte-index.json').read_text(encoding='utf-8'))
assert len(text_index) == len(original)
readable = gaps = replacement_chars_in_source = 0
for source, exported, text_item in zip(original, reader.records, text_index):
    id_, epoch, direction, type_, message = source
    assert [int(exported[k]) for k in ('id', 'epoch', 'direction', 'type')] == [id_, epoch, direction, type_]
    assert text_item['id'] == id_
    txt_body = text_bytes[text_item['offset']:text_item['offset'] + text_item['length']].decode('utf-8', 'strict')
    assert txt_body == exported['body']
    decoded,_=decode_body(message,0 if isinstance(message,str) else 2,config(task))
    if decoded is not None:
        assert exported['body'] == decoded and exported['unparsed'] == '0'
        replacement_chars_in_source += decoded.count('\ufffd')
        readable += 1
    else:
        assert exported['unparsed'] == '1' and '正文未解析' in exported['body'] and str(id_) in exported['body']
        gaps += 1
missing = []
external = []
for link in reader.links:
    if link.startswith('#'):
        assert any(r['id'] == link[2:] for r in reader.records)
        continue
    parsed = urlsplit(link)
    if parsed.scheme or parsed.netloc:
        external.append(link)
        continue
    destination = (root / unquote(parsed.path)).resolve()
    assert destination.is_relative_to(root)
    if not destination.is_file():
        missing.append(link)
assert not missing and not external
media = json.loads((root / 'media-index.json').read_text(encoding='utf-8'))
for item in media:
    path = (root / item['href']).resolve()
    assert path.is_relative_to(root)
    assert path.stat().st_size == item['bytes']
    assert hashlib.file_digest(path.open('rb'), 'sha256').hexdigest() == item['sha256']
assert all(original[i][1] <= original[i+1][1] for i in range(len(original)-1))
tz = display_timezone(options)
samples = []
for index in sorted({0, len(original)//2, len(original)-1}) if original else []:
    source = original[index]
    timestamp = dt.datetime.fromtimestamp(source[1], tz).strftime('%Y-%m-%d %H:%M:%S')
    assert timestamp in reader.records[index]['meta']
    samples.append({'position': index + 1, 'timestamp_display': timestamp, 'id_time_direction_body_or_gap_match': True,
                    'body_readable': isinstance(source[4], str)})
result = {'source_records': len(original), 'html_records': len(reader.records), 'txt_records': len(text_index),
          'source_readable_bodies_exactly_matched': readable, 'explicit_unparsed_records': gaps,
          'all_record_ids_times_directions_types_match': True, 'source_time_order_preserved': True,
          'html_utf8_strict': True, 'txt_utf8_strict': True, 'source_replacement_characters': replacement_chars_in_source,
          'missing_local_resource_paths': len(missing), 'external_resource_paths': len(external),
          'media_files_hash_verified': len(media), 'zero_byte_media_files': sum(i['bytes'] == 0 for i in media),
          'original_source_database_hash_unchanged': True, 'samples': samples,
          'display_timezone': options.get('display_timezone', '+08:00'), 'time_range': window.describe(),
          'earliest': samples[0]['timestamp_display'] if samples else None,
          'latest': samples[-1]['timestamp_display'] if samples else None}
backup_time = None
if (backup / 'Info.plist').is_file():
    with (backup / 'Info.plist').open('rb') as handle:
        info = plistlib.load(handle)
    raw_time = info.get('Last Backup Date')
    backup_time = raw_time.isoformat() if isinstance(raw_time, dt.datetime) else raw_time
result.update(wrapper_version='0.1.0', backup_time_metadata=backup_time,
              backup_time_note='Literal metadata; absent timezone is not inferred',
              conversion=options.get('conversion', 'disabled'),
              phone_ui_comparison='not verified', full_phone_history_coverage='not verified')
(task / 'work/export-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
(task / 'export-report.txt').write_text(
    'Local chat export report\n' + json.dumps(result, ensure_ascii=False, indent=2) + '\nMedia verification:\n' +
    (task / 'work/media-verification.json').read_text(encoding='utf-8') +
    '\nScope: readable records in the explicitly selected backup, contact and time window only.\n'
    'Phone UI comparison and complete phone-history coverage: not verified.\n', encoding='utf-8')
print(json.dumps(result, ensure_ascii=False))
