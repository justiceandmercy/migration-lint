"""Rule engine and built-in migration checks."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable, Sequence

from .parser import Operation


@dataclass
class Finding:
    """A single lint finding."""

    rule_id: str
    severity: str
    message: str
    file: str
    line: int
    column: int = 1


@dataclass
class RuleContext:
    """Context passed to a rule."""

    operations: list[Operation]
    file: str
    config: dict[str, Any] = field(default_factory=dict)
    all_files: list[str] = field(default_factory=list)
    all_operations: dict[str, list[Operation]] = field(default_factory=dict)
    pairs: list[Any] = field(default_factory=list)


class Rule:
    """Base class for a lint rule."""

    id: str = 'RULE'
    default_severity: str = 'warning'
    description: str = ''

    def enabled(self, context: RuleContext) -> bool:
        return True

    def check(self, context: RuleContext) -> list[Finding]:
        return []


class DropTableRule(Rule):
    id = 'destructive-drop-table'
    default_severity = 'error'

    def check(self, context: RuleContext) -> list[Finding]:
        out: list[Finding] = []
        for op in context.operations:
            if op.kind == 'DROP_TABLE':
                out.append(Finding(
                    rule_id=self.id,
                    severity=self.default_severity,
                    message=f'DROP TABLE on {op.table or "<unknown>"} is destructive',
                    file=context.file,
                    line=op.location.line,
                    column=op.location.column,
                ))
        return out


class DropColumnRule(Rule):
    id = 'destructive-drop-column'
    default_severity = 'error'

    def check(self, context: RuleContext) -> list[Finding]:
        out: list[Finding] = []
        for op in context.operations:
            if op.kind == 'DROP_COLUMN':
                cols = ', '.join(op.columns) if op.columns else '<unknown>'
                out.append(Finding(
                    rule_id=self.id,
                    severity=self.default_severity,
                    message=f'DROP COLUMN {cols} on {op.table or "<unknown>"} is destructive',
                    file=context.file,
                    line=op.location.line,
                    column=op.location.column,
                ))
        return out


class TruncateRule(Rule):
    id = 'destructive-truncate'
    default_severity = 'error'

    def check(self, context: RuleContext) -> list[Finding]:
        out: list[Finding] = []
        for op in context.operations:
            if op.kind == 'TRUNCATE':
                out.append(Finding(
                    rule_id=self.id,
                    severity=self.default_severity,
                    message=f'TRUNCATE on {op.table or "<unknown>"} removes all rows',
                    file=context.file,
                    line=op.location.line,
                    column=op.location.column,
                ))
        return out


class DeleteWithoutWhereRule(Rule):
    id = 'delete-without-where'
    default_severity = 'warning'

    def check(self, context: RuleContext) -> list[Finding]:
        out: list[Finding] = []
        for op in context.operations:
            if op.kind == 'DELETE' and 'WHERE' not in op.statement.upper():
                out.append(Finding(
                    rule_id=self.id,
                    severity=self.default_severity,
                    message='DELETE without WHERE affects all rows',
                    file=context.file,
                    line=op.location.line,
                    column=op.location.column,
                ))
        return out


class UpdateWithoutWhereRule(Rule):
    id = 'update-without-where'
    default_severity = 'warning'

    def check(self, context: RuleContext) -> list[Finding]:
        out: list[Finding] = []
        for op in context.operations:
            if op.kind == 'UPDATE' and 'WHERE' not in op.statement.upper():
                out.append(Finding(
                    rule_id=self.id,
                    severity=self.default_severity,
                    message='UPDATE without WHERE affects all rows',
                    file=context.file,
                    line=op.location.line,
                    column=op.location.column,
                ))
        return out


class TransactionBoundaryRule(Rule):
    id = 'missing-transaction-boundary'
    default_severity = 'warning'

    def check(self, context: RuleContext) -> list[Finding]:
        ops = context.operations
        if len(ops) <= 1:
            return []
        has_begin = any(op.kind == 'TX_BEGIN' for op in ops)
        has_commit = any(op.kind == 'TX_COMMIT' for op in ops)
        if has_begin and has_commit:
            return []
        return [Finding(
            rule_id=self.id,
            severity=self.default_severity,
            message='Multi-statement migration lacks transaction boundaries (BEGIN/COMMIT)',
            file=context.file,
            line=ops[0].location.line,
            column=ops[0].location.column,
        )]


class NamingConventionRule(Rule):
    id = 'naming-convention'
    default_severity = 'warning'

    def check(self, context: RuleContext) -> list[Finding]:
        pattern = context.config.get('naming_pattern', r'^\d+_.+\.sql$')
        name = context.file.rsplit('/', 1)[-1]
        if re.match(pattern, name):
            return []
        return [Finding(
            rule_id=self.id,
            severity=self.default_severity,
            message=f'Migration filename {name!r} does not match {pattern!r}',
            file=context.file,
            line=1,
            column=1,
        )]


class DuplicateVersionRule(Rule):
    id = 'duplicate-version'
    default_severity = 'error'

    def check(self, context: RuleContext) -> list[Finding]:
        # Only run once per engine pass; guard by checking file list non-empty.
        if not context.all_files:
            return []
        # Group by leading version token.
        versions: dict[str, list[str]] = {}
        for f in context.all_files:
            name = f.rsplit('/', 1)[-1]
            m = re.match(r'(\d+)', name)
            if not m:
                continue
            versions.setdefault(m.group(1), []).append(f)
        out: list[Finding] = []
        for ver, files in versions.items():
            if len(files) > 1:
                out.append(Finding(
                    rule_id=self.id,
                    severity=self.default_severity,
                    message=f'Duplicate version {ver}: {files}',
                    file=files[0],
                    line=1,
                    column=1,
                ))
        return out


class VersionGapRule(Rule):
    id = 'version-gap'
    default_severity = 'warning'

    def check(self, context: RuleContext) -> list[Finding]:
        if not context.all_files:
            return []
        nums: list[int] = []
        for f in context.all_files:
            name = f.rsplit('/', 1)[-1]
            m = re.match(r'(\d+)', name)
            if m:
                nums.append(int(m.group(1)))
        nums = sorted(set(nums))
        if len(nums) < 2:
            return []
        out: list[Finding] = []
        for a, b in zip(nums, nums[1:]):
            if b - a > 1:
                out.append(Finding(
                    rule_id=self.id,
                    severity=self.default_severity,
                    message=f'Version gap between {a} and {b}',
                    file=context.all_files[0],
                    line=1,
                    column=1,
                ))
        return out


def default_rules() -> list[Rule]:
    return [
        DropTableRule(),
        DropColumnRule(),
        TruncateRule(),
        DeleteWithoutWhereRule(),
        UpdateWithoutWhereRule(),
        TransactionBoundaryRule(),
        NamingConventionRule(),
        DuplicateVersionRule(),
        VersionGapRule(),
    ]


class RuleEngine:
    """Applies a set of rules to migration contexts."""

    def __init__(
        self,
        rules: Sequence[Rule] | None = None,
        severity_overrides: dict[str, str] | None = None,
    ):
        self.rules = list(rules) if rules is not None else default_rules()
        self.severity_overrides = severity_overrides or {}

    def run(self, contexts: Iterable[RuleContext]) -> list[Finding]:
        findings: list[Finding] = []
        ctx_list = list(contexts)
        # Run collection-level rules once using a synthetic context.
        if ctx_list:
            base = ctx_list[0]
            collection_ctx = RuleContext(
                operations=[],
                file=base.file,
                config=base.config,
                all_files=base.all_files,
                all_operations=base.all_operations,
                pairs=base.pairs,
            )
            for rule in (DuplicateVersionRule(), VersionGapRule()):
                if rule.id in {r.id for r in self.rules}:
                    sev = self.severity_overrides.get(rule.id, rule.default_severity)
                    for f in rule.check(collection_ctx):
                        findings.append(replace(f, severity=sev))
        for ctx in ctx_list:
            for rule in self.rules:
                if rule.id in ('duplicate-version', 'version-gap'):
                    continue
                sev = self.severity_overrides.get(rule.id, rule.default_severity)
                for f in rule.check(ctx):
                    findings.append(replace(f, severity=sev))
        return findings
