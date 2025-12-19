#!/usr/bin/env python3
"""
Code Quality Analyzer for GmailJobTracker
Detects dead code, redundancy, and complexity issues.

Usage:
    python scripts/analyze_code_quality.py [--fix-imports] [--verbose]
"""

import ast
import json
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple


class CodeAnalyzer(ast.NodeVisitor):
    """AST visitor to analyze Python code structure."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.functions: Dict[str, int] = {}  # name -> line number
        self.classes: Dict[str, int] = {}
        self.imports: Set[str] = set()
        self.used_names: Set[str] = set()
        self.decorators: Dict[str, List[str]] = defaultdict(list)  # func -> decorators

    def visit_FunctionDef(self, node):
        self.functions[node.name] = node.lineno
        # Track decorators (login_required, csrf_exempt, etc.)
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name):
                self.decorators[node.name].append(dec.id)
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        self.classes[node.name] = node.lineno
        self.generic_visit(node)

    def visit_Import(self, node):
        for alias in node.names:
            self.imports.add(alias.name)

    def visit_ImportFrom(self, node):
        if node.module:
            for alias in node.names:
                self.imports.add(f"{node.module}.{alias.name}")

    def visit_Name(self, node):
        self.used_names.add(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node):
        if isinstance(node.value, ast.Name):
            self.used_names.add(node.value.id)
        self.generic_visit(node)


def analyze_file(filepath: Path) -> CodeAnalyzer:
    """Parse and analyze a Python file."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        tree = ast.parse(content, filename=str(filepath))
        analyzer = CodeAnalyzer(str(filepath))
        analyzer.visit(tree)
        return analyzer
    except Exception as e:
        print(f"⚠️ Error analyzing {filepath}: {e}")
        return None


def find_dead_code(project_root: Path) -> Dict[str, List[Tuple[str, int]]]:
    """Find potentially unused functions and classes."""
    print("🔍 Analyzing for dead code...")

    # Collect all definitions and usages
    all_definitions = defaultdict(list)  # name -> [(file, line)]
    all_usages = defaultdict(set)  # name -> {files}
    analyzers = {}

    # Scan all Python files
    py_files = list(project_root.rglob("*.py"))
    py_files = [
        f for f in py_files if ".venv" not in str(f) and "__pycache__" not in str(f)
    ]

    for py_file in py_files:
        analyzer = analyze_file(py_file)
        if not analyzer:
            continue

        analyzers[py_file] = analyzer
        rel_path = py_file.relative_to(project_root)

        # Track definitions
        for func_name, line in analyzer.functions.items():
            all_definitions[func_name].append((str(rel_path), line))
        for class_name, line in analyzer.classes.items():
            all_definitions[class_name].append((str(rel_path), line))

        # Track usages
        for name in analyzer.used_names:
            all_usages[name].add(str(rel_path))

    # Find potentially dead code
    dead_code = defaultdict(list)
    for name, defs in all_definitions.items():
        # Skip if name starts with _ (private/magic methods)
        if name.startswith("_"):
            continue

        # Skip Django-specific patterns
        django_patterns = {"Meta", "Admin", "Migration", "Config"}
        if any(pattern in name for pattern in django_patterns):
            continue

        # Check if used anywhere (excluding self-reference)
        used_files = all_usages.get(name, set())
        def_files = {f for f, _ in defs}

        # If only used in its own file, flag as potentially dead
        if used_files <= def_files:
            for filepath, line in defs:
                # Check for decorators that indicate URL/admin registration
                file_path = project_root / filepath
                if file_path in analyzers:
                    analyzer = analyzers[file_path]
                    if name in analyzer.decorators:
                        decorators = analyzer.decorators[name]
                        # Skip if has routing/admin decorators
                        if any(
                            d in ["login_required", "csrf_exempt", "admin.register"]
                            for d in decorators
                        ):
                            continue

                dead_code[filepath].append((name, line))

    return dict(dead_code)


