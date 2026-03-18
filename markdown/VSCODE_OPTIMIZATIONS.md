# Code Citations

## License: unknown
https://github.com/coder/docs/blob/7828b49fe572212294519d5aee4f24587318ac51/guides/troubleshooting/inotify-watch-limits.md

```
Based on your settings and the Activity Monitor data (Code Helper Plugin at **54.4%**, Renderer at **25.2%**), here are the key culprits and what to change:

---

## Biggest Wins

### 1. Pylance type checking — likely #1 CPU driver
```json
"python.analysis.typeCheckingMode": "basic"   // currently "standard" — very expensive
```
`standard` mode does full type inference across your whole project constantly. Dropping to `basic` cuts CPU significantly with minimal practical impact.

### 2. Exclude heavy directories from Pylance analysis
You have `model/`, `__pycache__/`, `migrations/`, `imports/` (CSV files), and `debug/` that don't need analysis:
```json
"python.analysis.exclude": [
    "**/node_modules",
    "**/__pycache__",
    "**/migrations",
    "**/model",
    "**/imports",
    "**/staticfiles",
    "**/debug"
]
```

### 3. File watcher exclusions (feeds `logd` at 4.4% too)
```json
"files.watcherExclude": {
    "**/.git/objects/**": true,
    "**/.git/subtree-cache/**": true,
    "**/node_modules/**": true,
    "**/__
```


## License: unknown
https://github.com/coder/docs/blob/7828b49fe572212294519d5aee4f24587318ac51/guides/troubleshooting/inotify-watch-limits.md

```
Based on your settings and the Activity Monitor data (Code Helper Plugin at **54.4%**, Renderer at **25.2%**), here are the key culprits and what to change:

---

## Biggest Wins

### 1. Pylance type checking — likely #1 CPU driver
```json
"python.analysis.typeCheckingMode": "basic"   // currently "standard" — very expensive
```
`standard` mode does full type inference across your whole project constantly. Dropping to `basic` cuts CPU significantly with minimal practical impact.

### 2. Exclude heavy directories from Pylance analysis
You have `model/`, `__pycache__/`, `migrations/`, `imports/` (CSV files), and `debug/` that don't need analysis:
```json
"python.analysis.exclude": [
    "**/node_modules",
    "**/__pycache__",
    "**/migrations",
    "**/model",
    "**/imports",
    "**/staticfiles",
    "**/debug"
]
```

### 3. File watcher exclusions (feeds `logd` at 4.4% too)
```json
"files.watcherExclude": {
    "**/.git/objects/**": true,
    "**/.git/subtree-cache/**": true,
    "**/node_modules/**": true,
    "**/__
```


## License: unknown
https://github.com/coder/docs/blob/7828b49fe572212294519d5aee4f24587318ac51/guides/troubleshooting/inotify-watch-limits.md

```
Based on your settings and the Activity Monitor data (Code Helper Plugin at **54.4%**, Renderer at **25.2%**), here are the key culprits and what to change:

---

## Biggest Wins

### 1. Pylance type checking — likely #1 CPU driver
```json
"python.analysis.typeCheckingMode": "basic"   // currently "standard" — very expensive
```
`standard` mode does full type inference across your whole project constantly. Dropping to `basic` cuts CPU significantly with minimal practical impact.

### 2. Exclude heavy directories from Pylance analysis
You have `model/`, `__pycache__/`, `migrations/`, `imports/` (CSV files), and `debug/` that don't need analysis:
```json
"python.analysis.exclude": [
    "**/node_modules",
    "**/__pycache__",
    "**/migrations",
    "**/model",
    "**/imports",
    "**/staticfiles",
    "**/debug"
]
```

### 3. File watcher exclusions (feeds `logd` at 4.4% too)
```json
"files.watcherExclude": {
    "**/.git/objects/**": true,
    "**/.git/subtree-cache/**": true,
    "**/node_modules/**": true,
    "**/__
```


## License: unknown
https://github.com/coder/docs/blob/7828b49fe572212294519d5aee4f24587318ac51/guides/troubleshooting/inotify-watch-limits.md

```
Based on your settings and the Activity Monitor data (Code Helper Plugin at **54.4%**, Renderer at **25.2%**), here are the key culprits and what to change:

---

## Biggest Wins

### 1. Pylance type checking — likely #1 CPU driver
```json
"python.analysis.typeCheckingMode": "basic"   // currently "standard" — very expensive
```
`standard` mode does full type inference across your whole project constantly. Dropping to `basic` cuts CPU significantly with minimal practical impact.

### 2. Exclude heavy directories from Pylance analysis
You have `model/`, `__pycache__/`, `migrations/`, `imports/` (CSV files), and `debug/` that don't need analysis:
```json
"python.analysis.exclude": [
    "**/node_modules",
    "**/__pycache__",
    "**/migrations",
    "**/model",
    "**/imports",
    "**/staticfiles",
    "**/debug"
]
```

### 3. File watcher exclusions (feeds `logd` at 4.4% too)
```json
"files.watcherExclude": {
    "**/.git/objects/**": true,
    "**/.git/subtree-cache/**": true,
    "**/node_modules/**": true,
    "**/__
```


## License: unknown
https://github.com/coder/docs/blob/7828b49fe572212294519d5aee4f24587318ac51/guides/troubleshooting/inotify-watch-limits.md

```
Based on your settings and the Activity Monitor data (Code Helper Plugin at **54.4%**, Renderer at **25.2%**), here are the key culprits and what to change:

---

## Biggest Wins

### 1. Pylance type checking — likely #1 CPU driver
```json
"python.analysis.typeCheckingMode": "basic"   // currently "standard" — very expensive
```
`standard` mode does full type inference across your whole project constantly. Dropping to `basic` cuts CPU significantly with minimal practical impact.

### 2. Exclude heavy directories from Pylance analysis
You have `model/`, `__pycache__/`, `migrations/`, `imports/` (CSV files), and `debug/` that don't need analysis:
```json
"python.analysis.exclude": [
    "**/node_modules",
    "**/__pycache__",
    "**/migrations",
    "**/model",
    "**/imports",
    "**/staticfiles",
    "**/debug"
]
```

### 3. File watcher exclusions (feeds `logd` at 4.4% too)
```json
"files.watcherExclude": {
    "**/.git/objects/**": true,
    "**/.git/subtree-cache/**": true,
    "**/node_modules/**": true,
    "**/__
```


## License: unknown
https://github.com/coder/docs/blob/7828b49fe572212294519d5aee4f24587318ac51/guides/troubleshooting/inotify-watch-limits.md

```
Based on your settings and the Activity Monitor data (Code Helper Plugin at **54.4%**, Renderer at **25.2%**), here are the key culprits and what to change:

---

## Biggest Wins

### 1. Pylance type checking — likely #1 CPU driver
```json
"python.analysis.typeCheckingMode": "basic"   // currently "standard" — very expensive
```
`standard` mode does full type inference across your whole project constantly. Dropping to `basic` cuts CPU significantly with minimal practical impact.

### 2. Exclude heavy directories from Pylance analysis
You have `model/`, `__pycache__/`, `migrations/`, `imports/` (CSV files), and `debug/` that don't need analysis:
```json
"python.analysis.exclude": [
    "**/node_modules",
    "**/__pycache__",
    "**/migrations",
    "**/model",
    "**/imports",
    "**/staticfiles",
    "**/debug"
]
```

### 3. File watcher exclusions (feeds `logd` at 4.4% too)
```json
"files.watcherExclude": {
    "**/.git/objects/**": true,
    "**/.git/subtree-cache/**": true,
    "**/node_modules/**": true,
    "**/__
```


## License: unknown
https://github.com/coder/docs/blob/7828b49fe572212294519d5aee4f24587318ac51/guides/troubleshooting/inotify-watch-limits.md

```
Based on your settings and the Activity Monitor data (Code Helper Plugin at **54.4%**, Renderer at **25.2%**), here are the key culprits and what to change:

---

## Biggest Wins

### 1. Pylance type checking — likely #1 CPU driver
```json
"python.analysis.typeCheckingMode": "basic"   // currently "standard" — very expensive
```
`standard` mode does full type inference across your whole project constantly. Dropping to `basic` cuts CPU significantly with minimal practical impact.

### 2. Exclude heavy directories from Pylance analysis
You have `model/`, `__pycache__/`, `migrations/`, `imports/` (CSV files), and `debug/` that don't need analysis:
```json
"python.analysis.exclude": [
    "**/node_modules",
    "**/__pycache__",
    "**/migrations",
    "**/model",
    "**/imports",
    "**/staticfiles",
    "**/debug"
]
```

### 3. File watcher exclusions (feeds `logd` at 4.4% too)
```json
"files.watcherExclude": {
    "**/.git/objects/**": true,
    "**/.git/subtree-cache/**": true,
    "**/node_modules/**": true,
    "**/__
```

