# migration-lint

> A CLI that audits SQL migration files for destructive or unsafe changes, missing reversals, and transaction-safety issues before they reach production.

[![CI](https://github.com/justiceandmercy/migration-lint/actions/workflows/ci.yml/badge.svg)](https://github.com/justiceandmercy/migration-lint/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Topics:** sql, migrations, database, cli, linter, devtools, static-analysis

## Features

- Discover migration files using configurable glob patterns and deterministic ordering rules.
- Parse SQL into a structured operation model with a lightweight tokenizer and statement splitter.
- Classify operations as destructive, reversible, or safe with configurable severity levels.
- Detect missing transaction boundaries around multi-statement or multi-file migrations.
- Verify up migrations have matching down migrations or explicit irreversibility markers.
- Enforce migration naming, versioning, and sequence conventions to catch gaps and duplicates.
- Support baseline files to suppress known findings and detect newly introduced regressions.
- Emit human-readable, JSON, and SARIF reports for local development and CI pipelines.
- Load configuration from pyproject.toml or .migration-lint.toml with per-rule severity overrides.
- Provide plugin hooks for custom operation classifiers and organization-specific policies.

## Install

```sh
git clone https://github.com/justiceandmercy/migration-lint.git
cd migration-lint
pip install .
```

## Quick start

```sh
migration-lint --help
```

Entry point: `src/main.py`.

## Architecture

- `pyproject.toml` — Package metadata, dependencies, console-script entry point, and default tool configuration.
- `src/main.py` — CLI entry point that parses subcommands, loads configuration, runs audits, and returns appropriate exit codes.
- `src/migration_lint/__init__.py` — Package initialization and public version metadata.
- `src/migration_lint/config.py` — Load, validate, and merge configuration from files and command-line overrides.
- `src/migration_lint/discovery.py` — Find migration files by glob, sort them by version or filename, and identify paired up/down files.
- `src/migration_lint/parser.py` — Tokenize SQL and parse statements into normalized operation objects with locations.
- `src/migration_lint/rules.py` — Implement the rule engine and built-in checks for destructive, unsafe, and convention violations.
- `src/migration_lint/reversal.py` — Match up and down migrations, detect missing reversals, and honor irreversibility declarations.
- `src/migration_lint/reporters.py` — Render audit findings as text, JSON, and SARIF with stable schemas and severity grouping.
- `src/migration_lint/baseline.py` — Read and write baseline files and compare current findings against accepted historical results.
- `tests/test_parser.py` — Unit tests for SQL tokenization, statement splitting, and operation extraction.
- `tests/test_rules.py` — Unit tests for rule classification, severity handling, transaction checks, and reversal logic.
- `tests/test_cli.py` — Integration tests for CLI subcommands, configuration loading, baseline behavior, and exit codes.
- `docs/usage.md` — Document installation, configuration, rules, output formats, CI usage, and plugin development.

For the full module map and design decisions, read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Testing

```sh
pytest -q
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). PRs welcome!

## License

MIT — see [LICENSE](LICENSE).
