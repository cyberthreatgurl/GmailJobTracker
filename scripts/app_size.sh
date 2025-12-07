# Check your application size
du -sh .
du -sh * | sort -h

# Identify large dependencies
pip list --format=freeze | while read pkg; do
    pkg_name=$(echo $pkg | cut -d'=' -f1)
    pip show $pkg_name | grep -E "Name|Version|Location"
    du -sh $(pip show $pkg_name | grep Location | cut -d' ' -f2)/$pkg_name 2>/dev/null
done | sort -h

# Check for unused imports
pip install vulture
vulture . --min-confidence 80

# Find dead code
pip install pyflakes
pyflakes .

# Check code complexity
pip install radon
radon cc . -a -nb

# Analyze dependencies
pip install pipdeptree
pipdeptree