---
name: Code Refactoring
about: Major refactoring effort to improve code organization and maintainability
title: 'Refactor codebase for leaner, more efficient logic and processing'
labels: ['refactoring', 'technical-debt', 'enhancement']
assignees: ''
---

## Problem Statement

The current codebase has grown organically and contains several large monolithic files that are difficult to maintain, test, and extend. Many `.py` files exceed reasonable length limits and lack proper object-oriented structure.

## Goals

1. **Break down large files** into smaller, focused modules
2. **Introduce classes** where procedural code can benefit from encapsulation
3. **Improve code organization** with clear separation of concerns
4. **Enhance testability** through better modularity
5. **Reduce cognitive load** for developers working on the codebase

## Current Issues

### Large Monolithic Files

| File | Lines | Issues |
|------|-------|--------|
| `parser.py` | ~3,485 | Combines metadata extraction, classification, ingestion, and business logic |
| `tracker/views.py` | ~2,800+ | Multiple view functions with complex business logic mixed with presentation |
| `db_helpers.py` | Large | Database operations mixed with business logic |

### Specific Problems

- **Mixed Responsibilities**: Single files handling multiple concerns (parsing, classification, storage, validation)
- **Long Functions**: Functions exceeding 100+ lines that should be decomposed
- **Repeated Code**: Similar logic duplicated across functions
- **Hard to Test**: Tightly coupled code makes unit testing difficult
- **Hard to Extend**: Adding new features requires modifying large files
- **Poor Reusability**: Logic embedded in functions rather than reusable classes

## Proposed Refactoring Strategy

### Phase 1: parser.py Refactoring

**Current Structure** (3,485 lines):
```
parser.py
├── Global variables and patterns
├── extract_metadata() - 150+ lines
├── rule_label() - 200+ lines
├── predict_with_fallback() - 300+ lines
├── parse_subject() - 500+ lines
├── extract_status_dates() - 200+ lines
├── ingest_message() - 800+ lines
└── ingest_eml_file() - 400+ lines
```

**Proposed Structure**:
```
parser/
├── __init__.py
├── metadata.py           # MetadataExtractor class
├── classification.py     # MessageClassifier class
├── rules.py             # RuleEngine class
├── patterns.py          # PatternMatcher class
├── company.py           # CompanyResolver class
├── ingestion.py         # MessageIngester class
└── status_dates.py      # StatusDateExtractor class
```

**Classes to Create**:

1. **`MetadataExtractor`** - Extract metadata from Gmail API messages
   ```python
   class MetadataExtractor:
       def extract(self, service, msg_id) -> MessageMetadata
       def extract_from_eml(self, eml_content) -> MessageMetadata
   ```

2. **`MessageClassifier`** - Handle ML and rule-based classification
   ```python
   class MessageClassifier:
       def classify(self, subject, body, sender) -> ClassificationResult
       def apply_rules(self, text) -> Optional[str]
       def predict_ml(self, subject, body) -> MLPrediction
   ```

3. **`RuleEngine`** - Pattern matching and rule evaluation
   ```python
   class RuleEngine:
       def match_label(self, text) -> Optional[str]
       def check_exclusions(self, text, label) -> bool
       def apply_overrides(self, result, context) -> ClassificationResult
   ```

4. **`CompanyResolver`** - Company extraction and mapping
   ```python
   class CompanyResolver:
       def resolve(self, sender_domain, subject, body) -> Optional[Company]
       def map_by_domain(self, domain) -> Optional[str]
       def extract_from_subject(self, subject) -> Optional[str]
   ```

5. **`MessageIngester`** - Handle message storage and deduplication
   ```python
   class MessageIngester:
       def ingest(self, metadata, classification) -> IngestionResult
       def check_duplicates(self, msg_id, body_hash) -> bool
       def create_message(self, data) -> Message
   ```

### Phase 2: views.py Refactoring

**Current Issues**:
- View functions mixing business logic with presentation
- Complex filtering and pagination logic in views
- Data processing happening in view layer

**Proposed Structure**:
```
tracker/
├── views/
│   ├── __init__.py
│   ├── dashboard.py      # Dashboard views
│   ├── messages.py       # Message labeling views
│   ├── companies.py      # Company management views
│   └── analytics.py      # Analytics and reports
├── services/
│   ├── __init__.py
│   ├── message_service.py    # Message business logic
│   ├── company_service.py    # Company business logic
│   └── stats_service.py      # Statistics calculations
└── serializers/
    ├── __init__.py
    └── message_serializers.py
```

