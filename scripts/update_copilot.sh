#!/usr/bin/env bash
set -euo pipefail

STAGE_DIR="update_copilot"

# Ensure staging directory exists (fresh each run)
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"

# Use git to list all tracked and untracked-but-not-ignored .py files
git ls-files --cached --others --exclude-standard '*.py' | while read -r file; do
  # Strip leading ./ if present
  rel_path="${file#./}"

  # Replace directory separators with dashes
  flat_name="${rel_path//\//-}.txt"

  # Destination is always in STAGE_DIR
  dest="$STAGE_DIR/$flat_name"

  # Copy the file
  cp "$file" "$dest"

  echo "Copied $file -> $dest"
done