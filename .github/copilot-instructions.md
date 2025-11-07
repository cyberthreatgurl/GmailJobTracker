# 🧠 Copilot Instructions: Linting and Formatting Standards

## 🐍 Python Code Style (Pylint)
Copilot must follow these Python standards:

- Use `snake_case` for variables, functions, and method names.
- Limit line length to 100 characters.
- Avoid wildcard imports (`from module import *`).
- Include docstrings for all public functions and classes.
- Use explicit exception types (`except ValueError:` not `except:`).
- Prefer `is`/`is not` for `None` comparisons.
- Avoid unused imports and variables.
- Respect indentation and spacing rules from `.pylintrc` or `pyproject.toml`.

### ✅ Example
```python
def fetch_data(source: str) -> dict:
    """Fetches data from the given source."""
    if source is None:
        raise ValueError("Source cannot be None")
    return {"data": source}
