#!/usr/bin/env python3
"""Calculate Source Lines of Code (SLOC) for all Python files in the repository.

SLOC counts non-blank, non-comment lines of code.
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple


def count_sloc(file_path: str) -> Tuple[int, int, int, int]:
    """Count lines in a Python file.
    
    Args:
        file_path: Path to the Python file
        
    Returns:
        Tuple of (total_lines, blank_lines, comment_lines, sloc)
    """
    total_lines = 0
    blank_lines = 0
    comment_lines = 0
    in_multiline_string = False
    multiline_delimiter = None
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                total_lines += 1
                stripped = line.strip()
                
                # Handle multiline strings (docstrings)
                if in_multiline_string:
                    if multiline_delimiter in line:
                        in_multiline_string = False
                        multiline_delimiter = None
                    comment_lines += 1
                    continue
                
                # Check for start of multiline string
                if '"""' in stripped or "'''" in stripped:
                    if '"""' in stripped:
                        delimiter = '"""'
                    else:
                        delimiter = "'''"
                    
                    # Count occurrences to determine if it's a single-line docstring
                    count = stripped.count(delimiter)
                    if count == 1:
                        in_multiline_string = True
                        multiline_delimiter = delimiter
                        comment_lines += 1
                        continue
                    elif count >= 2:
                        # Single line docstring
                        comment_lines += 1
                        continue
                
                # Check for blank lines
                if not stripped:
                    blank_lines += 1
                    continue
                
                # Check for comment lines (lines starting with #)
                if stripped.startswith('#'):
                    comment_lines += 1
                    continue
                
                # If we get here, it's a source line of code
                
    except Exception as e:
        print(f"Error reading {file_path}: {e}", file=sys.stderr)
        return 0, 0, 0, 0
    
    sloc = total_lines - blank_lines - comment_lines
    return total_lines, blank_lines, comment_lines, sloc


def find_python_files(root_dir: str) -> List[str]:
    """Find all Python files in the repository.
    
    Args:
        root_dir: Root directory to search
        
    Returns:
        List of paths to Python files
    """
    python_files = []
    root_path = Path(root_dir)
    
    for py_file in root_path.rglob('*.py'):
        python_files.append(str(py_file))
    
    return sorted(python_files)


def main():
    """Main function to calculate and display SLOC statistics."""
    # Get repository root directory
    repo_root = Path(__file__).parent
    
    print("=" * 80)
    print("SLOC Analysis for Python Files")
    print("=" * 80)
    print()
    
    # Find all Python files
    python_files = find_python_files(repo_root)
    
    if not python_files:
        print("No Python files found in the repository.")
        return
    
    print(f"Found {len(python_files)} Python files\n")
    
    # Calculate SLOC for each file
    file_stats: Dict[str, Tuple[int, int, int, int]] = {}
    total_lines = 0
    total_blank = 0
    total_comments = 0
    total_sloc = 0
    
    for file_path in python_files:
        lines, blank, comments, sloc = count_sloc(file_path)
        # Store relative path for better readability
        rel_path = os.path.relpath(file_path, repo_root)
        file_stats[rel_path] = (lines, blank, comments, sloc)
        
        total_lines += lines
        total_blank += blank
        total_comments += comments
        total_sloc += sloc
    
    # Display results
    print("-" * 80)
    print(f"{'File':<50} {'Total':>8} {'Blank':>8} {'Comment':>8} {'SLOC':>8}")
    print("-" * 80)
    
    for rel_path, (lines, blank, comments, sloc) in file_stats.items():
        print(f"{rel_path:<50} {lines:>8} {blank:>8} {comments:>8} {sloc:>8}")
    
    print("-" * 80)
    print(f"{'TOTAL':<50} {total_lines:>8} {total_blank:>8} "
          f"{total_comments:>8} {total_sloc:>8}")
    print("=" * 80)
    print()
    print(f"Summary:")
    print(f"  Total Python files: {len(python_files)}")
    print(f"  Total lines: {total_lines}")
    print(f"  Blank lines: {total_blank} ({total_blank/total_lines*100:.1f}%)")
    print(f"  Comment lines: {total_comments} ({total_comments/total_lines*100:.1f}%)")
    print(f"  Source Lines of Code (SLOC): {total_sloc} "
          f"({total_sloc/total_lines*100:.1f}%)")
    print()


if __name__ == "__main__":
    main()
