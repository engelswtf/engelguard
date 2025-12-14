#!/bin/bash
#
# EngelGuard Bot Live Simulation Runner
# 
# This script runs the comprehensive bot simulation that tests all features
# and outputs to Twitch chat.
#
# Usage: ./run_simulation.sh [--no-cleanup] [--fast]
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="/opt/twitch-bot/venv"
SIMULATION_SCRIPT="/opt/twitch-bot/tests/simulate_live_usage.py"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print banner
echo -e "${BLUE}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║         EngelGuard Bot Live Simulation                   ║"
echo "║                                                          ║"
echo "║  Tests ALL bot features with simulated users             ║"
echo "║  Output goes to Twitch chat for demonstration            ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check if running as root or twitchbot user
if [[ $EUID -ne 0 ]] && [[ "$(whoami)" != "twitchbot" ]]; then
    echo -e "${YELLOW}Warning: Running as $(whoami). Consider running as root or twitchbot.${NC}"
fi

# Check if virtual environment exists
if [[ ! -d "$VENV_PATH" ]]; then
    echo -e "${RED}Error: Virtual environment not found at $VENV_PATH${NC}"
    echo "Please ensure the bot is properly installed."
    exit 1
fi

# Check if simulation script exists
if [[ ! -f "$SIMULATION_SCRIPT" ]]; then
    echo -e "${RED}Error: Simulation script not found at $SIMULATION_SCRIPT${NC}"
    exit 1
fi

# Check if bot is running (optional warning)
if systemctl is-active --quiet twitch-bot 2>/dev/null; then
    echo -e "${GREEN}Bot service is running - messages will be sent to Twitch chat${NC}"
else
    echo -e "${YELLOW}Warning: Bot service is not running${NC}"
    echo -e "${YELLOW}Messages will be queued but not sent to Twitch until bot starts${NC}"
fi

# Check if dashboard is running
if systemctl is-active --quiet twitch-dashboard 2>/dev/null; then
    echo -e "${GREEN}Dashboard service is running - API calls will work${NC}"
else
    echo -e "${YELLOW}Warning: Dashboard service is not running${NC}"
    echo -e "${YELLOW}Some features may use fallback simulation mode${NC}"
fi

echo ""
echo -e "${BLUE}Starting simulation...${NC}"
echo "Press Ctrl+C to stop at any time"
echo ""

# Activate virtual environment and run simulation
cd /opt/twitch-bot
source "$VENV_PATH/bin/activate"

# Run the simulation
python "$SIMULATION_SCRIPT" "$@"

# Deactivate virtual environment
deactivate 2>/dev/null || true

echo ""
echo -e "${GREEN}Simulation complete!${NC}"
echo ""
echo "Check Twitch chat at: https://twitch.tv/ogengels"
echo "Dashboard at: http://10.10.10.101:5000"
