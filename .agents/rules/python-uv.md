# Python UV Rules

## Initialization

Use `uv` for Python project initialization and dependency management.

```bash
uv init .
uv add --dev pyright ruff
```

Configure `pyright` in `pyproject.toml`:

```toml
[tool.pyright]
venvPath = "."
venv = ".venv"
pythonVersion = "..."
useLibraryCodeForTypes = true
typeCheckingMode = "strict"
```

Use the Python version declared by the repository. Do not introduce a separate environment or dependency manager.

## Commands

Use `uv` to synchronize dependencies and run Python tooling.

```bash
uv sync
uv run ruff format .
uv run ruff check .
uv run pyright
uv run pytest
```

Code MUST pass the configured formatter, linter, type checker, and relevant tests.

Before adding commands, dependencies, or tool configuration, inspect `pyproject.toml` and follow the repository's existing conventions.

Do not invoke project tools through a globally installed executable when they are available through `uv run`.
