"""Configuration loading and validation for migration-lint."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomllib


SEVERITY_LEVELS = ('info', 'warning', 'error', 'critical')
SEVERITIES = SEVERITY_LEVELS
OUTPUT_FORMATS = ('text', 'json', 'sarif')
ORDERING_STRATEGIES = ('path', 'version', 'modified')
FAIL_ON_LEVELS = ('none', 'info', 'warning', 'error', 'critical')

_SEVERITY_RANK = {
    'info': 10,
    'warning': 20,
    'error': 30,
    'critical': 40,
}


class ConfigError(ValueError):
    """Raised when configuration is invalid or cannot be loaded."""


@dataclass(slots=True)
class RuleConfig:
    """Configuration for a single lint rule."""

    enabled: bool = True
    severity: str = 'warning'
    options: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.severity not in _SEVERITY_RANK:
            raise ConfigError(f'unknown severity {self.severity!r} for rule')
        if not isinstance(self.enabled, bool):
            raise ConfigError('rule "enabled" must be a boolean')
        if not isinstance(self.options, dict):
            raise ConfigError('rule "options" must be a mapping')


@dataclass(slots=True)
class Config:
    """Resolved migration-lint configuration."""

    root: Path
    include: list[str]
    exclude: list[str]
    extensions: list[str]
    ordering: str
    baseline: Path | None
    output_format: str
    fail_on: str
    plugins: list[str]
    rules: dict[str, RuleConfig]
    config_path: Path | None = None

    def validate(self) -> None:
        if not self.root.is_dir():
            raise ConfigError(f'configuration root does not exist: {self.root}')
        if self.output_format not in OUTPUT_FORMATS:
            raise ConfigError(f'unsupported output format: {self.output_format}')
        if self.fail_on not in FAIL_ON_LEVELS:
            raise ConfigError(f'unsupported fail-on level: {self.fail_on}')
        if self.ordering not in ORDERING_STRATEGIES:
            raise ConfigError(f'unsupported ordering strategy: {self.ordering}')
        for name, values in (
            ('include', self.include),
            ('exclude', self.exclude),
            ('extensions', self.extensions),
            ('plugins', self.plugins),
        ):
            if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
                raise ConfigError(f'{name} must be a list of strings')
        for rule in self.rules.values():
            rule.validate()

    def to_dict(self) -> dict[str, Any]:
        return {
            'root': str(self.root),
            'config_path': str(self.config_path) if self.config_path is not None else None,
            'include': list(self.include),
            'exclude': list(self.exclude),
            'extensions': list(self.extensions),
            'ordering': self.ordering,
            'baseline': str(self.baseline) if self.baseline is not None else None,
            'output_format': self.output_format,
            'fail_on': self.fail_on,
            'plugins': list(self.plugins),
            'rules': {
                name: {
                    'enabled': rule.enabled,
                    'severity': rule.severity,
                    'options': dict(rule.options),
                }
                for name, rule in self.rules.items()
            },
        }

    def apply_overrides(self, overrides: Mapping[str, Any]) -> None:
        if not isinstance(overrides, Mapping):
            raise ConfigError('overrides must be a mapping')

        if overrides.get('root') is not None:
            self.root = Path(str(overrides['root'])).resolve()
        if overrides.get('config_path') is not None:
            self.config_path = Path(str(overrides['config_path']))
            if not self.config_path.is_absolute():
                self.config_path = (self.root / self.config_path).resolve()
        if overrides.get('include') is not None:
            self.include = _as_string_list(overrides['include'], 'include')
        if overrides.get('exclude') is not None:
            self.exclude = _as_string_list(overrides['exclude'], 'exclude')
        if overrides.get('extensions') is not None:
            self.extensions = _as_string_list(overrides['extensions'], 'extensions')
        if overrides.get('ordering') is not None:
            self.ordering = str(overrides['ordering'])
        if overrides.get('baseline') is not None:
            baseline = Path(str(overrides['baseline']))
            self.baseline = baseline if baseline.is_absolute() else (self.root / baseline).resolve()
        if overrides.get('output_format') is not None:
            self.output_format = str(overrides['output_format'])
        if overrides.get('fail_on') is not None:
            self.fail_on = str(overrides['fail_on'])
        if overrides.get('plugins') is not None:
            self.plugins = _as_string_list(overrides['plugins'], 'plugins')

        if overrides.get('rules') is not None:
            rules = overrides['rules']
            if not isinstance(rules, Mapping):
                raise ConfigError('rules override must be a mapping')
            for name, raw in rules.items():
                if not isinstance(raw, Mapping):
                    raise ConfigError(f'rule override for {name!r} must be a mapping')
                rule = self.rules.get(str(name), RuleConfig())
                if 'enabled' in raw:
                    rule.enabled = bool(raw['enabled'])
                if 'severity' in raw:
                    rule.severity = str(raw['severity'])
                options = dict(rule.options)
                if isinstance(raw.get('options'), Mapping):
                    options.update(raw['options'])
                for key, value in raw.items():
                    if key not in ('enabled', 'severity', 'options'):
                        options[key] = value
                rule.options = options
                rule.validate()
                self.rules[str(name)] = rule

        if overrides.get('severity_overrides') is not None:
            severity_overrides = overrides['severity_overrides']
            if not isinstance(severity_overrides, Mapping):
                raise ConfigError('severity_overrides must be a mapping')
            for name, severity in severity_overrides.items():
                rule = self.rules.get(str(name), RuleConfig())
                rule.severity = str(severity)
                rule.validate()
                self.rules[str(name)] = rule

        self.validate()


def _as_string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        if all(isinstance(item, str) for item in value):
            return list(value)
    raise ConfigError(f'{field_name} must be a string or list of strings')


def _deep_merge(base: dict[str, Any], update: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in update.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = _deep_merge(dict(result[key]), value)
        else:
            result[key] = value
    return result


def _extract_pyproject(path: Path) -> dict[str, Any]:
    with path.open('rb') as handle:
        parsed = tomllib.load(handle)
    if not isinstance(parsed, Mapping):
        raise ConfigError(f'invalid TOML in {path}')
    tool_section = parsed.get('tool', {})
    if tool_section is None:
        tool_section = {}
    if not isinstance(tool_section, Mapping):
        raise ConfigError(f'invalid [tool] table in {path}')
    section = tool_section.get('migration-lint', {})
    if section is None:
        section = {}
    if not isinstance(section, Mapping):
        raise ConfigError(f'invalid [tool.migration-lint] table in {path}')
    if not section and isinstance(parsed.get('migration-lint'), Mapping):
        section = parsed['migration-lint']
    return dict(section)


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open('rb') as handle:
        parsed = tomllib.load(handle)
    if not isinstance(parsed, Mapping):
        raise ConfigError(f'invalid TOML in {path}')
    return dict(parsed)


def _load_config_file(path: Path, root: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f'configuration file not found: {path}')
    if path.name == 'pyproject.toml':
        return _extract_pyproject(path)
    return _load_toml(path)


def _build_config(root: Path, config_path: Path | None, data: Mapping[str, Any]) -> Config:
    defaults: dict[str, Any] = {
        'include': ['**/*.sql'],
        'exclude': [],
        'extensions': ['.sql'],
        'ordering': 'path',
        'baseline': None,
        'output_format': 'text',
        'fail_on': 'error',
        'plugins': [],
        'rules': {},
        'severity_overrides': {},
    }
    merged = _deep_merge(defaults, dict(data))

    rules_raw = merged.pop('rules', {})
    severity_overrides = merged.pop('severity_overrides', {})
    if not isinstance(rules_raw, Mapping):
        raise ConfigError('rules must be a mapping')
    if not isinstance(severity_overrides, Mapping):
        raise ConfigError('severity_overrides must be a mapping')

    rule_configs: dict[str, RuleConfig] = {}
    for name, raw in rules_raw.items():
        if not isinstance(raw, Mapping):
            raise ConfigError(f'rule {name!r} must be a mapping')
        known = {'enabled', 'severity', 'options'}
        options = dict(raw.get('options', {})) if isinstance(raw.get('options'), Mapping) else {}
        for key, value in raw.items():
            if key not in known:
                options[key] = value
        rule = RuleConfig(
            enabled=bool(raw.get('enabled', True)),
            severity=str(raw.get('severity', 'warning')),
            options=options,
        )
        rule.validate()
        rule_configs[str(name)] = rule

    for name, severity in severity_overrides.items():
        rule = rule_configs.get(str(name), RuleConfig())
        rule.severity = str(severity)
        rule.validate()
        rule_configs[str(name)] = rule

    baseline_raw = merged.get('baseline')
    baseline = None
    if baseline_raw is not None:
        baseline_path = Path(str(baseline_raw))
        baseline = baseline_path if baseline_path.is_absolute() else (root / baseline_path).resolve()

    config = Config(
        root=root,
        include=_as_string_list(merged.get('include'), 'include'),
        exclude=_as_string_list(merged.get('exclude'), 'exclude'),
        extensions=_as_string_list(merged.get('extensions'), 'extensions'),
        ordering=str(merged.get('ordering', 'path')),
        baseline=baseline,
        output_format=str(merged.get('output_format', 'text')),
        fail_on=str(merged.get('fail_on', 'error')),
        plugins=_as_string_list(merged.get('plugins'), 'plugins'),
        rules=rule_configs,
        config_path=config_path,
    )
    return config


def load_config(
    root: str | Path | None = None,
    config_path: str | Path | None = None,
    overrides: Mapping[str, Any] | None = None,
    *,
    discovery: bool = True,
) -> Config:
    """Load configuration from disk and apply optional overrides."""
    root_path = Path(root if root is not None else '.').resolve()

    selected_path: Path | None = None
    data: dict[str, Any] = {}

    if config_path is not None:
        selected_path = Path(config_path)
        if not selected_path.is_absolute():
            selected_path = root_path / selected_path
        data = _load_config_file(selected_path, root_path)
    elif discovery:
        pyproject = root_path / 'pyproject.toml'
        if pyproject.is_file():
            data = _deep_merge(data, _extract_pyproject(pyproject))
        standalone = root_path / '.migration-lint.toml'
        if standalone.is_file():
            data = _deep_merge(data, _load_toml(standalone))

    if overrides:
        data = _deep_merge(data, dict(overrides))

    config = _build_config(root_path, selected_path, data)
    config.validate()
    return config
