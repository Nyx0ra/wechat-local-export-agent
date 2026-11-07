"""Download a pinned public upstream archive; never accept or transmit chat data."""
import argparse
import hashlib
import json
import pathlib
import shutil
import stat
import tempfile
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]


def digest(path):
    with pathlib.Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def install_archive(archive, destination, expected_sha256, expected_exe_sha256):
    destination = pathlib.Path(destination).resolve()
    if destination.exists():
        raise ValueError('Destination must not already exist')
    if destination.is_relative_to(ROOT) or ROOT.is_relative_to(destination):
        raise ValueError('Upstream runtime must be outside the source project')
    if digest(archive).lower() != expected_sha256.lower():
        raise ValueError('Archive checksum mismatch')
    with tempfile.TemporaryDirectory(prefix='wx-upstream-unpack-') as temporary:
        unpacked = pathlib.Path(temporary) / 'unpacked'
        unpacked.mkdir()
        with zipfile.ZipFile(archive) as bundle:
            members = bundle.infolist()
            if len(members) > 2000 or sum(item.file_size for item in members) > 256 * 1024 * 1024:
                raise ValueError('Archive exceeds expected limits')
            for item in members:
                name = pathlib.PurePosixPath(item.filename.replace('\\', '/'))
                if name.is_absolute() or '..' in name.parts or ':' in str(name) or stat.S_ISLNK(item.external_attr >> 16):
                    raise ValueError('Unsafe archive member')
            bundle.extractall(unpacked)
        matches = list(unpacked.rglob('WechatExporterCmd.exe'))
        if len(matches) != 1 or digest(matches[0]).lower() != expected_exe_sha256.lower():
            raise ValueError('Unexpected upstream executable')
        shutil.copytree(matches[0].parent, destination)
    return destination / 'WechatExporterCmd.exe'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', required=True, type=pathlib.Path)
    parser.add_argument('--archive', type=pathlib.Path, help='Use an already-downloaded original archive')
    args = parser.parse_args()
    lock = json.loads((ROOT / 'tools/upstream-lock.json').read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(prefix='wx-upstream-download-') as temporary:
        archive = args.archive or pathlib.Path(temporary) / 'upstream.zip'
        if args.archive is None:
            request = urllib.request.Request(lock['archive_url'], headers={'User-Agent': 'wechat-local-export-agent-bootstrap'})
            with urllib.request.urlopen(request, timeout=60) as response, archive.open('wb') as output:
                shutil.copyfileobj(response, output)
        executable = install_archive(archive, args.destination, lock['archive_sha256'], lock['executable_sha256'])
    print(json.dumps({'version': lock['version'], 'sha256_verified': True, 'executable': str(executable)}))


if __name__ == '__main__':
    main()
