#!/bin/bash
# ===========================================
# Twitch Bot Update Script
# ===========================================
# This script updates the Twitch bot to the latest version
# and restarts the service
#
# Usage:
#   sudo ./scripts/update.sh [--no-restart] [--from-git]
#
# Options:
#   --no-restart   Don't restart the service after update
#   --from-git     Pull updates from git repository
#   --from-local   Copy files from local directory (default)
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
SERVICE_NAME="twitch-bot"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
RESTART=true
UPDATE_METHOD="local"

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

check_installation() {
    if [[ ! -d "$INSTALL_DIR" ]]; then
        print_error "Bot is not installed at $INSTALL_DIR"
        print_error "Please run install.sh first"
        exit 1
    fi
}

# ===========================================
# Update Steps
# ===========================================

backup_current() {
    print_info "Creating backup..."
    
    local backup_dir="/tmp/twitch-bot-backup-$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$backup_dir"
    
    # Backup current installation (excluding venv and data)
    rsync -a --exclude='venv' \
             --exclude='data' \
             --exclude='__pycache__' \
             --exclude='*.pyc' \
             "$INSTALL_DIR/" "$backup_dir/"
    
    print_success "Backup created at $backup_dir"
    echo "$backup_dir" > /tmp/twitch-bot-last-backup
}

stop_service() {
    print_info "Stopping service..."
    
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        systemctl stop "$SERVICE_NAME"
        print_success "Service stopped"
    else
        print_warning "Service is not running"
    fi
}

update_from_git() {
    print_info "Pulling latest changes from git..."
    
    if [[ ! -d "$INSTALL_DIR/.git" ]]; then
        print_error "Not a git repository. Use --from-local instead"
        exit 1
    fi
    
    cd "$INSTALL_DIR"
    
    # Stash any local changes
    if ! git diff-index --quiet HEAD --; then
        print_warning "Local changes detected, stashing..."
        sudo -u "$BOT_USER" git stash
    fi
    
    # Pull latest changes
    sudo -u "$BOT_USER" git pull
    
    print_success "Git repository updated"
}

update_from_local() {
    print_info "Copying files from $PROJECT_DIR..."
    
    # Copy source files (preserve .env and data)
    rsync -a --exclude='venv' \
             --exclude='__pycache__' \
             --exclude='*.pyc' \
             --exclude='.git' \
             --exclude='.env' \
             --exclude='data' \
             --exclude='systemd' \
             --exclude='scripts' \
             "$PROJECT_DIR/" "$INSTALL_DIR/"
    
    print_success "Files updated"
}

update_dependencies() {
    print_info "Updating Python dependencies..."
    
    if [[ -f "$INSTALL_DIR/requirements.txt" ]]; then
        # Upgrade pip first
        "$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q
        
        # Update dependencies
        "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" --upgrade -q
        
        print_success "Dependencies updated"
    else
        print_warning "requirements.txt not found, skipping dependency update"
    fi
}

update_service_file() {
    print_info "Checking for service file updates..."
    
    local source_service="$PROJECT_DIR/systemd/twitch-bot.service"
    local installed_service="/etc/systemd/system/$SERVICE_NAME.service"
    
    if [[ -f "$source_service" ]]; then
        if ! cmp -s "$source_service" "$installed_service"; then
            print_info "Service file has changed, updating..."
            cp "$source_service" "$installed_service"
            systemctl daemon-reload
            print_success "Service file updated"
        else
            print_info "Service file unchanged"
        fi
    fi
}

set_permissions() {
    print_info "Setting file permissions..."
    
    # Set ownership (preserve .env permissions)
    chown -R "$BOT_USER:$BOT_GROUP" "$INSTALL_DIR"
    
    # Make run.py executable
    chmod 755 "$INSTALL_DIR/run.py"
    
    # Ensure .env is secure
    if [[ -f "$INSTALL_DIR/.env" ]]; then
        chmod 600 "$INSTALL_DIR/.env"
    fi
    
    print_success "Permissions set"
}

start_service() {
    if [[ "$RESTART" == true ]]; then
        print_info "Starting service..."
        
        systemctl start "$SERVICE_NAME"
        
        # Wait a moment for service to start
        sleep 2
        
        if systemctl is-active --quiet "$SERVICE_NAME"; then
            print_success "Service started successfully"
        else
            print_error "Service failed to start"
            print_error "Check logs with: journalctl -u $SERVICE_NAME -n 50"
            exit 1
        fi
    else
        print_info "Skipping service restart (use --no-restart flag)"
    fi
}

verify_update() {
    print_info "Verifying update..."
    
    # Check if service is running
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        print_success "Service is running"
        
        # Show recent logs
        echo ""
        print_info "Recent logs:"
        journalctl -u "$SERVICE_NAME" -n 10 --no-pager
    else
        print_warning "Service is not running"
    fi
}

rollback() {
    print_error "Update failed! Rolling back..."
    
    if [[ -f /tmp/twitch-bot-last-backup ]]; then
        local backup_dir=$(cat /tmp/twitch-bot-last-backup)
        
        if [[ -d "$backup_dir" ]]; then
            print_info "Restoring from $backup_dir..."
            
            rsync -a --exclude='venv' \
                     --exclude='data' \
                     --exclude='.env' \
                     "$backup_dir/" "$INSTALL_DIR/"
            
            set_permissions
            
            if [[ "$RESTART" == true ]]; then
                systemctl start "$SERVICE_NAME"
            fi
            
            print_success "Rollback complete"
        fi
    else
        print_error "No backup found for rollback"
    fi
}

# ===========================================
# Main Update
# ===========================================

parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --no-restart)
                RESTART=false
                shift
                ;;
            --from-git)
                UPDATE_METHOD="git"
                shift
                ;;
            --from-local)
                UPDATE_METHOD="local"
                shift
                ;;
            -h|--help)
                echo "Usage: $0 [OPTIONS]"
                echo ""
                echo "Options:"
                echo "  --no-restart   Don't restart the service after update"
                echo "  --from-git     Pull updates from git repository"
                echo "  --from-local   Copy files from local directory (default)"
                echo "  -h, --help     Show this help message"
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
    echo "  Twitch Bot Update"
    echo "=========================================="
    echo ""
    
    # Pre-flight checks
    check_root
    check_installation
    
    print_info "Update method: $UPDATE_METHOD"
    echo ""
    
    # Set up error handling for rollback
    trap rollback ERR
    
    # Update steps
    backup_current
    stop_service
    
    if [[ "$UPDATE_METHOD" == "git" ]]; then
        update_from_git
    else
        update_from_local
    fi
    
    update_dependencies
    update_service_file
    set_permissions
    start_service
    
    # Remove error trap
    trap - ERR
    
    echo ""
    echo "=========================================="
    print_success "Update Complete!"
    echo "=========================================="
    echo ""
    
    verify_update
    
    echo ""
    print_info "Useful commands:"
    echo "  Status:  ${YELLOW}sudo systemctl status $SERVICE_NAME${NC}"
    echo "  Logs:    ${YELLOW}sudo journalctl -u $SERVICE_NAME -f${NC}"
    echo "  Restart: ${YELLOW}sudo systemctl restart $SERVICE_NAME${NC}"
    echo ""
}

# Run main function
main "$@"