### Phase 3: Database Layer Refactoring

**Current Issues**:
- Database queries scattered throughout codebase
- Business logic mixed with data access
- No repository pattern

**Proposed Structure**:
```
tracker/
├── repositories/
│   ├── __init__.py
│   ├── message_repository.py
│   ├── company_repository.py
│   └── application_repository.py
└── queries/
    ├── __init__.py
    ├── message_queries.py
    └── analytics_queries.py
```

### Phase 4: Utility Refactoring

Break down monolithic utility files:
```
utils/
├── __init__.py
├── date_utils.py         # Date parsing and formatting
├── domain_utils.py       # Domain extraction and validation
├── text_utils.py         # Text cleaning and normalization
├── email_utils.py        # Email parsing utilities
└── hash_utils.py         # Body hashing and deduplication
```

## Implementation Plan

### Step 1: Create Module Structure ✅
- [ ] Create new directory structure
- [ ] Add `__init__.py` files with proper imports
- [ ] Set up base classes and interfaces

### Step 2: Extract Classes (Iterative)
- [ ] Extract `MetadataExtractor` from `parser.py`
- [ ] Extract `RuleEngine` from pattern matching code
- [ ] Extract `MessageClassifier` from prediction logic
- [ ] Extract `CompanyResolver` from company mapping
- [ ] Extract `MessageIngester` from ingestion logic

### Step 3: Migrate Functions
- [ ] Move functions to appropriate classes as methods
- [ ] Update function signatures to use class context
- [ ] Remove global state dependencies
- [ ] Add type hints to all methods

### Step 4: Update Imports
- [ ] Update all import statements across codebase
- [ ] Maintain backward compatibility with deprecated warnings
- [ ] Update tests to use new structure

### Step 5: Add Tests
- [ ] Unit tests for each class
- [ ] Integration tests for workflows
- [ ] Maintain existing test coverage

### Step 6: Documentation
- [ ] Document new class structures
- [ ] Update architecture diagrams
- [ ] Create migration guide for developers

## Success Criteria

- [ ] No single `.py` file exceeds 500 lines
- [ ] Each class has a single, well-defined responsibility
- [ ] Functions average < 50 lines
- [ ] Test coverage maintained or improved
- [ ] All existing functionality preserved
- [ ] Performance impact < 5%
- [ ] Code quality metrics improved:
  - Cyclomatic complexity reduced
  - Code duplication reduced
  - Maintainability index improved

## Benefits

1. **Maintainability**: Easier to locate and modify specific functionality
2. **Testability**: Smaller, focused classes are easier to unit test
3. **Reusability**: Classes can be imported and used in different contexts
4. **Extensibility**: New features can be added with minimal changes
5. **Onboarding**: New developers can understand isolated modules more easily
6. **Performance**: Opportunity to optimize specific components
7. **Debugging**: Smaller scope makes issues easier to isolate

## Migration Strategy

To avoid breaking changes:

1. **Create new structure alongside old code**
2. **Gradual migration** - one module at a time
3. **Deprecation warnings** for old imports
4. **Comprehensive testing** at each step
5. **Feature flags** for new vs old code paths
6. **Rollback plan** for each phase

## Risks and Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Breaking existing functionality | High | Comprehensive test suite, gradual migration |
| Performance regression | Medium | Benchmark critical paths, profile changes |
| Import confusion | Medium | Clear deprecation warnings, documentation |
| Increased complexity | Low | Good documentation, clear module boundaries |

## Timeline Estimate

- **Phase 1** (parser.py): 2-3 weeks
- **Phase 2** (views.py): 2-3 weeks  
- **Phase 3** (database layer): 1-2 weeks
- **Phase 4** (utilities): 1 week
- **Testing & Documentation**: 1-2 weeks

**Total**: 7-11 weeks (part-time development)

## References

- [PEP 8 - Style Guide for Python Code](https://pep8.org/)
- [Clean Code in Python](https://github.com/zedr/clean-code-python)
- [SOLID Principles](https://en.wikipedia.org/wiki/SOLID)
- [Martin Fowler - Refactoring](https://refactoring.com/)

## Related Issues

- #TBD - parser.py exceeds 3,000 lines
- #TBD - Improve test coverage for classification logic
- #TBD - Extract company resolution logic

---

**Priority**: High  
**Effort**: Large  
**Impact**: High
