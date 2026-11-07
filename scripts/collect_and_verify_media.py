"""Copy only target media and verify formats locally; never print payloads."""
import collections
import concurrent.futures
import hashlib
import json
import pathlib
import re
import shutil
import sys
import av
from PIL import Image

av.logging.set_level(av.logging.PANIC)
task = pathlib.Path(sys.argv[1]).resolve()
from common import backup_for, config, decode_body, media_message_id
backup = backup_for(task)
root = task / 'exports/html'
media_root = root / 'media'
media_root.mkdir(exist_ok=True)
source_index = json.loads((task / 'work/target-media-source-index.json').read_text(encoding='utf-8'))
records = [json.loads(line) for line in (task / 'work/target-records.jsonl').read_text(encoding='utf-8').splitlines()]
ids = {r['id'] for r in records}
state = json.loads((task / 'work/target-view-state.json').read_text(encoding='utf-8'))
target_hash = hashlib.md5(state['target']['username'].encode()).hexdigest()
entries = []


def local_id(relative):
    scoped = media_message_id(relative, target_hash)
    if scoped in ids:
        return scoped
    hashes = set(re.findall(r'(?i)[0-9a-f]{32}', relative)) - {target_hash}
    matches = [record['id'] for record in records if not record['unparsed'] and any(h in record['body'].lower() for h in hashes)]
    return matches[0] if len(matches) == 1 else None


def converted_local_id(relative):
    match = re.match(r'^(\d+)(?:[._]|$)', pathlib.PurePosixPath(relative).name)
    return int(match[1]) if match and int(match[1]) in ids else None


def add(source, name, source_kind, relative):
    destination = media_root / source_kind / name
    destination.parent.mkdir(exist_ok=True)
    shutil.copy2(source, destination)
    entries.append({'id': converted_local_id(relative) if source_kind == 'converted' else local_id(relative), 'href': destination.relative_to(root).as_posix(),
                    'source_kind': source_kind, 'source_relative': relative, 'bytes': source.stat().st_size,
                    'thumbnail': bool(re.search('thum|thumb', relative, re.I))})


for item in source_index:
    source = backup / item['fileID'][:2] / item['fileID']
    basename = pathlib.PurePosixPath(item['relative']).name
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', basename)[:160]
    add(source, item['fileID'][:12] + '-' + safe, 'original', item['relative'])
for source in (task / 'work/official-raw-export').rglob('*'):
    if source.is_file() and source.suffix.lower() in ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.mp3', '.mp4'):
        if converted_local_id(source.name) is not None:
            add(source, source.name, 'converted', source.name)


def validate(entry):
    path = root / entry['href']
    entry['sha256'] = hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()
    entry['kind'] = 'attachment'
    suffix = path.suffix.lower()
    if suffix in ('.mp3', '.mp4') and entry['source_kind'] == 'converted':
        entry['kind'] = 'audio' if suffix == '.mp3' else 'video'
        try:
            count = 0
            seconds = 0.0
            with av.open(str(path)) as container:
                streams = [s.type for s in container.streams]
                for frame in container.decode():
                    count += 1
                    if isinstance(frame, av.AudioFrame):
                        seconds += frame.samples / frame.sample_rate
            assert count > 0
            entry.update(valid=True, decoded_frames=count, audio_seconds=round(seconds, 4), streams=streams)
        except Exception as error:
            entry.update(valid=False, error=type(error).__name__)
    elif suffix in ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.pic', '.pic_thum', '.video_thum') or '/Img/' in entry['source_relative']:
        entry['kind'] = 'image'
        try:
            with Image.open(path) as image:
                entry.update(format=image.format, width=image.width, height=image.height)
                image.verify()
            with Image.open(path) as image:
                image.load()
            entry['valid'] = True
        except Exception as error:
            entry.update(valid=False, error=type(error).__name__)
    else:
        entry['valid'] = None
    return entry


with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    entries = list(pool.map(validate, entries))
(root / 'media-index.json').write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding='utf-8')
summary = {'original_files': sum(e['source_kind'] == 'original' for e in entries),
           'converted_files': sum(e['source_kind'] == 'converted' for e in entries),
           'unassociated_files': sum(e['id'] is None for e in entries), 'types': {}, 'message_coverage': {},
           'conversion': state.get('conversion', 'disabled'),
           'bounded_media_excluded_unassociated': state.get('bounded_media_excluded_unassociated', 0),
           'missing_selected_payloads': state.get('missing_selected_payloads', 0)}
for kind in ('audio', 'video', 'image', 'attachment'):
    subset = [e for e in entries if e['kind'] == kind]
    summary['types'][kind] = {'files': len(subset), 'verified': sum(e['valid'] is True for e in subset),
                            'failed_or_unsupported': sum(e['valid'] is False for e in subset),
                            'unverified': sum(e['valid'] is None for e in subset)}
for typ, kind in ((34, 'audio'), (43, 'video'), (3, 'image')):
    expected = {r['id'] for r in records if r['type'] == typ}
    usable = {e['id'] for e in entries if e['kind'] == kind and e['valid'] is True}
    full = {e['id'] for e in entries if e['kind'] == kind and e['valid'] is True and not e['thumbnail']}
    summary['message_coverage'][kind] = {'source_records': len(expected), 'with_verified_media': len(expected & usable),
                                        'with_verified_non_thumbnail': len(expected & full)}
(task / 'work/media-verification.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
print(json.dumps(summary), flush=True)
