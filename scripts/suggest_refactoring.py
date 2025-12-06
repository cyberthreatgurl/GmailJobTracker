#!/usr/bin/env python3
"""
Refactoring Suggestions for Large Python Files
Analyzes large files and suggests how to split them into modules.

Usage:
    python scripts/suggest_refactoring.py [--file views.py] [--threshold 500]
"""

import ast
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set


class FunctionAnalyzer(ast.NodeVisitor):
    """Analyze function dependencies and groupings."""

    def __init__(self):
        self.functions = {}  # name -> {line, decorators, calls, imports}
        self.current_function = None
        self.imports = set()

    def visit_Import(self, node):
        for alias in node.names:
            self.imports.add(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module:
            for alias in node.names:
                self.imports.add(f"{node.module}.{alias.name}")
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        decorators = []
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name):
                decorators.append(dec.id)
            elif isinstance(dec, ast.Attribute):
                decorators.append(f"{dec.value.id}.{dec.attr}" if isinstance(dec.value, ast.Name) else dec.attr)

        self.functions[node.name] = {
            "line": node.lineno,
            "decorators": decorators,
            "calls": set(),
            "imports_used": set(),
            "models_accessed": set(),
            "returns_response": False,
        }

        # Track what this function calls/uses
        old_func = self.current_function
        self.current_function = node.name
        self.generic_visit(node)
        self.current_function = old_func

    def visit_Call(self, node):
        if self.current_function:
            # Track function calls
            func_name = None
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name):
                    func_name = f"{node.func.value.id}.{node.func.attr}"
                else:
                    func_name = node.func.attr

            if func_name:
                self.functions[self.current_function]["calls"].add(func_name)

                # Track model access
                if func_name.endswith(".objects") or func_name.endswith(".filter") or func_name.endswith(".all"):
                    model_name = func_name.split(".")[0]
                    self.functions[self.current_function]["models_accessed"].add(model_name)

        self.generic_visit(node)

    def visit_Return(self, node):
        if self.current_function and node.value:
            # Check if returns render/redirect/JsonResponse
            if isinstance(node.value, ast.Call):
                if isinstance(node.value.func, ast.Name):
                    if node.value.func.id in ["render", "redirect", "JsonResponse", "HttpResponse"]:
                        self.functions[self.current_function]["returns_response"] = True

        self.generic_visit(node)


