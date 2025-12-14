#!/bin/bash
#
# EngelGuard Test Runner
# 
# Usage: ./run_tests.sh [options]
#   -v, --verbose    Show detailed output
#   -k, --keep       Keep test data after running (don't cleanup)
#   -h, --help       Show this help message
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_SCRIPT="$SCRIPT_DIR/tests/test_dashboard_features.py"
VENV_PATH="$SCRIPT_DIR/venv"

# Parse arguments
VERBOSE=""
NO_CLEANUP=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -v|--verbose)
            VERBOSE="--verbose"
            shift
            ;;
        -k|--keep)
            NO_CLEANUP="--no-cleanup"
            shift
            ;;
        -h|--help)
            echo "EngelGuard Test Runner"
            echo ""
            echo "Usage: ./run_tests.sh [options]"
            echo ""
            echo "Options:"
            echo "  -v, --verbose    Show detailed output"
            echo "  -k, --keep       Keep test data after running"
            echo "  -h, --help       Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Check if test script exists
if [ ! -f "$TEST_SCRIPT" ]; then
    echo -e "${RED}Error: Test script not found at $TEST_SCRIPT${NC}"
    exit 1
fi

# Check if venv exists
if [ ! -d "$VENV_PATH" ]; then
    echo -e "${YELLOW}Warning: Virtual environment not found at $VENV_PATH${NC}"
    echo "Using system Python..."
    PYTHON="python3"
else
    PYTHON="$VENV_PATH/bin/python"
fi

# Check if requests is installed
if ! $PYTHON -c "import requests" 2>/dev/null; then
    echo -e "${YELLOW}Installing requests library...${NC}"
    $PYTHON -m pip install requests --quiet
fi

# Check if dashboard is running
echo -e "${YELLOW}Checking dashboard status...${NC}"
if curl -s -o /dev/null -w "%{http_code}" http://10.10.10.101:5000/login | grep -q "200"; then
    echo -e "${GREEN}Dashboard is running${NC}"
else
    echo -e "${RED}Warning: Dashboard may not be running!${NC}"
    echo "Attempting to start dashboard..."
    systemctl start twitch-dashboard 2>/dev/null || true
    sleep 2
fi

# Run tests
echo ""
echo -e "${GREEN}Running EngelGuard Test Suite...${NC}"
echo ""

$PYTHON "$TEST_SCRIPT" $VERBOSE $NO_CLEANUP

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
else
    echo -e "${RED}Some tests failed.${NC}"
fi

exit $EXIT_CODE
