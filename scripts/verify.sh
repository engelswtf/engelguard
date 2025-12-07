#!/bin/bash
# ===========================================
# Twitch Bot Installation Verification Script
# ===========================================
# This script verifies the bot installation
# and checks for common issues
#
# Usage:
#   ./scripts/verify.sh
# ===========================================

set -u  # Exit on undefined variable

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
BOT_USER="twitchbot"
BOT_GROUP="twitchbot"
INSTALL_DIR="/opt/twitch-bot"
LOG_DIR="/var/log/twitch-bot"
SERVICE_NAME="twitch-bot"

CHECKS_PASSED=0
CHECKS_FAILED=0
CHECKS_WARNING=0

# ===========================================
# Helper Functions
# ===========================================

print_header() {
    echo ""
    echo "=========================================="
    echo "  $1"
    echo "=========================================="
    echo ""
}

print_check() {
    echo -n "Checking $1... "
}

print_pass() {
    echo -e "${GREEN}✓ PASS${NC}"
    ((CHECKS_PASSED++))
}

print_fail() {
    echo -e "${RED}✗ FAIL${NC}"
    if [[ -n "${1:-}" ]]; then
        echo -e "  ${RED}→${NC} $1"
    fi
    ((CHECKS_FAILED++))
}

print_warn() {
    echo -e "${YELLOW}⚠ WARNING${NC}"
    if [[ -n "${1:-}" ]]; then
        echo -e "  ${YELLOW}→${NC} $1"
    fi
    ((CHECKS_WARNING++))
}

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

# ===========================================
# Verification Checks
# ===========================================

check_user() {
    print_check "bot user exists"
    if id "$BOT_USER" &>/dev/null; then
        print_pass
    else
        print_fail "User '$BOT_USER' does not exist"
    fi
}

check_directories() {
    print_check "installation directory"
    if [[ -d "$INSTALL_DIR" ]]; then
        print_pass
    else
        print_fail "Directory $INSTALL_DIR does not exist"
    fi
    
    print_check "log directory"
    if [[ -d "$LOG_DIR" ]]; then
        print_pass
    else
        print_warn "Directory $LOG_DIR does not exist (optional)"
    fi
}

check_python() {
    print_check "Python version"
    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
        print_pass
        echo "  → Python $PYTHON_VERSION"
    else
        print_fail "Python 3 not found"
    fi
}

check_virtualenv() {
    print_check "virtual environment"
    if [[ -d "$INSTALL_DIR/venv" ]]; then
        if [[ -f "$INSTALL_DIR/venv/bin/python" ]]; then
            print_pass
            VENV_VERSION=$("$INSTALL_DIR/venv/bin/python" --version 2>&1 | cut -d' ' -f2)
            echo "  → venv Python $VENV_VERSION"
        else
            print_fail "Virtual environment is corrupted"
        fi
    else
        print_fail "Virtual environment not found at $INSTALL_DIR/venv"
    fi
}

check_dependencies() {
    print_check "Python dependencies"
    if [[ -f "$INSTALL_DIR/venv/bin/pip" ]]; then
        if "$INSTALL_DIR/venv/bin/pip" list 2>/dev/null | grep -q twitchio; then
            print_pass
            TWITCHIO_VERSION=$("$INSTALL_DIR/venv/bin/pip" show twitchio 2>/dev/null | grep Version | cut -d' ' -f2)
            echo "  → twitchio $TWITCHIO_VERSION"
        else
            print_fail "twitchio not installed in virtual environment"
        fi
    else
        print_fail "pip not found in virtual environment"
    fi
}

