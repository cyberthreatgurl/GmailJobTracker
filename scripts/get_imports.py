"""Utility to extract and analyze Python imports across the codebase."""

import os
import re
import subprocess


def get_repo_root():
    """Get the root directory of the git repository."""
    return (
        subprocess.check_output(["git", "rev-parse", "--show-toplevel"])
        .decode()
        .strip()
    )


def extract_imports():
    """Extract all import statements from Python files in the last git commit."""
    repo_root = get_repo_root()
    os.chdir(repo_root)

    # Get committed .py files from latest commit
    commit_hash = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    files = (
        subprocess.check_output(
            ["git", "show", "--pretty=", "--name-only", commit_hash]
        )
        .decode()
        .splitlines()
    )
    py_files = [f for f in files if f.endswith(".py")]

    imports = set()
    pattern = re.compile(r"^\s*(import|from)\s+([a-zA-Z0-9_\.]+)")

    for file in py_files:
        try:
            with open(file, "r", encoding="utf-8") as f:
                for line in f:
                    match = pattern.match(line)
                    if match:
                        module = match.group(2).split(".")[0]
                        imports.add(module)
        except FileNotFoundError:
            continue

    print("📦 Modules detected in committed .py files:")
    for module in sorted(imports):
        print(f"- {module}")

    return imports


extract_imports()
