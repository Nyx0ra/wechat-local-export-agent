import datetime as dt
import hashlib
import json,pathlib,re,zstandard
from dataclasses import dataclass
KIT=pathlib.Path(__file__).resolve().parents[1]

@dataclass(frozen=True)
class TimeWindow:
    start: int | None = None
    end: int | None = None

    @classmethod
    def from_config(cls, options):
        value = options.get('time_range')
        if value is None:
            return cls()
        if not isinstance(value, dict) or set(value) - {'start', 'end'}:
            raise ValueError('time_range accepts only start and end')
        def parse(text):
            if text is None:
                return None
            if not isinstance(text, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z|[+-]\d{2}:\d{2})', text):
                raise ValueError('Use whole-second ISO 8601 with explicit UTC offset')
            stamp = dt.datetime.fromisoformat(text.replace('Z', '+00:00'))
            return int(stamp.timestamp())
        start, end = parse(value.get('start')), parse(value.get('end'))
        if start is not None and end is not None and start >= end:
            raise ValueError('start must precede exclusive end')
        return cls(start, end)

    @property
    def bounded(self):
        return self.start is not None or self.end is not None

    def contains(self, epoch):
        return (self.start is None or epoch >= self.start) and (self.end is None or epoch < self.end)

    def sql(self):
        clauses, values = [], []
        for bound, op in ((self.start, '>='), (self.end, '<')):
            if bound is not None:
                clauses.append('CreateTime ' + op + ' ?')
                values.append(bound)
        return (' WHERE ' + ' AND '.join(clauses) if clauses else ''), values

    def describe(self):
        def stamp(value):
            return dt.datetime.fromtimestamp(value, dt.timezone.utc).isoformat() if value is not None else None
        return {'start_inclusive': stamp(self.start), 'end_exclusive': stamp(self.end)}


def media_message_id(relative, target_hash):
    parts = relative.replace('\\', '/').split('/')
    if target_hash not in parts:
        return None
    position = parts.index(target_hash)
    if position + 1 >= len(parts):
        return None
    match = re.fullmatch(r'(\d+)(?:[._].*)?', parts[position + 1])
    return int(match[1]) if match else None


def display_timezone(options):
    value = options.get('display_timezone', '+08:00')
    if not isinstance(value, str) or not re.fullmatch(r'[+-](?:0\d|1[0-3]):[0-5]\d|[+-]14:00', value):
        raise ValueError('display_timezone must be a fixed offset, for example +08:00')
    sign = -1 if value[0] == '-' else 1
    return dt.timezone(sign * dt.timedelta(hours=int(value[1:3]), minutes=int(value[4:])))
def config(task):
    p=pathlib.Path(task)/'case-config.json'
    c=json.loads(p.read_text(encoding='utf-8-sig'))
    if not c.get('backup_dir'): raise ValueError('An explicit backup_dir is required; no first-backup selection')
    return c
def backup_for(task): return pathlib.Path(config(task)['backup_dir']).resolve()
def exporter_for(task):
    value=config(task).get('exporter_executable')
    if not value or not pathlib.Path(value).is_file():
        raise ValueError('Explicit external upstream executable required')
    executable = pathlib.Path(value).resolve()
    lock = json.loads((KIT / 'tools/upstream-lock.json').read_text(encoding='utf-8'))
    with executable.open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    if digest != lock['executable_sha256']:
        raise ValueError('Upstream executable hash does not match pinned version')
    return executable
def decode_body(value,flag,c):
    if isinstance(value,str): return value,None
    if not isinstance(value,bytes) or not value.startswith(bytes.fromhex('28b52ffd')) or flag!=2:
        raise ValueError('Unsupported message encoding; refusing to guess')
    did=zstandard.get_frame_parameters(value).dict_id
    path=c.get('zstd_dictionaries',{}).get(str(did))
    if not path: return None,did
    d=zstandard.ZstdCompressionDict(pathlib.Path(path).read_bytes())
    if d.dict_id()!=did: raise ValueError('Dictionary ID does not match compressed frame')
    out=zstandard.ZstdDecompressor(dict_data=d).decompress(value,max_output_size=128*1024*1024,allow_extra_data=False)
    return out.decode('utf-8','strict'),did
