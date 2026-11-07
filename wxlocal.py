"""Local-only, explicit-target chat export stage runner."""
import argparse
import json
import pathlib
import subprocess
import sys
from scripts.common import KIT, TimeWindow, display_timezone

STAGES = {
    'identify': 'identify_target.py',
    'inventory': 'inventory_target.py',
    'prepare': 'prepare_target_view.py',
    'official': 'run_official_exports.py',
    'media': 'collect_and_verify_media.py',
    'render': 'render_readable_export.py',
    'verify': 'verify_export.py',
}
PREREQUISITES = {'inventory': 'identify', 'prepare': 'inventory', 'official': 'prepare',
                 'media': 'prepare', 'render': 'media', 'verify': 'render'}


def load_options(path):
    options = json.loads(path.read_text(encoding='utf-8-sig'))
    allowed = {'case_dir', 'backup_dir', 'target', 'account_hash', 'exporter_executable',
               'zstd_dictionaries', 'time_range', 'display_timezone', 'conversion'}
    if set(options) - allowed:
        raise ValueError('Unknown configuration field')
    def resolve(value):
        p = pathlib.Path(value)
        return str((path.parent / p).resolve())
    for key in ('case_dir', 'backup_dir'):
        options[key] = resolve(options[key])
    options.setdefault('conversion', 'disabled')
    options.setdefault('display_timezone', '+08:00')
    options.setdefault('account_hash', None)
    options.setdefault('exporter_executable', None)
    options.setdefault('zstd_dictionaries', {})
    if options['conversion'] not in ('disabled', 'upstream'):
        raise ValueError('conversion must be disabled or upstream')
    if options['exporter_executable']:
        options['exporter_executable'] = resolve(options['exporter_executable'])
    if options['conversion'] == 'upstream' and not options['exporter_executable']:
        raise ValueError('Explicit external exporter_executable required for conversion')
    options['zstd_dictionaries'] = {str(k): resolve(v) for k, v in options['zstd_dictionaries'].items()}
    target = options.get('target')
    if not isinstance(target, dict) or set(target) - {'remark', 'nickname', 'wechat_id'}:
        raise ValueError('target accepts remark, nickname, wechat_id')
    if not any(target.values()) or any(not isinstance(v, str) for v in target.values()):
        raise ValueError('Provide at least one nonempty target identity string')
    TimeWindow.from_config(options)
    display_timezone(options)
    case, backup = pathlib.Path(options['case_dir']), pathlib.Path(options['backup_dir'])
    if case == backup or case.is_relative_to(backup) or backup.is_relative_to(case):
        raise ValueError('Backup and case paths must not overlap')
    if case.is_relative_to(KIT) or KIT.is_relative_to(case):
        raise ValueError('Runtime case_dir must be outside source project')
    if not (backup / 'Manifest.db').is_file():
        raise ValueError('Explicit backup_dir must contain Manifest.db')
    return options


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=pathlib.Path)
    parser.add_argument('stage', choices=[*STAGES, 'run'])
    args = parser.parse_args()
    options = load_options(args.config.resolve())
    case = pathlib.Path(options['case_dir'])
    frozen = case / 'case-config.json'
    if frozen.exists():
        if json.loads(frozen.read_text(encoding='utf-8')) != options:
            raise ValueError('Configuration changed; use a fresh case_dir')
    elif args.stage not in ('identify', 'run'):
        raise ValueError('Run identify first')
    elif case.exists() and any(case.iterdir()):
        raise ValueError('First identify requires an empty case_dir')
    for folder in ('work', 'exports/html', 'exports/txt'):
        (case / folder).mkdir(parents=True, exist_ok=True)
    if not frozen.exists():
        frozen.write_text(json.dumps(options, ensure_ascii=False, indent=2), encoding='utf-8')
    stages = list(STAGES) if args.stage == 'run' else [args.stage]
    for stage in stages:
        if stage == 'official' and options['conversion'] == 'disabled':
            print(json.dumps({'stage': stage, 'status': 'skipped', 'reason': 'conversion disabled'}))
            continue
        prerequisite = PREREQUISITES.get(stage)
        if prerequisite and not (case / 'work' / (prerequisite + '.completed')).exists():
            raise ValueError('Required prior stage has not completed')
        if stage == 'media' and options['conversion'] == 'upstream' and not (case / 'work/official.completed').exists():
            raise ValueError('Upstream conversion has not completed')
        success_marker = case / 'work' / (stage + '.completed')
        if success_marker.exists() and stage != 'verify':
            raise ValueError('Stage already completed; use next stage or a fresh case_dir')
        logpath = case / 'work' / ('stage-' + stage + '.log')
        command = [sys.executable, str(KIT / 'scripts' / STAGES[stage])]
        command += [options['backup_dir'], str(case / 'work/target-identification.json'), str(frozen)] if stage == 'identify' else [str(case)]
        with logpath.open('wb') as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            print(json.dumps({'stage': stage, 'exit': result.returncode, 'status': 'failed', 'detail': 'Inspect local stage log; do not upload its contents'}))
            return result.returncode
        if stage == 'identify':
            identity = json.loads((case / 'work/target-identification.json').read_text(encoding='utf-8'))
            matches = identity['matches']
            if len(identity['accounts']) != 1 or len(matches) != 1 or identity['errors'] or not all(matches[0][key] for key in ('remark_match', 'nickname_match', 'wechat_id_match')):
                raise ValueError('Identity ambiguous, inconsistent or unreadable; review local metadata and use a fresh case')
            if matches[0]['username'].endswith('@chatroom'):
                raise ValueError('Group chats are not supported in this version')
        success_marker.write_text('ok\n', encoding='utf-8')
        print(json.dumps({'stage': stage, 'exit': 0, 'status': 'passed'}))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(json.dumps({'status': 'failed', 'error_type': type(error).__name__,
                          'reason': str(error) if isinstance(error, ValueError) else 'Invalid configuration or local I/O; check paths locally'}))
        sys.exit(2)
