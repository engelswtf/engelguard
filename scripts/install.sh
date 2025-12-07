#!/bin/bash
# ===========================================
# Twitch Bot Installation Script
# ===========================================
# This script installs the Twitch bot as a systemd service
# on Proxmox LXC containers or VMs running Debian/Ubuntu
#
# Usage:
#   sudo ./scripts/install.sh
#
# Requirements:
#   - Debian/Ubuntu-based system
#   - Python 3.9 or higher
#   - systemd
#   - Root or sudo access
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
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

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

check_python() {
    if ! command -v python3 &> /dev/null; then
        print_error "Python 3 is not installed"
        exit 1
    fi
    
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
    PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d'.' -f1)
    PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d'.' -f2)
    
    # Require Python 3.9+
    if [[ "$PYTHON_MAJOR" -lt 3 ]] || [[ "$PYTHON_MAJOR" -eq 3 && "$PYTHON_MINOR" -lt 9 ]]; then
        print_error "Python 3.9 or higher is required (found $PYTHON_VERSION)"
        exit 1
    fi
    
    print_success "Python $PYTHON_VERSION detected"
}

check_systemd() {
    if ! command -v systemctl &> /dev/null; then
        print_error "systemd is not available on this system"
        exit 1
    fi
    print_success "systemd detected"
}

# ===========================================
# Installation Steps
# ===========================================

create_user() {
    print_info "Creating bot user and group..."
    
    if id "$BOT_USER" &>/dev/null; then
        print_warning "User '$BOT_USER' already exists, skipping creation"
    else
        # Create system user with no login shell and no home directory
        useradd --system --no-create-home --shell /usr/sbin/nologin "$BOT_USER"
        print_success "Created system user '$BOT_USER'"
    fi
}

create_directories() {
    print_info "Creating directories..."
    
    # Create installation directory
    mkdir -p "$INSTALL_DIR"
    mkdir -p "$INSTALL_DIR/data"
    
    # Create log directory
    mkdir -p "$LOG_DIR"
    
    print_success "Created directories"
}

install_dependencies() {
    print_info "Installing system dependencies..."
    
    # Update package list
    apt-get update -qq
    
    # Install required packages
    apt-get install -y -qq \
        python3-pip \
        python3-venv \
        python3-dev \
        build-essential \
        git
    
    print_success "System dependencies installed"
}

setup_virtualenv() {
    print_info "Setting up Python virtual environment..."
    
    # Create virtual environment
    python3 -m venv "$INSTALL_DIR/venv"
    
    # Upgrade pip
    "$INSTALL_DIR/venv/bin/pip" install --upgrade pip setuptools wheel -q
    
    print_success "Virtual environment created"
}

install_python_packages() {
    print_info "Installing Python dependencies..."
    
    # Install from requirements.txt
    if [[ -f "$PROJECT_DIR/requirements.txt" ]]; then
        "$INSTALL_DIR/venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt" -q
        print_success "Python dependencies installed"
    else
        print_error "requirements.txt not found in $PROJECT_DIR"
        exit 1
    fi
}

copy_files() {
    print_info "Copying bot files..."
    
    # Copy source files (using cp instead of rsync for compatibility)
    cp -r "$PROJECT_DIR/src" "$INSTALL_DIR/"
    cp -r "$PROJECT_DIR/tests" "$INSTALL_DIR/" 2>/dev/null || true
    cp "$PROJECT_DIR/run.py" "$INSTALL_DIR/"
    cp "$PROJECT_DIR/requirements.txt" "$INSTALL_DIR/"
    cp "$PROJECT_DIR/pyproject.toml" "$INSTALL_DIR/" 2>/dev/null || true
    cp "$PROJECT_DIR/README.md" "$INSTALL_DIR/" 2>/dev/null || true
    cp "$PROJECT_DIR/.gitignore" "$INSTALL_DIR/" 2>/dev/null || true
    
    # Clean up any pycache directories
    find "$INSTALL_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find "$INSTALL_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true
    
    print_success "Bot files copied"
}

