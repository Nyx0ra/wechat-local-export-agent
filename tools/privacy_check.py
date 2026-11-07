"""Conservative source-release checks; findings never echo matched private values."""
import argparse
import json
import pathlib
import re

TOP_FILES = {'README.md', 'AGENTS.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'SECURITY.md',
             'CHANGELOG.md', 'requirements.txt', 'wxlocal.py', '.gitignore', '.gitattributes'}
TOP_DIRS = {'scripts', 'tests', 'tools', 'docs', 'examples', '.github'}
SUFFIXES = {'.py', '.md', '.txt', '.json', '.yml', '.yaml', '.ps1'}
RUNTIME_NAMES = {'case-config.json', 'target-identification.json', 'target-view-state.json',
                 'media-index.json', 'export-report.txt', 'target-records.jsonl'}


def source_files(root):
    root = pathlib.Path(root).resolve()
    result = []
    def visit(folder):
        for path in sorted(folder.iterdir()):
            if path.name in ('.git', '__pycache__') or path.suffix == '.pyc':
                continue
            if path.is_symlink():
                result.append(path)
            elif path.is_dir():
                visit(path)
            else:
                result.append(path)
    visit(root)
    return result


def scan(root, denied_terms=()):
    root = pathlib.Path(root).resolve()
    findings = []
    for path in source_files(root):
        rel = path.relative_to(root)
        name = rel.as_posix()
        def record(rule):
            findings.append({'file': name, 'rule': rule})
        if path.is_symlink():
            record('symbolic-link'); continue
        if rel.parts[0] not in TOP_DIRS and name not in TOP_FILES:
            record('unexpected-release-path')
        if path.name in RUNTIME_NAMES:
            record('runtime-data-file')
        if path.suffix not in SUFFIXES and name not in TOP_FILES:
            record('binary-or-unexpected-extension'); continue
        if path.stat().st_size > 1024 * 1024:
            record('oversized-source-file'); continue
        try:
            text = path.read_text(encoding='utf-8-sig')
        except UnicodeError:
            record('non-utf8-file'); continue
        if re.search(r'(?i)[a-z]:[\\/]+Users[\\/]+[^\\/\s"<>]+', text):
            record('absolute-user-profile-path')
        if re.search(r'(?i)[a-z]:[\\/]+WeChatLocalExport[\\/]+\d{8}-\d{6}', text):
            record('real-case-path')
        if re.search('-----BEGIN ' + r'(?:RSA |EC |OPENSSH )?PRIVATE KEY-----', text):
            record('private-key')
        if any(term and term.casefold() in text.casefold() for term in denied_terms):
            record('private-deny-term')
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=pathlib.Path, default=pathlib.Path(__file__).resolve().parents[1])
    parser.add_argument('--deny-file', type=pathlib.Path, help='External JSON list of private strings; never put in repository')
    args = parser.parse_args()
    terms = json.loads(args.deny_file.read_text(encoding='utf-8-sig')) if args.deny_file else []
    findings = scan(args.root, terms)
    print(json.dumps({'passed': not findings, 'source_files': len(source_files(args.root)), 'findings': findings}, ensure_ascii=True))
    return bool(findings)


if __name__ == '__main__':
    raise SystemExit(main())
