"""Up/down migration reversal checks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

from .discovery import MigrationFile, MigrationPair, pair_migrations
from .rules import Finding

_IRREVERSIBLE_RE = re.compile(
    r'--\s*(?:migration-lint:\s*)?irreversible\b', re.IGNORECASE
)


def has_irreversibility_marker(text: str) -> bool:
    """Return True if ``text`` declares the migration irreversible."""
    return bool(_IRREVERSIBLE_RE.search(text))


def _default_reader(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8')
    except OSError:
        return ''


def check_reversals(
    pairs: Sequence[MigrationPair],
    content_provider: Callable[[Path], str] | None = None,
) -> list[Finding]:
    """Detect up migrations without matching down migrations.

    Honors irreversibility declarations in the up migration file.
    """
    reader = content_provider or _default_reader
    findings: list[Finding] = []
    for pair in pairs:
        if not pair.has_up:
            if pair.has_down:
                findings.append(Finding(
                    rule_id='orphan-down-migration',
                    severity='warning',
                    message=f'Down migration without matching up: {pair.down.name if pair.down else pair.key}',
                    file=str(pair.down.path) if pair.down else pair.key,
                    line=1,
                    column=1,
                ))
            continue
        if pair.has_down:
            continue
        text = reader(pair.up.path)
        if has_irreversibility_marker(text):
            continue
        findings.append(Finding(
            rule_id='missing-down-migration',
            severity='error',
            message=f'Up migration {pair.up.name} has no matching down migration',
            file=str(pair.up.path),
            line=1,
            column=1,
        ))
    return findings


def match_pairs(files: Iterable[MigrationFile]) -> list[MigrationPair]:
    """Convenience wrapper around discovery.pair_migrations."""
    return pair_migrations(files)