def find_duplicate_code(project_root: Path, min_lines: int = 5) -> List[Dict]:
    """Find duplicate code blocks (simple line-based detection)."""
    print("🔍 Analyzing for duplicate code...")

    py_files = list(project_root.rglob("*.py"))
    py_files = [
        f for f in py_files if ".venv" not in str(f) and "__pycache__" not in str(f)
    ]

    # Extract code blocks (functions)
    code_blocks = []
    for py_file in py_files:
        try:
            with open(py_file, "r", encoding="utf-8") as f:
                lines = f.readlines()

            # Simple function extraction
            in_function = False
            func_lines = []
            func_start = 0
            func_name = ""

            for i, line in enumerate(lines, 1):
                if re.match(r"^\s*def\s+(\w+)", line):
                    if func_lines:
                        code_blocks.append(
                            {
                                "file": str(py_file.relative_to(project_root)),
                                "name": func_name,
                                "start": func_start,
                                "lines": func_lines,
                                "hash": hash("".join(func_lines).strip()),
                            }
                        )
                    match = re.match(r"^\s*def\s+(\w+)", line)
                    func_name = match.group(1)
                    func_start = i
                    func_lines = [line]
                    in_function = True
                elif in_function:
                    if (
                        line.strip()
                        and not line[0].isspace()
                        and not line.startswith("def")
                    ):
                        # End of function
                        if len(func_lines) >= min_lines:
                            code_blocks.append(
                                {
                                    "file": str(py_file.relative_to(project_root)),
                                    "name": func_name,
                                    "start": func_start,
                                    "lines": func_lines,
                                    "hash": hash("".join(func_lines).strip()),
                                }
                            )
                        in_function = False
                        func_lines = []
                    else:
                        func_lines.append(line)

        except Exception as e:
            print(f"⚠️ Error processing {py_file}: {e}")

    # Find duplicates by hash
    hash_groups = defaultdict(list)
    for block in code_blocks:
        if len(block["lines"]) >= min_lines:
            hash_groups[block["hash"]].append(block)

    duplicates = []
    for blocks in hash_groups.values():
        if len(blocks) > 1:
            duplicates.append(
                {
                    "count": len(blocks),
                    "locations": [(b["file"], b["name"], b["start"]) for b in blocks],
                    "line_count": len(blocks[0]["lines"]),
                }
            )

    return sorted(duplicates, key=lambda x: x["line_count"], reverse=True)


def analyze_file_complexity(project_root: Path) -> List[Dict]:
    """Analyze Python files for size and complexity."""
    print("🔍 Analyzing file complexity...")

    py_files = list(project_root.rglob("*.py"))
    py_files = [
        f for f in py_files if ".venv" not in str(f) and "__pycache__" not in str(f)
    ]

    file_stats = []
    for py_file in py_files:
        try:
            with open(py_file, "r", encoding="utf-8") as f:
                lines = f.readlines()

            total_lines = len(lines)
            code_lines = sum(
                1 for line in lines if line.strip() and not line.strip().startswith("#")
            )

            analyzer = analyze_file(py_file)
            if analyzer:
                num_functions = len(analyzer.functions)
                num_classes = len(analyzer.classes)
                num_imports = len(analyzer.imports)
            else:
                num_functions = num_classes = num_imports = 0

            rel_path = py_file.relative_to(project_root)
            file_stats.append(
                {
                    "file": str(rel_path),
                    "total_lines": total_lines,
                    "code_lines": code_lines,
                    "functions": num_functions,
                    "classes": num_classes,
                    "imports": num_imports,
                    "avg_lines_per_function": (
                        code_lines // num_functions if num_functions > 0 else 0
                    ),
                }
            )

        except Exception as e:
            print(f"⚠️ Error analyzing {py_file}: {e}")

    return sorted(file_stats, key=lambda x: x["total_lines"], reverse=True)


