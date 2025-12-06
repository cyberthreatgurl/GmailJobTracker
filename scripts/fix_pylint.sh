#!/usr/bin/env bash
# Quick-start script to fix pylint errors in phases

set -e

PHASE="${1:-summary}"
DRY_RUN="${2:-}"

# Colors
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
RED='\033[0;31m'
WHITE='\033[1;37m'
GRAY='\033[0;37m'
NC='\033[0m' # No Color

echo -e "${CYAN}======================================================================"
echo -e "🔧 GmailJobTracker Pylint Error Fixer"
echo -e "======================================================================${NC}"

check_package() {
    python -c "import $1" 2>/dev/null
}

install_tools() {
    echo -e "\n${YELLOW}📦 Checking required tools...${NC}"
    
    local missing=()
    
    for tool in isort autoflake black pylint; do
        if check_package "$tool"; then
            echo -e "  ${GREEN}✓ $tool installed${NC}"
        else
            echo -e "  ${RED}✗ $tool missing${NC}"
            missing+=("$tool")
        fi
    done
    
    if [ ${#missing[@]} -gt 0 ]; then
        echo -e "\n${YELLOW}⚠️  Missing packages: ${missing[*]}${NC}"
        read -p "Install missing packages? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo -e "${YELLOW}Installing...${NC}"
            pip install "${missing[@]}"
        else
            echo -e "${RED}❌ Cannot proceed without required tools${NC}"
            exit 1
        fi
    fi
}

show_summary() {
    echo -e "\n${CYAN}📊 Current Pylint Error Summary${NC}"
    python scripts/fix_pylint_errors.py --category summary
}

run_phase1() {
    local dry_run=$1
    
    echo -e "\n${CYAN}🚀 PHASE 1: Automated Fixes${NC}"
    echo -e "${CYAN}======================================================================${NC}"
    
    # Step 1: Format with Black
    echo -e "\n${YELLOW}1️⃣ Running Black formatter...${NC}"
    if [ "$dry_run" = "true" ]; then
        black . --line-length 120 --skip-string-normalization --check --diff
    else
        black . --line-length 120 --skip-string-normalization
        echo -e "  ${GREEN}✓ Code formatted${NC}"
    fi
    
    # Step 2: Fix import order with isort
    echo -e "\n${YELLOW}2️⃣ Fixing import order with isort...${NC}"
    if [ "$dry_run" = "true" ]; then
        isort . --profile black --line-length 100 --check-only --diff
    else
        isort . --profile black --line-length 100
        echo -e "  ${GREEN}✓ Imports sorted${NC}"
    fi
    
    # Step 3: Remove unused imports
    echo -e "\n${YELLOW}3️⃣ Removing unused imports with autoflake...${NC}"
    if [ "$dry_run" = "true" ]; then
        autoflake --remove-all-unused-imports --recursive .
    else
        autoflake --remove-all-unused-imports --in-place --recursive .
        echo -e "  ${GREEN}✓ Unused imports removed${NC}"
    fi
    
    # Step 4: Fix formatting issues
    echo -e "\n${YELLOW}4️⃣ Fixing trailing whitespace and newlines...${NC}"
    if [ "$dry_run" = "true" ]; then
        python scripts/fix_pylint_errors.py --category formatting --dry-run
    else
        python scripts/fix_pylint_errors.py --category formatting
    fi
    
    # Step 5: Add module docstrings
    echo -e "\n${YELLOW}5️⃣ Adding module docstrings...${NC}"
    if [ "$dry_run" = "true" ]; then
        python scripts/fix_pylint_errors.py --category docstrings --dry-run
    else
        python scripts/fix_pylint_errors.py --category docstrings
    fi
    
    echo -e "\n${GREEN}✅ Phase 1 Complete!${NC}"
    
    if [ "$dry_run" != "true" ]; then
        echo -e "\n${YELLOW}📊 Generating new pylint report...${NC}"
        pylint . --output-format=json > scripts/debug/pylint_after_phase1.json
        
        echo -e "\n${CYAN}📈 Improvement Summary:${NC}"
        python scripts/fix_pylint_errors.py --report scripts/debug/pylint_after_phase1.json --category summary
    fi
}

run_phase2() {
    echo -e "\n${CYAN}🚀 PHASE 2: Critical Manual Fixes${NC}"
    echo -e "${CYAN}======================================================================${NC}"
    
    echo -e "\n${YELLOW}Phase 2 requires manual intervention. See PYLINT_FIXING_STRATEGY.md${NC}"
    echo -e "\n${YELLOW}Key tasks:${NC}"
    echo -e "  ${WHITE}1. Fix import errors (15 errors)${NC}"
    echo -e "     ${GRAY}- Rename parser.py to email_parser.py if needed${NC}"
    echo -e "     ${GRAY}- Fix circular imports${NC}"
    echo -e "  ${WHITE}2. Replace broad exceptions (30 errors)${NC}"
    echo -e "     ${GRAY}- Use specific exception types${NC}"
    echo -e "  ${WHITE}3. Fix redefined outer names (9 errors)${NC}"
    echo -e "  ${WHITE}4. Add function docstrings (27 errors)${NC}"
    
    echo -e "\n${CYAN}See markdown/PYLINT_FIXING_STRATEGY.md for detailed instructions${NC}"
}

main() {
    # Check if we're in the right directory
    if [ ! -f "manage.py" ]; then
        echo -e "${RED}❌ Must be run from GmailJobTracker root directory${NC}"
        exit 1
    fi
    
    local dry_run=false
    if [ "$DRY_RUN" = "--dry-run" ]; then
        dry_run=true
    fi
    
    case "$PHASE" in
        summary)
            show_summary
            ;;
        phase1)
            install_tools
            run_phase1 "$dry_run"
            ;;
        phase2)
            run_phase2
            ;;
        all)
            install_tools
            run_phase1 "$dry_run"
            if [ "$dry_run" != "true" ]; then
                run_phase2
            fi
            ;;
        *)
            echo -e "${RED}Invalid phase: $PHASE${NC}"
            echo "Usage: $0 [summary|phase1|phase2|all] [--dry-run]"
            exit 1
            ;;
    esac
    
    if [ "$dry_run" = "true" ]; then
        echo -e "\n${CYAN}💡 This was a dry run. Run without --dry-run to apply changes.${NC}"
    else
        echo -e "\n${CYAN}💡 Next steps:${NC}"
        echo -e "  ${WHITE}1. Review the changes: git diff${NC}"
        echo -e "  ${WHITE}2. Test the application: pytest${NC}"
        echo -e "  ${WHITE}3. Run Django tests: python manage.py test${NC}"
        echo -e "  ${WHITE}4. Commit changes: git add . && git commit -m 'fix: automated pylint fixes'${NC}"
    fi
}

main
