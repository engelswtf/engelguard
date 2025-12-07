#!/bin/bash
# ===========================================
# Twitch Bot Uninstallation Script
# ===========================================
# This script removes the Twitch bot systemd service
# and optionally removes all bot files and user
#
# Usage:
#   sudo ./scripts/uninstall.sh [--purge]
#
# Options:
#   --purge    Remove all files, logs, and user account
#              (default: keep files and user, only remove service)
# ===========================================

set -e  # Exit on error
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
PURGE=false

# ===========================================
# Helper Functions
# ===========================================

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        print_error "This script must be run as root or with sudo"
        exit 1
    fi
}

confirm_action() {
    local message="$1"
    local response
    
    echo -e "${YELLOW}$message${NC}"
    read -p "Are you sure? (yes/no): " response
    
    if [[ "$response" != "yes" ]]; then
        print_info "Operation cancelled"
        exit 0
    fi
}

# ===========================================
# Uninstallation Steps
# ===========================================

stop_service() {
    print_info "Stopping service..."
    
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        systemctl stop "$SERVICE_NAME"
        print_success "Service stopped"
    else
        print_warning "Service is not running"
    fi
}

disable_service() {
    print_info "Disabling service..."
    
    if systemctl is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
        systemctl disable "$SERVICE_NAME"
        print_success "Service disabled"
    else
        print_warning "Service is not enabled"
    fi
}

remove_service_file() {
    print_info "Removing service file..."
    
    if [[ -f "/etc/systemd/system/$SERVICE_NAME.service" ]]; then
        rm -f "/etc/systemd/system/$SERVICE_NAME.service"
        systemctl daemon-reload
        systemctl reset-failed
        print_success "Service file removed"
    else
        print_warning "Service file not found"
    fi
}

backup_env_file() {
    if [[ -f "$INSTALL_DIR/.env" ]]; then
        local backup_file="/root/twitch-bot.env.backup.$(date +%Y%m%d_%H%M%S)"
        print_info "Backing up .env file to $backup_file"
        cp "$INSTALL_DIR/.env" "$backup_file"
        chmod 600 "$backup_file"
        print_success "Configuration backed up"
    fi
}

remove_files() {
    if [[ "$PURGE" == true ]]; then
        print_info "Removing bot files..."
        
        # Backup .env before removing
        backup_env_file
        
        if [[ -d "$INSTALL_DIR" ]]; then
            rm -rf "$INSTALL_DIR"
            print_success "Bot files removed from $INSTALL_DIR"
        else
            print_warning "Installation directory not found"
        fi
        
        if [[ -d "$LOG_DIR" ]]; then
            rm -rf "$LOG_DIR"
            print_success "Log files removed from $LOG_DIR"
        else
            print_warning "Log directory not found"
        fi
    else
        print_info "Keeping bot files (use --purge to remove)"
    fi
}

remove_user() {
    if [[ "$PURGE" == true ]]; then
        print_info "Removing bot user..."
        
        if id "$BOT_USER" &>/dev/null; then
            userdel "$BOT_USER" 2>/dev/null || true
            print_success "User '$BOT_USER' removed"
        else
            print_warning "User '$BOT_USER' not found"
        fi
    else
        print_info "Keeping bot user (use --purge to remove)"
    fi
}

# ===========================================
# Main Uninstallation
# ===========================================

parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --purge)
                PURGE=true
                shift
                ;;
            -h|--help)
                echo "Usage: $0 [--purge]"
                echo ""
                echo "Options:"
                echo "  --purge    Remove all files, logs, and user account"
                echo "  -h, --help Show this help message"
                exit 0
                ;;
            *)
                print_error "Unknown option: $1"
                echo "Use --help for usage information"
                exit 1
                ;;
        esac
    done
}

main() {
    parse_args "$@"
    
    echo ""
    echo "=========================================="
    echo "  Twitch Bot Uninstallation"
    echo "=========================================="
    echo ""
    
    # Pre-flight checks
    check_root
    
    # Confirm action
    if [[ "$PURGE" == true ]]; then
        confirm_action "This will COMPLETELY REMOVE the bot, including all files and logs!"
    else
        confirm_action "This will remove the systemd service but keep bot files."
    fi
    
    echo ""
    print_info "Starting uninstallation..."
    echo ""
    
    # Uninstallation steps
    stop_service
    disable_service
    remove_service_file
    remove_files
    remove_user
    
    echo ""
    echo "=========================================="
    print_success "Uninstallation Complete!"
    echo "=========================================="
    echo ""
    
    if [[ "$PURGE" == true ]]; then
        print_info "The bot has been completely removed from your system"
        if [[ -f /root/twitch-bot.env.backup.* ]]; then
            echo ""
            print_info "Your .env configuration was backed up to:"
            ls -1 /root/twitch-bot.env.backup.* 2>/dev/null | tail -1
        fi
    else
        print_info "The service has been removed, but files remain at:"
        echo "  - $INSTALL_DIR"
        echo "  - $LOG_DIR"
        echo ""
        print_info "To completely remove all files, run:"
        echo "  ${YELLOW}sudo $0 --purge${NC}"
    fi
    
    echo ""
}

# Run main function
main "$@"
