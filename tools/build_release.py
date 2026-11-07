"""Build a source-only ZIP after privacy checks. No Git operation or upload."""
import argparse
import hashlib
import json
import pathlib
import zipfile
from privacy_check import scan, source_files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=pathlib.Path)
    parser.add_argument('--deny-file', type=pathlib.Path)
    args = parser.parse_args()
    root = pathlib.Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if output.is_relative_to(root) or output.exists():
        raise ValueError('Release path must be a new ZIP outside source tree')
    terms = json.loads(args.deny_file.read_text(encoding='utf-8-sig')) if args.deny_file else []
    findings = scan(root, terms)
    if findings:
        raise ValueError('Privacy check failed; run privacy_check.py for rule names')
    output.parent.mkdir(parents=True, exist_ok=True)
    files = source_files(root)
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in files:
            bundle.write(path, 'wechat-local-export-agent/' + path.relative_to(root).as_posix())
    with output.open('rb') as handle:
        sha = hashlib.file_digest(handle, 'sha256').hexdigest()
    print(json.dumps({'source_files': len(files), 'bytes': output.stat().st_size, 'sha256': sha, 'uploaded': False}))


if __name__ == '__main__':
    main()
