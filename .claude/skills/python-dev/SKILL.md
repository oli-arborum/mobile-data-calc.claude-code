---
name: python-guidelines
description: Python coding guidelines for building maintainable, and testable command-line tools. Use this skill when generating or modifying Python code.
---

# Agent Guidelines (Python)

You are an expert in modern Python backend development. You write maintainable, secure, and well-tested code aligned with current Python ecosystem best practices and this repository’s conventions.

## Language & Formatting Conventions

- Use **type hints everywhere** (functions, return types, attributes). Keep `pyright` strict.
- Prefer `from __future__ import annotations` in modules that declare lots of types.
- Prefer **explicit, readable code** over cleverness.
- Use **f-strings** for interpolation.
- Keep imports clean and layered:
  - stdlib
  - third-party
  - local (`from app...`)
- Follow `ruff` formatting (line-length 120, double quotes).
- Use `TYPE_CHECKING` for imports needed only for typing to avoid runtime cycles.

## Python Best Practices

- Prefer **pure functions** and small units with clear inputs/outputs.
- Validate inputs early; use **guard clauses** and keep the happy path obvious.
- Avoid global mutable state (especially shared sessions/clients).
- Prefer `pathlib.Path` for filesystem paths.
- Use timezone-aware timestamps where applicable; treat UTC as the default for storage/transport.
- Don’t catch broad exceptions unless you re-raise or translate them into a well-defined error response.
- Prefer `logging` over `print()`.

## Testing (unittest framework)

- Prefer deterministic, isolated tests.
- Use behavior-focused test names and assertions.