def find_unused_imports(project_root: Path) -> Dict[str, List[str]]:
    """Find potentially unused imports."""
    print("🔍 Analyzing for unused imports...")

    py_files = list(project_root.rglob("*.py"))
    py_files = [
        f for f in py_files if ".venv" not in str(f) and "__pycache__" not in str(f)
    ]

    unused = {}
    for py_file in py_files:
        try:
            with open(py_file, "r", encoding="utf-8") as f:
                content = f.read()

            # Extract imports
            import_pattern = r"^(?:from\s+[\w.]+\s+)?import\s+([\w\s,]+)"
            imports = []
            for match in re.finditer(import_pattern, content, re.MULTILINE):
                import_names = match.group(1).split(",")
                for name in import_names:
                    name = name.strip().split(" as ")[0].strip()
                    imports.append(name)

            # Check usage (simple text search)
            file_unused = []
            for imp in imports:
                # Skip common Django imports that may not appear directly
                if imp in ["models", "forms", "admin", "Q", "F", "Count", "Sum"]:
                    continue

                # Check if import name appears elsewhere in file
                pattern = rf"\b{re.escape(imp)}\b"
                matches = list(re.finditer(pattern, content))
                # If only appears once (the import itself), it's unused
                if len(matches) <= 1:
                    file_unused.append(imp)

            if file_unused:
                rel_path = py_file.relative_to(project_root)
                unused[str(rel_path)] = file_unused

        except Exception as e:
            print(f"⚠️ Error checking imports in {py_file}: {e}")

    return unused


def generate_report(project_root: Path, output_file: str = "code_quality_report.json"):
    """Generate comprehensive code quality report."""
    print("=" * 60)
    print("📊 Code Quality Analysis for GmailJobTracker")
    print("=" * 60)

    report = {
        "timestamp": (
            Path(output_file).stat().st_mtime if Path(output_file).exists() else None
        ),
        "dead_code": {},
        "duplicates": [],
        "file_complexity": [],
        "unused_imports": {},
    }

    # 1. Dead code analysis
    dead_code = find_dead_code(project_root)
    report["dead_code"] = dead_code
    if dead_code:
        print(
            f"\n⚠️ Found {sum(len(v) for v in dead_code.values())} potentially unused definitions:"
        )
        for filepath, items in sorted(dead_code.items())[:10]:
            print(f"\n  {filepath}:")
            for name, line in items[:5]:
                print(f"    - {name} (line {line})")
            if len(items) > 5:
                print(f"    ... and {len(items) - 5} more")
    else:
        print("\n✅ No obvious dead code found")

    # 2. Duplicate code analysis
    duplicates = find_duplicate_code(project_root)
    report["duplicates"] = duplicates
    if duplicates:
        print(f"\n⚠️ Found {len(duplicates)} duplicate code blocks:")
        for dup in duplicates[:5]:
            print(f"\n  {dup['line_count']} lines duplicated {dup['count']} times:")
            for filepath, name, line in dup["locations"]:
                print(f"    - {filepath}:{name} (line {line})")
    else:
        print("\n✅ No significant duplicate code found")

    # 3. File complexity analysis
    file_stats = analyze_file_complexity(project_root)
    report["file_complexity"] = file_stats
    print(f"\n📏 File Complexity (Top 10 largest files):")
    print(f"{'File':<40} {'Lines':<10} {'Functions':<10} {'Classes':<10}")
    print("-" * 70)
    for stat in file_stats[:10]:
        print(
            f"{stat['file']:<40} {stat['total_lines']:<10} {stat['functions']:<10} {stat['classes']:<10}"
        )

    # Highlight oversized files
    oversized = [s for s in file_stats if s["total_lines"] > 1000]
    if oversized:
        print(f"\n⚠️ {len(oversized)} files exceed 1000 lines (consider splitting):")
        for stat in oversized[:5]:
            print(
                f"  - {stat['file']}: {stat['total_lines']} lines, {stat['functions']} functions"
            )

    # 4. Unused imports
    unused_imports = find_unused_imports(project_root)
    report["unused_imports"] = unused_imports
    if unused_imports:
        print(f"\n⚠️ Found unused imports in {len(unused_imports)} files:")
        for filepath, imports in list(unused_imports.items())[:5]:
            print(f"\n  {filepath}:")
            for imp in imports[:5]:
                print(f"    - {imp}")
    else:
        print("\n✅ No obvious unused imports found")

    # Save report
    output_path = project_root / output_file
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"\n📄 Full report saved to: {output_file}")
    print("=" * 60)

    return report


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Analyze code quality")
    parser.add_argument(
        "--output", default="code_quality_report.json", help="Output report file"
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    generate_report(project_root, args.output)


if __name__ == "__main__":
    main()
