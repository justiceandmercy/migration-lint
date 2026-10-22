# Architecture

migration-lint — A CLI that audits SQL migration files for destructive or unsafe changes, missing reversals, and transaction-safety issues before they reach production.

## Overview

The codebase is organized around a small set of focused modules. Each module owns a
single responsibility and the public surface is kept deliberately small so the tool
stays easy to hack on.

## Module map

| Path | Responsibility |
| ---- | -------------- |
| `pyproject.toml` | Package metadata, dependencies, console-script entry point, and default tool configuration. |
| `src/main.py` | CLI entry point that parses subcommands, loads configuration, runs audits, and returns appropriate exit codes. |
| `src/migration_lint/__init__.py` | Package initialization and public version metadata. |
| `src/migration_lint/config.py` | Load, validate, and merge configuration from files and command-line overrides. |
| `src/migration_lint/discovery.py` | Find migration files by glob, sort them by version or filename, and identify paired up/down files. |
| `src/migration_lint/parser.py` | Tokenize SQL and parse statements into normalized operation objects with locations. |
| `src/migration_lint/rules.py` | Implement the rule engine and built-in checks for destructive, unsafe, and convention violations. |
| `src/migration_lint/reversal.py` | Match up and down migrations, detect missing reversals, and honor irreversibility declarations. |
| `src/migration_lint/reporters.py` | Render audit findings as text, JSON, and SARIF with stable schemas and severity grouping. |
| `src/migration_lint/baseline.py` | Read and write baseline files and compare current findings against accepted historical results. |
| `tests/test_parser.py` | Unit tests for SQL tokenization, statement splitting, and operation extraction. |
| `tests/test_rules.py` | Unit tests for rule classification, severity handling, transaction checks, and reversal logic. |
| `tests/test_cli.py` | Integration tests for CLI subcommands, configuration loading, baseline behavior, and exit codes. |
| `docs/usage.md` | Document installation, configuration, rules, output formats, CI usage, and plugin development. |

## Key design decisions

- **Zero/low runtime dependencies**: the core works from the standard library so
  installs stay fast and supply-chain risk stays low.
- **Configuration before convention**: behavior is tunable through config files and
  documented CLI flags instead of magic environment variables.
- **Structured output modes**: human-readable text by default, machine-readable JSON
  for automation, and DOT/Mermaid exports where a graph applies.
- **Everything is guarded by tests**: the CI matrix runs the suite on every push.

## Data flow

`CLI entrypoint -> config loading -> per-item scanning/processing -> aggregation ->
reporting (text | JSON | graph)`.

## Testing

Unit tests cover SQL tokenization, operation classification, reversal pairing, configuration validation, baseline diffing, and CLI exit codes; integration tests invoke the CLI against fixture migration directories and assert text, JSON, and SARIF output.

Run them locally with `pytest -q`. CI (`.github/workflows/ci.yml`) executes the
same suite on a version matrix for every push and pull request.