setup_env_file() {
    print_info "Setting up environment file..."
    
    if [[ -f "$INSTALL_DIR/.env" ]]; then
        print_warning ".env file already exists, skipping creation"
        print_warning "Please review and update $INSTALL_DIR/.env manually"
    else
        if [[ -f "$PROJECT_DIR/.env" ]]; then
            # Copy existing .env from project
            cp "$PROJECT_DIR/.env" "$INSTALL_DIR/.env"
            print_success "Copied existing .env file"
        elif [[ -f "$PROJECT_DIR/.env.example" ]]; then
            # Copy example and warn user
            cp "$PROJECT_DIR/.env.example" "$INSTALL_DIR/.env"
            print_warning "Created .env from .env.example - YOU MUST EDIT THIS FILE!"
        else
            print_error "No .env or .env.example found"
            print_error "Please create $INSTALL_DIR/.env manually"
            exit 1
        fi
    fi
}

install_service() {
    print_info "Installing systemd service..."
    
    # Copy service file
    if [[ -f "$PROJECT_DIR/systemd/twitch-bot.service" ]]; then
        cp "$PROJECT_DIR/systemd/twitch-bot.service" "/etc/systemd/system/$SERVICE_NAME.service"
        
        # Reload systemd
        systemctl daemon-reload
        
        print_success "Systemd service installed"
    else
        print_error "Service file not found at $PROJECT_DIR/systemd/twitch-bot.service"
        exit 1
    fi
}

set_permissions() {
    print_info "Setting file permissions..."
    
    # Set ownership
    chown -R "$BOT_USER:$BOT_GROUP" "$INSTALL_DIR"
    chown -R "$BOT_USER:$BOT_GROUP" "$LOG_DIR"
    
    # Set directory permissions
    chmod 755 "$INSTALL_DIR"
    chmod 750 "$INSTALL_DIR/data"
    chmod 750 "$LOG_DIR"
    
    # Set .env permissions (readable only by bot user)
    chmod 600 "$INSTALL_DIR/.env"
    
    # Make run.py executable
    chmod 755 "$INSTALL_DIR/run.py"
    
    print_success "Permissions set"
}

# ===========================================
# Main Installation
# ===========================================

main() {
    echo ""
    echo "=========================================="
    echo "  Twitch Bot Installation"
    echo "=========================================="
    echo ""
    
    # Pre-flight checks
    check_root
    check_python
    check_systemd
    
    echo ""
    print_info "Starting installation..."
    echo ""
    
    # Installation steps
    create_user
    create_directories
    install_dependencies
    setup_virtualenv
    install_python_packages
    copy_files
    setup_env_file
    install_service
    set_permissions
    
    echo ""
    echo "=========================================="
    print_success "Installation Complete!"
    echo "=========================================="
    echo ""
    
    # Post-installation instructions
    print_info "Next steps:"
    echo ""
    echo "  1. Edit the configuration file:"
    echo "     ${YELLOW}sudo nano $INSTALL_DIR/.env${NC}"
    echo ""
    echo "  2. Verify the configuration:"
    echo "     ${YELLOW}sudo cat $INSTALL_DIR/.env${NC}"
    echo ""
    echo "  3. Enable the service to start on boot:"
    echo "     ${YELLOW}sudo systemctl enable $SERVICE_NAME${NC}"
    echo ""
    echo "  4. Start the service:"
    echo "     ${YELLOW}sudo systemctl start $SERVICE_NAME${NC}"
    echo ""
    echo "  5. Check the service status:"
    echo "     ${YELLOW}sudo systemctl status $SERVICE_NAME${NC}"
    echo ""
    echo "  6. View logs:"
    echo "     ${YELLOW}sudo journalctl -u $SERVICE_NAME -f${NC}"
    echo ""
    
    print_warning "IMPORTANT: You MUST edit $INSTALL_DIR/.env before starting the bot!"
    echo ""
}

# Run main function
main "$@"