check_env_file() {
    print_check ".env file"
    if [[ -f "$INSTALL_DIR/.env" ]]; then
        print_pass
        
        # Check permissions
        print_check ".env permissions"
        PERMS=$(stat -c "%a" "$INSTALL_DIR/.env")
        if [[ "$PERMS" == "600" ]]; then
            print_pass
        else
            print_warn "Permissions are $PERMS (should be 600)"
        fi
        
        # Check for required variables
        print_check ".env configuration"
        MISSING_VARS=()
        
        source "$INSTALL_DIR/.env" 2>/dev/null || true
        
        [[ -z "${TWITCH_CLIENT_ID:-}" || "$TWITCH_CLIENT_ID" == "your_client_id_here" ]] && MISSING_VARS+=("TWITCH_CLIENT_ID")
        [[ -z "${TWITCH_CLIENT_SECRET:-}" || "$TWITCH_CLIENT_SECRET" == "your_client_secret_here" ]] && MISSING_VARS+=("TWITCH_CLIENT_SECRET")
        [[ -z "${TWITCH_OAUTH_TOKEN:-}" || "$TWITCH_OAUTH_TOKEN" == "oauth:your_token_here" ]] && MISSING_VARS+=("TWITCH_OAUTH_TOKEN")
        [[ -z "${TWITCH_BOT_NICK:-}" || "$TWITCH_BOT_NICK" == "your_bot_username" ]] && MISSING_VARS+=("TWITCH_BOT_NICK")
        [[ -z "${TWITCH_CHANNELS:-}" || "$TWITCH_CHANNELS" == "channel1,channel2" ]] && MISSING_VARS+=("TWITCH_CHANNELS")
        
        if [[ ${#MISSING_VARS[@]} -eq 0 ]]; then
            print_pass
        else
            print_fail "Missing or unconfigured: ${MISSING_VARS[*]}"
        fi
    else
        print_fail ".env file not found at $INSTALL_DIR/.env"
    fi
}

check_service_file() {
    print_check "systemd service file"
    if [[ -f "/etc/systemd/system/$SERVICE_NAME.service" ]]; then
        print_pass
    else
        print_fail "Service file not found at /etc/systemd/system/$SERVICE_NAME.service"
    fi
}

check_service_status() {
    print_check "service enabled"
    if systemctl is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
        print_pass
    else
        print_warn "Service is not enabled (won't start on boot)"
    fi
    
    print_check "service active"
    if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        print_pass
        
        # Show uptime
        UPTIME=$(systemctl show -p ActiveEnterTimestamp "$SERVICE_NAME" | cut -d'=' -f2)
        if [[ -n "$UPTIME" ]]; then
            echo "  → Running since: $UPTIME"
        fi
    else
        print_warn "Service is not running"
    fi
}

check_permissions() {
    print_check "file ownership"
    if [[ -d "$INSTALL_DIR" ]]; then
        OWNER=$(stat -c "%U:%G" "$INSTALL_DIR")
        if [[ "$OWNER" == "$BOT_USER:$BOT_GROUP" ]]; then
            print_pass
        else
            print_fail "Owned by $OWNER (should be $BOT_USER:$BOT_GROUP)"
        fi
    else
        print_fail "Installation directory not found"
    fi
}

check_network() {
    print_check "internet connectivity"
    if ping -c 1 -W 2 8.8.8.8 &>/dev/null; then
        print_pass
    else
        print_fail "No internet connectivity"
    fi
    
    print_check "Twitch API reachable"
    if curl -s --max-time 5 https://api.twitch.tv/helix &>/dev/null; then
        print_pass
    else
        print_warn "Cannot reach Twitch API (may be temporary)"
    fi
}

show_logs() {
    if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        echo ""
        print_info "Recent logs (last 10 lines):"
        echo "----------------------------------------"
        journalctl -u "$SERVICE_NAME" -n 10 --no-pager 2>/dev/null || echo "No logs available"
        echo "----------------------------------------"
    fi
}

# ===========================================
# Main Verification
# ===========================================

main() {
    print_header "Twitch Bot Installation Verification"
    
    print_info "Checking installation..."
    echo ""
    
    # Run all checks
    check_user
    check_directories
    check_python
    check_virtualenv
    check_dependencies
    check_env_file
    check_service_file
    check_service_status
    check_permissions
    check_network
    
    # Show logs if service is running
    show_logs
    
    # Summary
    echo ""
    print_header "Verification Summary"
    
    echo -e "${GREEN}Passed:${NC}   $CHECKS_PASSED"
    echo -e "${YELLOW}Warnings:${NC} $CHECKS_WARNING"
    echo -e "${RED}Failed:${NC}   $CHECKS_FAILED"
    echo ""
    
    if [[ $CHECKS_FAILED -eq 0 ]]; then
        if [[ $CHECKS_WARNING -eq 0 ]]; then
            echo -e "${GREEN}✓ All checks passed! Bot is ready.${NC}"
        else
            echo -e "${YELLOW}⚠ Some warnings detected. Review above.${NC}"
        fi
    else
        echo -e "${RED}✗ Some checks failed. Please fix the issues above.${NC}"
        echo ""
        echo "Common fixes:"
        echo "  - Run installation: sudo ./scripts/install.sh"
        echo "  - Configure .env: sudo nano /opt/twitch-bot/.env"
        echo "  - Fix permissions: sudo chown -R twitchbot:twitchbot /opt/twitch-bot"
        echo "  - Start service: sudo systemctl start twitch-bot"
    fi
    
    echo ""
    
    # Exit with appropriate code
    if [[ $CHECKS_FAILED -gt 0 ]]; then
        exit 1
    else
        exit 0
    fi
}

# Run main function
main "$@"
