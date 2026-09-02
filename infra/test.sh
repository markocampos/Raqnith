#!/usr/bin/env bash
# infra/test.sh - Comprehensive testing and QA pipeline

set -e

# Change to project root
cd "$(dirname "$0")/.."

echo "🚀 Starting Virtus QA Pipeline..."
echo "================================="

echo -e "\n🧹 [1/3] Running Linters & Formatters (Ruff)"
.venv/bin/ruff check --ignore E501 .
.venv/bin/ruff format --check .
echo "✅ Code is clean and formatted correctly."

echo -e "\n🛠️  [2/3] Checking Django Configuration"
.venv/bin/python manage.py check
echo "✅ Django checks passed."

echo -e "\n🧪 [3/3] Running Test Suite with Coverage"
# Run pytest with coverage for the local apps (excluding config/manage.py/etc)
.venv/bin/pytest --cov=apps --cov-report=term-missing -v
echo "✅ All tests passed successfully."

echo -e "\n🎉 Pipeline completed successfully!"
