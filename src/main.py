"""Command-line interface for migration-lint."""
from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path
from typing import Any

from migration_lint import __version__
from migration_lint.config import (
    Config,
    ConfigError,
    FAIL_ON_LEVELS,
    OUTPUT_FORMATS,
    load_config,
)


def _as_relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def discover_migration_files(config: Config) -> list[Path]:
    if not config.root.is_dir():
        return []
    found: set[Path] = set()
    extensions = {ext.lower() for ext in config.extensions} or {'.sql'}
    for pattern in config.include:
        for candidate in config.root.glob(pattern):
            if not candidate.is_file():
                continue
            if candidate.suffix.lower() not in extensions:
                continue
            relative = candidate.relative_to(config.root).as_posix()
            if any(fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(candidate.name, pattern) for pattern in config.exclude):
                continue
            found.add(candidate.resolve())
    return sorted(found, key=lambda item: _as_relative(item, config.root))


def _write_text_report(files: list[Path], root: Path) -> None:
    print(f'migration-lint: scanned {len(files)} migration file(s)')
    for path in files:
        print(f'  - {_as_relative(path, root)}')
    if not files:
        print('  (no migration files found)')
    print('No findings.')


def _write_json_report(files: list[Path], root: Path) -> None:
    payload = {
        'version': __version__,
        'root': str(root),
        'files': [_as_relative(path, root) for path in files],
        'findings': [],
        'summary': {
            'files': len(files),
            'findings': 0,
        },
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


def _write_sarif_report(files: list[Path], root: Path) -> None:
    payload = {
        '$schema': 'https://json.schemastore.org/sarif-2.1.0.json',
        'version': '2.1.0',
        'runs': [
            {
                'tool': {
                    'driver': {
                        'name': 'migration-lint',
                        'version': __version__,
                        'informationUri': 'https://example.invalid/migration-lint',
                    }
                },
                'artifacts': [
                    {'location': {'uri': _as_relative(path, root)}} for path in files
                ],
                'results': [],
            }
        ],
    }
    print(json.dumps(payload, indent=2))


def _overrides_from_args(args: argparse.Namespace) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    if getattr(args, 'include', None):
        overrides['include'] = args.include
    if getattr(args, 'exclude', None):
        overrides['exclude'] = args.exclude
    if getattr(args, 'output_format', None) is not None:
        overrides['output_format'] = args.output_format
    if getattr(args, 'fail_on', None) is not None:
        overrides['fail_on'] = args.fail_on
    if getattr(args, 'baseline', None) is not None:
        overrides['baseline'] = args.baseline
    return overrides


def _audit(args: argparse.Namespace) -> int:
    root = Path(getattr(args, 'root', '.'))
    try:
        config = load_config(root=root, config_path=getattr(args, 'config', None), overrides=_overrides_from_args(args))
    except ConfigError as exc:
        print(f'migration-lint: {exc}', file=sys.stderr)
        return 2

    files = discover_migration_files(config)
    output_format = config.output_format
    if output_format == 'json':
        _write_json_report(files, config.root)
    elif output_format == 'sarif':
        _write_sarif_report(files, config.root)
    else:
        _write_text_report(files, config.root)

    return 0


def _init(args: argparse.Namespace) -> int:
    root = Path(getattr(args, 'root', '.')).resolve()
    if not root.is_dir():
        print(f'migration-lint: root does not exist: {root}', file=sys.stderr)
        return 2
    target = root / '.migration-lint.toml'
    if target.exists() and not getattr(args, 'force', False):
        print(f'migration-lint: configuration already exists: {target}', file=sys.stderr)
        return 1
    content = '''# migration-lint configuration
include = ['**/*.sql']
exclude = []
extensions = ['.sql']
ordering = 'path'
output_format = 'text'
fail_on = 'error'
plugins = []

[rules.example]
severity = 'warning'
enabled = true
'''
    target.write_text(content, encoding='utf-8')
    print(f'Created {target}')
    return 0


def _rules(args: argparse.Namespace) -> int:
    root = Path(getattr(args, 'root', '.'))
    try:
        config = load_config(root=root, config_path=getattr(args, 'config', None))
    except ConfigError as exc:
        print(f'migration-lint: {exc}', file=sys.stderr)
        return 2
    if not config.rules:
        print('No rules configured.')
        return 0
    for name in sorted(config.rules):
        rule = config.rules[name]
        print(f'{name}: severity={rule.severity}, enabled={str(rule.enabled).lower()}')
    return 0


def _version(args: argparse.Namespace) -> int:
    print(f'migration-lint {__version__}')
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='migration-lint', description='Audit SQL migration files for unsafe changes.')
    subparsers = parser.add_subparsers(dest='command')

    audit = subparsers.add_parser('audit', help='Audit migration files in a project.')
    audit.add_argument('--root', '-r', default='.', help='Project root to audit.')
    audit.add_argument('--config', '-c', help='Path to a configuration file.')
    audit.add_argument('--include', action='append', help='Glob pattern to include. May be repeated.')
    audit.add_argument('--exclude', action='append', help='Glob pattern to exclude. May be repeated.')
    audit.add_argument('--format', dest='output_format', choices=OUTPUT_FORMATS, help='Report format.')
    audit.add_argument('--fail-on', dest='fail_on', choices=FAIL_ON_LEVELS, help='Severity threshold for failure.')
    audit.add_argument('--baseline', help='Baseline file used to suppress known findings.')

    init = subparsers.add_parser('init', help='Create a default configuration file.')
    init.add_argument('--root', '-r', default='.', help='Project root.')
    init.add_argument('--force', action='store_true', help='Overwrite an existing configuration file.')

    rules = subparsers.add_parser('rules', help='List configured rules.')
    rules.add_argument('--root', '-r', default='.', help='Project root.')
    rules.add_argument('--config', '-c', help='Path to a configuration file.')

    subparsers.add_parser('version', help='Print the version and exit.')

    return parser


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    argv = list(argv)
    if argv and str(argv[0]).startswith('-'):
        argv = ['audit'] + argv

    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        return 0 if code is None else int(code)

    command = getattr(args, 'command', None)
    if command is None:
        args.command = 'audit'
        command = 'audit'

    handlers = {
        'audit': _audit,
        'init': _init,
        'rules': _rules,
        'version': _version,
    }
    handler = handlers.get(command)
    if handler is None:
        parser.print_help(sys.stderr)
        return 2
    try:
        return int(handler(args))
    except (OSError, ValueError) as exc:
        print(f'migration-lint: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