def analyze_large_file(filepath: Path) -> Dict:
    """Analyze a large Python file and suggest refactoring."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
        lines = content.splitlines()

    tree = ast.parse(content)
    analyzer = FunctionAnalyzer()
    analyzer.visit(tree)

    # Group functions by purpose/pattern
    groups = defaultdict(list)

    for func_name, info in analyzer.functions.items():
        # Categorize by decorators and patterns
        if "login_required" in info["decorators"]:
            if info["returns_response"]:
                # This is a view function
                if "api" in func_name.lower() or "json" in func_name.lower():
                    groups["API Views"].append(func_name)
                elif any(keyword in func_name.lower() for keyword in ["company", "companies"]):
                    groups["Company Views"].append(func_name)
                elif any(keyword in func_name.lower() for keyword in ["message", "label"]):
                    groups["Message/Label Views"].append(func_name)
                elif any(keyword in func_name.lower() for keyword in ["domain", "pattern"]):
                    groups["Domain/Config Views"].append(func_name)
                elif any(keyword in func_name.lower() for keyword in ["ingest", "reingest", "gmail"]):
                    groups["Ingestion Views"].append(func_name)
                elif any(keyword in func_name.lower() for keyword in ["metric", "stat", "dashboard"]):
                    groups["Dashboard/Metrics Views"].append(func_name)
                else:
                    groups["Other Views"].append(func_name)
            else:
                groups["View Helpers"].append(func_name)
        elif "csrf_exempt" in info["decorators"]:
            groups["API Endpoints (CSRF Exempt)"].append(func_name)
        elif func_name.startswith("_") or not info["returns_response"]:
            # Utility/helper functions
            if "validate" in func_name.lower() or "sanitize" in func_name.lower():
                groups["Validation/Sanitization Helpers"].append(func_name)
            elif "parse" in func_name.lower() or "extract" in func_name.lower():
                groups["Parsing Helpers"].append(func_name)
            else:
                groups["Utility Functions"].append(func_name)
        else:
            groups["Uncategorized"].append(func_name)

    # Generate statistics
    stats = {
        "total_lines": len(lines),
        "total_functions": len(analyzer.functions),
        "groups": dict(groups),
        "imports": analyzer.imports,
    }

    return stats


def suggest_file_split(filepath: Path, threshold: int = 500):
    """Suggest how to split a large file into modules."""
    print(f"\n📁 Analyzing: {filepath.name}")
    print("=" * 60)

    stats = analyze_large_file(filepath)

    print(f"Total lines: {stats['total_lines']}")
    print(f"Total functions: {stats['total_functions']}")
    print(f"Total imports: {len(stats['imports'])}")

    if stats["total_lines"] < threshold:
        print(f"✅ File is under {threshold} lines - no split recommended")
        return

    print(f"\n⚠️ File exceeds {threshold} lines")
    print("\n💡 Suggested module split:\n")

    # Suggest module structure
    groups = stats["groups"]

    # Primary views split
    view_groups = {
        "views_company.py": groups.get("Company Views", []),
        "views_messages.py": groups.get("Message/Label Views", []),
        "views_domain.py": groups.get("Domain/Config Views", []),
        "views_ingestion.py": groups.get("Ingestion Views", []),
        "views_dashboard.py": groups.get("Dashboard/Metrics Views", []),
        "views_api.py": groups.get("API Views", []) + groups.get("API Endpoints (CSRF Exempt)", []),
    }

    # Helpers/utils split
    util_groups = {
        "utils/validators.py": groups.get("Validation/Sanitization Helpers", []),
        "utils/parsers.py": groups.get("Parsing Helpers", []),
        "utils/helpers.py": groups.get("View Helpers", []) + groups.get("Utility Functions", []),
    }

    print("📦 Suggested View Modules:")
    for module, funcs in view_groups.items():
        if funcs:
            print(f"\n  {module} ({len(funcs)} functions):")
            for func in sorted(funcs)[:5]:
                print(f"    - {func}")
            if len(funcs) > 5:
                print(f"    ... and {len(funcs) - 5} more")

    print("\n📦 Suggested Utility Modules:")
    for module, funcs in util_groups.items():
        if funcs:
            print(f"\n  {module} ({len(funcs)} functions):")
            for func in sorted(funcs)[:5]:
                print(f"    - {func}")
            if len(funcs) > 5:
                print(f"    ... and {len(funcs) - 5} more")

    uncategorized = groups.get("Uncategorized", []) + groups.get("Other Views", [])
    if uncategorized:
        print(f"\n⚠️ Uncategorized functions ({len(uncategorized)}):")
        for func in sorted(uncategorized)[:10]:
            print(f"    - {func}")

    print("\n" + "=" * 60)
    print("📋 Next Steps:")
    print("1. Create new module files in tracker/ or tracker/utils/")
    print("2. Move functions to appropriate modules")
    print("3. Update imports in main views.py")
    print("4. Update URL routing if needed")
    print("5. Run tests to ensure nothing broke")
    print("=" * 60)


def generate_refactor_plan(project_root: Path, output_file: str = "refactor_plan.txt"):
    """Generate detailed refactoring plan for all large files."""
    py_files = list(project_root.rglob("*.py"))
    py_files = [f for f in py_files if ".venv" not in str(f) and "__pycache__" not in str(f)]

    large_files = []
    for py_file in py_files:
        try:
            with open(py_file, "r", encoding="utf-8") as f:
                lines = len(f.readlines())
            if lines > 500:
                large_files.append((py_file, lines))
        except Exception:
            pass

    large_files.sort(key=lambda x: x[1], reverse=True)

    output_path = project_root / output_file
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("=" * 80 + "\n")
        f.write("REFACTORING PLAN FOR GMAILJOBTRACKET\n")
        f.write("=" * 80 + "\n\n")

        f.write(f"Found {len(large_files)} files over 500 lines:\n\n")
        for filepath, lines in large_files:
            rel_path = filepath.relative_to(project_root)
            f.write(f"  {rel_path}: {lines} lines\n")

        f.write("\n" + "=" * 80 + "\n")
        f.write("DETAILED RECOMMENDATIONS\n")
        f.write("=" * 80 + "\n\n")

        for filepath, lines in large_files:
            rel_path = filepath.relative_to(project_root)
            f.write(f"\n{'=' * 80}\n")
            f.write(f"FILE: {rel_path} ({lines} lines)\n")
            f.write(f"{'=' * 80}\n\n")

            try:
                stats = analyze_large_file(filepath)
                f.write(f"Functions: {stats['total_functions']}\n")
                f.write(f"Imports: {len(stats['imports'])}\n\n")

                f.write("Function Groups:\n")
                for group_name, funcs in sorted(stats["groups"].items()):
                    if funcs:
                        f.write(f"\n  {group_name} ({len(funcs)}):\n")
                        for func in sorted(funcs):
                            f.write(f"    - {func}\n")

                f.write("\n" + "-" * 80 + "\n")
            except Exception as e:
                f.write(f"Error analyzing: {e}\n")

    print(f"\n📄 Refactoring plan saved to: {output_file}")
    return output_path


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Suggest refactoring for large files")
    parser.add_argument("--file", help="Specific file to analyze (e.g., tracker/views.py)")
    parser.add_argument("--threshold", type=int, default=500, help="Line threshold for splitting")
    parser.add_argument("--plan", action="store_true", help="Generate full refactoring plan")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]

    if args.plan:
        generate_refactor_plan(project_root)
    elif args.file:
        filepath = project_root / args.file
        if filepath.exists():
            suggest_file_split(filepath, args.threshold)
        else:
            print(f"❌ File not found: {args.file}")
    else:
        # Default: analyze views.py
        views_file = project_root / "tracker" / "views.py"
        if views_file.exists():
            suggest_file_split(views_file, args.threshold)
        else:
            print("❌ tracker/views.py not found")


if __name__ == "__main__":
    main()
