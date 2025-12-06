#!/usr/bin/env python3
"""Batch-parse .eml fixtures by invoking the Django management command.

This avoids importing Django models directly from scripts and uses
`manage.py ingest_raw_eml --json` to get a machine-readable parse result.
"""

from pathlib import Path
import subprocess
import json
import time
import argparse

EMAIL_DIR = Path(__file__).resolve().parent.parent / 'tests' / 'email'

rows = []
counts = {
    'total': 0,
    'body_empty': 0,
    'rl_overrides_ml': 0,
    'final_differs_from_ml': 0,
    'rl_is_none': 0,
}

# Use the virtualenv python from the repo so Django settings are available
PYTHON = str(Path(__file__).resolve().parent.parent / '.venv' / 'Scripts' / 'python.exe')


def find_last_json(s: str):
    """Return the last balanced JSON object found in string `s`, or None."""
    starts = []
    objs = []
    for i, ch in enumerate(s):
        if ch == '{':
            starts.append(i)
        elif ch == '}' and starts:
            start = starts.pop()
            # If there are no more open braces, we've closed an outermost object
            if not starts:
                objs.append((start, i + 1))
    if not objs:
        return None
    # try the last object first
    start, end = objs[-1]
    candidate = s[start:end]
    try:
        return json.loads(candidate)
    except Exception:
        # fallback: try earlier objects
        for start, end in reversed(objs[:-1]):
            try:
                return json.loads(s[start:end])
            except Exception:
                continue
    return None


def run_manage_json(cmd, timeout_sec=15):
    """Run a management command and return parsed JSON or (None, stdout).

    Returns (json_obj, stdout_str). json_obj is None when parsing fails.
    """
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout_sec)
    except subprocess.TimeoutExpired as e:
        return None, f"TIMEOUT: {e}\nPartial stdout:\n{getattr(e, 'stdout', '')}\nPartial stderr:\n{getattr(e, 'stderr', '')}"
    if proc.returncode != 0:
        return None, proc.stdout + "\n" + proc.stderr
    out = proc.stdout
    # Try fast parse first
    try:
        return json.loads(out), out
    except Exception:
        # attempt to find the last balanced JSON object in output
        obj = find_last_json(out)
        return obj, out

parser = argparse.ArgumentParser()
parser.add_argument('--timeout', type=int, default=15, help='Per-management-command timeout (seconds)')
parser.add_argument('--batch-size', type=int, default=0, help='Process files in chunks of this size (0 = no chunking)')
args = parser.parse_args()

files = sorted(EMAIL_DIR.glob('*.eml'))
if args.batch_size and args.batch_size > 0:
    chunks = [files[i:i+args.batch_size] for i in range(0, len(files), args.batch_size)]
else:
    chunks = [files]

for chunk_idx, chunk in enumerate(chunks, start=1):
    if len(chunks) > 1:
        print(f"Processing chunk {chunk_idx}/{len(chunks)} ({len(chunk)} files)")
    for p in chunk:
        counts['total'] += 1
        start = time.time()
        cmd = [PYTHON, 'manage.py', 'ingest_raw_eml', '--file', str(p), '--json']
        json_obj, out = run_manage_json(cmd, timeout_sec=args.timeout)
        if json_obj is None:
            print(f"Failed to parse JSON from command for {p} (chunk {chunk_idx})")
            # print small tail for debugging
            print(out[-2000:])
            continue
        result = json_obj

        subject = result.get('subject', '')
        body_preview = result.get('body_preview', '')
        sender_domain = result.get('sender_domain', '')
        ml_label = result.get('ml_label')
        ml_conf = result.get('ml_confidence', 0.0)
        final_label = result.get('final_label')
        header_hints = result.get('header_hints', {})

        # Run show-body to capture rule debug output
        cmd2 = [PYTHON, 'manage.py', 'ingest_raw_eml', '--file', str(p), '--show-body']
        _, stdout = run_manage_json(cmd2, timeout_sec=args.timeout)

        rl = None
        # prefer final_label from JSON output (parser's effective label) when available
        if 'final_label' in result and result.get('final_label'):
            final_label = result.get('final_label')
        else:
            final_label = None
        if stdout:
            for line in stdout.splitlines():
                if 'rule_label result=' in line:
                    try:
                        rl = line.split('rule_label result=')[-1].strip()
                    except Exception:
                        rl = None
                    break
            # Fallback: if parser printed a Label: line use that only when JSON didn't include final_label
            if not final_label:
                for line in stdout.splitlines():
                    if line.startswith('Label:'):
                        parts = line.split('Label:')[-1].strip().split()
                        if parts:
                            final_label = parts[0].strip().strip(',')
                        break

        body_len = len(body_preview or '')
        body_empty = body_len == 0
        if body_empty:
            counts['body_empty'] += 1
        if rl is None:
            counts['rl_is_none'] += 1
        if rl and ml_label and rl != ml_label:
            counts['rl_overrides_ml'] += 1
        if final_label and ml_label and final_label != ml_label:
            counts['final_differs_from_ml'] += 1

        rows.append({
            'file': str(p.relative_to(Path.cwd())),
            'subject': subject[:120],
            'sender_domain': sender_domain,
            'ml_label': ml_label,
            'ml_conf': ml_conf,
            'rule_label': rl,
            'final_label': final_label,
            'body_len': body_len,
            'body_preview': body_preview.replace('\n','\\n'),
            'header_hints': header_hints,
        })
        elapsed = time.time() - start
        print(f"Processed {p.name} in {elapsed:.2f}s: ml={ml_label} rl={rl} final={final_label}")

# Print CSV-like header
print('file,ml_label,ml_conf,rule_label,final_label,body_len')
for r in rows:
    print(f"{r['file']},{r['ml_label']},{r['ml_conf']:.2f},{r['rule_label']},{r['final_label']},{r['body_len']}")

print('\nSUMMARY')
for k, v in counts.items():
    print(f"{k}: {v}")

# Also write a JSON report for easier inspection
out = Path('review_reports')
out.mkdir(exist_ok=True)
with open(out / 'batch_eml_parse_report.json', 'w', encoding='utf-8') as fh:
    json.dump({'rows': rows, 'summary': counts}, fh, indent=2, ensure_ascii=False)

print('\nWrote review_reports/batch_eml_parse_report.json')
