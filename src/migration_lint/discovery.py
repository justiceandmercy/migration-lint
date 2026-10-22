"""Discovery of migration files.

This module locates migration files on disk using configurable glob patterns,
sorts them deterministically, and pairs ``up``/``down`` migrations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

_DEFAULT_PATTERNS: tuple[str, ...] = ('*.sql', '*.up.sql', '*.down.sql')

_VERSION_RE = re.compile(r'(?:^|[_\-./])(?:v|V)?(\d+)(?:[_\-./]|$)')


@dataclass(frozen=True)
class MigrationFile:
    """A single migration file discovered on disk."""

    path: Path
    name: str
    version: str | None
    direction: str  # 'up', 'down', or 'neutral'
    base_key: str

    @property
    def is_up(self) -> bool:
        return self.direction == 'up'

    @property
    def is_down(self) -> bool:
        return self.direction == 'down'


def _direction_for(path: Path) -> str:
    name = path.name.lower()
    if name.endswith('.up.sql') or name.endswith('_up.sql'):
        return 'up'
    if name.endswith('.down.sql') or name.endswith('_down.sql'):
        return 'down'
    return 'neutral'


def _base_key_for(path: Path) -> str:
    name = path.name
    lower = name.lower()
    for suffix in ('.up.sql', '.down.sql', '_up.sql', '_down.sql'):
        if lower.endswith(suffix):
            return name[: -len(suffix)]
    return path.stem


def _version_for(path: Path) -> str | None:
    match = _VERSION_RE.search(path.name)
    if not match:
        return None
    return match.group(1)


def _version_key(version: str | None) -> tuple[int, ...]:
    if version is None:
        return (10**9,)
    return (0, int(version))


def discover_files(
    root: Path | str,
    patterns: Sequence[str] | None = None,
    recursive: bool = True,
) -> list[MigrationFile]:
    """Discover migration files under ``root`` matching ``patterns``.

    Files are sorted deterministically by version then filename.
    """
    root = Path(root)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f'Migration root does not exist: {root}')
    patterns = list(patterns) if patterns else list(_DEFAULT_PATTERNS)

    found: dict[Path, MigrationFile] = {}
    for pattern in patterns:
        iterator = root.rglob(pattern) if recursive else root.glob(pattern)
        for path in iterator:
            if not path.is_file():
                continue
            resolved = path.resolve()
            if resolved in found:
                continue
            found[resolved] = MigrationFile(
                path=path,
                name=path.name,
                version=_version_for(path),
                direction=_direction_for(path),
                base_key=_base_key_for(path),
            )

    return sorted(found.values(), key=lambda f: (_version_key(f.version), f.name))


@dataclass
class MigrationPair:
    """A matched up/down migration pair."""

    key: str
    up: MigrationFile | None = None
    down: MigrationFile | None = None
    irreversibility_marker: str | None = None

    @property
    def has_up(self) -> bool:
        return self.up is not None

    @property
    def has_down(self) -> bool:
        return self.down is not None


def pair_migrations(files: Iterable[MigrationFile]) -> list[MigrationPair]:
    """Pair up and down migrations by their base key."""
    by_key: dict[str, MigrationPair] = {}
    for f in files:
        pair = by_key.setdefault(f.base_key, MigrationPair(key=f.base_key))
        if f.is_up:
            pair.up = f
        elif f.is_down:
            pair.down = f
        else:
            if pair.up is None:
                pair.up = f
    return sorted(
        by_key.values(),
        key=lambda p: (_version_key(p.up.version if p.up else None), p.key),
    )
