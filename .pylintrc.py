[MASTER]
# List of plugins to load. Add 'pylint_django' if you install it for Django-specific checks.
# load-plugins=pylint_django

[MESSAGES CONTROL]
# Disable some checks that may be overly strict or irrelevant for a Django project.
# R: Refactoring, C: Convention, W: Warning, E: Error
disable=
    # W0511: fixme (often used in development, can be noisy)
    W0511,
    # C0114: Missing module docstring (often skipped for simple modules)
    C0114,
    # C0115: Missing class docstring (can be optional for simple classes)
    C0115,
    # C0116: Missing function or method docstring
    C0116,
    # W0613: Unused argument (common in Django views/signals)
    W0613,
    # R0903: Too few public methods (often true for Django forms, models)
    R0903

[REPORTS]
# Enable the output report.
output-format=text

[DESIGN]
# Set the maximum allowed value for Cyclomatic Complexity (via the 'R0912' message)
max-complexity=10
# Set the maximum number of public methods allowed in a class.
max-public-methods=20
# Set the maximum number of statements in a function/method body.
max-statements=50

[TYPECHECK]
# Ignore external packages that Pylint might have trouble analyzing (e.g., C-extensions).
# Add your Django environment's name if you see errors.
ignored-modules=
    django

[MISCELLANEOUS]
# Tell Pylint to ignore common Django folders.
# Pylint shouldn't analyze migration files or the virtual environment.
ignore-paths=
    migrations,
    venv,
    .git