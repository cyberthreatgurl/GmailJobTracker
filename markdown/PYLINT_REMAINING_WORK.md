# Pylint Remaining Work

**Generated**: November 6, 2025  
**After**: Phase 1 Automated Fixes (black, isort, autoflake)

## Summary

- **Total Errors**: 478 (down from 1000+)
- **Files with Errors**: 54
- **Automated Reduction**: ~52% of original errors resolved

## Error Breakdown by Priority

### 🔴 High Priority (Functional Issues)

#### 1. `reimported` (114 occurrences)
Duplicate imports in the same file. Most are in test files importing multiple fixtures/helpers.

**Action Required**: Manual review to consolidate or remove duplicates  
**Example**: `tracker/tests/conftest.py` - Multiple imports from same module  
**Fix**: Combine into single import statement

#### 2. `no-member` (13 occurrences)
False positives from Django QuerySet methods and dynamic attributes.

**Action Required**: Add `# pylint: disable=no-member` comments or update `.pylintrc` with `generated-members`  
**Example**: `Message.objects.filter()` flagged as undefined  
**Fix**: Already partially handled in `.pylintrc` with Django plugin

#### 3. `no-name-in-module` (3 occurrences)
Import errors for valid Django/external modules.

**Action Required**: Verify imports are correct; add to `.pylintrc` ignored-modules if needed  
**Fix**: Check if modules are installed in venv

### 🟡 Medium Priority (Code Quality)

#### 4. `missing-*-docstring` (179 total)
- `missing-module-docstring`: 48
- `missing-function-docstring`: 72
- `missing-class-docstring`: 59

**Action Required**: Add docstrings to public APIs  
**Strategy**: 
- Start with modules (top-level files)
- Add class docstrings for models, views, forms
- Add function docstrings for public functions (skip private/test helpers)

#### 5. `unused-variable` (34) & `unused-argument` (12)
Variables assigned but never used; function args never referenced.

**Action Required**: Remove or prefix with `_` (e.g., `_unused_var`)  
**Tool**: `autoflake --remove-unused-variables`

#### 6. `redefined-outer-name` (31)
Function parameters shadow outer scope variables (often fixtures in tests).

**Action Required**: Rename parameters or add `# pylint: disable=redefined-outer-name` in test files  
**Example**: Test function param `fake_stats` shadows conftest fixture

### 🟢 Low Priority (Style/Convention)

#### 7. `line-too-long` (21)
Lines exceeding 120 characters (mostly SQL queries, long f-strings).

**Action Required**: Black should handle most; manually break remaining long lines  
**Note**: .pylintrc already sets `max-line-length=120`

#### 8. `too-few-public-methods` (22)
Classes with <2 public methods (mostly Django models/forms).

**Action Required**: Add `# pylint: disable=too-few-public-methods` or suppress globally  
**Fix**: Already disabled in `.pylintrc` for common patterns

#### 9. `deprecated-module` (7)
Using deprecated Python modules (likely `imp` or `distutils`).

**Action Required**: Replace with modern equivalents (`importlib`, `packaging`)

#### 10. `unnecessary-lambda` (7)
Lambdas that just call another function directly.

**Action Required**: Replace `lambda x: func(x)` with `func`

## Automated Fix Commands

### Remove Unused Variables
```powershell
autoflake --remove-unused-variables --remove-all-unused-imports --in-place --recursive tracker/ *.py
```

### Fix Docstrings (Semi-Automated)
```powershell
# Generate docstring templates (requires pyment or similar)
pip install pyment
pyment -w -o numpydoc tracker/models.py
```

## Manual Review Checklist

- [ ] Consolidate reimported modules (114 instances)
- [ ] Add module docstrings to top 10 most-used files
- [ ] Review and remove unused variables in parser.py
- [ ] Fix or suppress Django-specific `no-member` warnings
- [ ] Rename test fixture parameter shadows
- [ ] Replace deprecated modules (imp, distutils)
- [ ] Simplify unnecessary lambdas

## Files Needing Most Attention

1. **parser.py** - 50+ errors (reimports, docstrings, complexity)
2. **tracker/tests/conftest.py** - 20+ reimported fixtures
3. **tracker/views.py** - Missing docstrings, long lines
4. **ml_subject_classifier.py** - Docstrings, unused variables
5. **train_model.py** - Module docstring, import order

## Next Steps

1. **Immediate**: Fix remaining autoflake-able issues (unused vars)
2. **Short-term**: Add module/class docstrings to public APIs
3. **Medium-term**: Manual review of reimports and test shadows
4. **Long-term**: Refactor high-complexity functions flagged by pylint

## Configuration Notes

`.pylintrc` already disables:
- `too-many-instance-attributes`
- `too-many-arguments`
- `too-many-locals`
- `too-many-branches`
- `too-many-statements`
- `duplicate-code`

Consider adding:
```ini
[TYPECHECK]
generated-members=objects,DoesNotExist,MultipleObjectsReturned

[MESSAGES CONTROL]
disable=...,
    too-few-public-methods,
    redefined-outer-name  # For test files only
```
