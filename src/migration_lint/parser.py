"""Lightweight SQL tokenizer and statement parser."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

_KEYWORDS = {
    'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER', 'TRUNCATE',
    'RENAME', 'BEGIN', 'COMMIT', 'ROLLBACK', 'START', 'TRANSACTION', 'TABLE',
    'INDEX', 'COLUMN', 'IF', 'NOT', 'EXISTS', 'INTO', 'VALUES', 'SET', 'WHERE',
    'ADD', 'MODIFY', 'CHANGE', 'RENAME', 'TO', 'CASCADE', 'RESTRICT',
}


@dataclass(frozen=True)
class Location:
    """Source location of an operation."""

    file: str
    line: int
    column: int


@dataclass
class Token:
    """A single SQL token."""

    kind: str
    value: str
    line: int
    column: int


@dataclass
class Operation:
    """A normalized SQL operation."""

    kind: str
    statement: str
    location: Location
    table: str | None = None
    columns: list[str] = field(default_factory=list)


def tokenize(sql: str, filename: str = '<input>') -> list[Token]:
    """Tokenize SQL text into a list of tokens."""
    tokens: list[Token] = []
    i = 0
    n = len(sql)
    line = 1
    col = 1

    def advance_one() -> None:
        nonlocal line, col
        if i >= n:
            return
        ch = sql[i]
        if ch == '\n':
            line += 1
            col = 1
        else:
            col += 1

    while i < n:
        ch = sql[i]
        if ch in ' \t\r\n':
            advance_one()
            i += 1
            continue
        start_line, start_col = line, col
        # line comment
        if ch == '-' and i + 1 < n and sql[i + 1] == '-':
            while i < n and sql[i] != '\n':
                advance_one()
                i += 1
            continue
        # block comment
        if ch == '/' and i + 1 < n and sql[i + 1] == '*':
            for _ in range(2):
                advance_one()
                i += 1
            while i < n and not (sql[i] == '*' and i + 1 < n and sql[i + 1] == '/'):
                advance_one()
                i += 1
            if i < n:
                for _ in range(2):
                    if i < n:
                        advance_one()
                        i += 1
            continue
        # single-quoted string
        if ch == "'":
            buf = ch
            advance_one()
            i += 1
            while i < n:
                c = sql[i]
                buf += c
                advance_one()
                i += 1
                if c == "'":
                    if i < n and sql[i] == "'":
                        buf += sql[i]
                        advance_one()
                        i += 1
                        continue
                    break
            tokens.append(Token('string', buf, start_line, start_col))
            continue
        # double-quoted / backtick identifier
        if ch in ('"', '`'):
            quote = ch
            buf = quote
            advance_one()
            i += 1
            while i < n:
                c = sql[i]
                buf += c
                advance_one()
                i += 1
                if c == quote:
                    if i < n and sql[i] == quote:
                        buf += sql[i]
                        advance_one()
                        i += 1
                        continue
                    break
            tokens.append(Token('identifier', buf, start_line, start_col))
            continue
        # number
        if ch.isdigit():
            buf = ''
            while i < n and (sql[i].isdigit() or sql[i] == '.'):
                buf += sql[i]
                advance_one()
                i += 1
            tokens.append(Token('number', buf, start_line, start_col))
            continue
        # identifier / keyword
        if ch.isalpha() or ch == '_':
            buf = ''
            while i < n and (sql[i].isalnum() or sql[i] == '_'):
                buf += sql[i]
                advance_one()
                i += 1
            kind = 'keyword' if buf.upper() in _KEYWORDS else 'identifier'
            tokens.append(Token(kind, buf, start_line, start_col))
            continue
        # punctuation / operators
        tokens.append(Token('punct', ch, start_line, start_col))
        advance_one()
        i += 1

    return tokens


def split_statements(tokens: list[Token]) -> list[list[Token]]:
    """Split a token stream into top-level statements."""
    statements: list[list[Token]] = []
    current: list[Token] = []
    depth = 0
    for t in tokens:
        if t.kind == 'punct' and t.value == '(':
            depth += 1
            current.append(t)
        elif t.kind == 'punct' and t.value == ')':
            depth = max(0, depth - 1)
            current.append(t)
        elif t.kind == 'punct' and t.value == ';' and depth == 0:
            if current:
                statements.append(current)
                current = []
        else:
            current.append(t)
    if current:
        statements.append(current)
    return statements


def _text(tokens: list[Token]) -> str:
    return ' '.join(t.value for t in tokens)


def _extract_table(text: str, keyword: str) -> str | None:
    pattern = re.compile(
        keyword + r'\s+(?:IF\s+NOT\s+EXISTS\s+|IF\s+EXISTS\s+)?(["`\[]?[\w.]+["`\]]?)',
        re.IGNORECASE,
    )
    m = pattern.search(text)
    if not m:
        return None
    return m.group(1).strip('"`[]')


def _extract_columns(text: str) -> list[str]:
    cols: list[str] = []
    # ALTER TABLE ... DROP COLUMN col / ADD COLUMN col
    for m in re.finditer(r'(?:DROP|ADD)\s+COLUMN\s+(["`\[]?[\w]+["`\]]?)', text, re.IGNORECASE):
        cols.append(m.group(1).strip('"`[]'))
    return cols


def parse_statement(tokens: list[Token], filename: str = '<input>') -> Operation:
    """Parse a single statement's tokens into an Operation."""
    text = _text(tokens)
    loc = Location(filename, tokens[0].line, tokens[0].column) if tokens else Location(filename, 1, 1)
    upper = text.upper().strip()
    kind = 'UNKNOWN'
    table: str | None = None
    columns: list[str] = []

    if upper.startswith('CREATE TABLE'):
        kind = 'CREATE_TABLE'
        table = _extract_table(text, 'CREATE\s+TABLE')
    elif upper.startswith('DROP TABLE'):
        kind = 'DROP_TABLE'
        table = _extract_table(text, 'DROP\s+TABLE')
    elif upper.startswith('ALTER TABLE'):
        kind = 'ALTER_TABLE'
        table = _extract_table(text, 'ALTER\s+TABLE')
        columns = _extract_columns(text)
        if 'DROP' in upper and 'COLUMN' in upper:
            kind = 'DROP_COLUMN'
        elif 'ADD' in upper and 'COLUMN' in upper:
            kind = 'ADD_COLUMN'
    elif upper.startswith('TRUNCATE'):
        kind = 'TRUNCATE'
        table = _extract_table(text, 'TRUNCATE\s+(?:TABLE\s+)?')
    elif upper.startswith('DELETE'):
        kind = 'DELETE'
        m = re.search(r'FROM\s+(["`\[]?[\w.]+["`\]]?)', text, re.IGNORECASE)
        table = m.group(1).strip('"`[]') if m else None
    elif upper.startswith('UPDATE'):
        kind = 'UPDATE'
        m = re.search(r'UPDATE\s+(["`\[]?[\w.]+["`\]]?)', text, re.IGNORECASE)
        table = m.group(1).strip('"`[]') if m else None
    elif upper.startswith('INSERT'):
        kind = 'INSERT'
        m = re.search(r'INTO\s+(["`\[]?[\w.]+["`\]]?)', text, re.IGNORECASE)
        table = m.group(1).strip('"`[]') if m else None
    elif upper.startswith('RENAME'):
        kind = 'RENAME'
    elif upper.startswith('CREATE INDEX'):
        kind = 'CREATE_INDEX'
    elif upper.startswith('DROP INDEX'):
        kind = 'DROP_INDEX'
    elif upper.startswith('BEGIN') or upper.startswith('START TRANSACTION'):
        kind = 'TX_BEGIN'
    elif upper.startswith('COMMIT'):
        kind = 'TX_COMMIT'
    elif upper.startswith('ROLLBACK'):
        kind = 'TX_ROLLBACK'

    return Operation(kind=kind, statement=text, location=loc, table=table, columns=columns)


def parse_sql(sql: str, filename: str = '<input>') -> list[Operation]:
    """Parse SQL text into a list of operations."""
    tokens = tokenize(sql, filename)
    statements = split_statements(tokens)
    ops: list[Operation] = []
    for stmt in statements:
        if not stmt:
            continue
        if all(t.kind in ('',) for t in stmt):
            continue
        ops.append(parse_statement(stmt, filename))
    return ops


def parse_file(path: Path | str) -> list[Operation]:
    """Read and parse a migration file."""
    path = Path(path)
    try:
        sql = path.read_text(encoding='utf-8')
    except OSError as exc:
        raise RuntimeError(f'Cannot read migration file {path}: {exc}') from exc
    return parse_sql(sql, str(path))
