/**
 * EngelGuard Dashboard - Main JavaScript
 */

document.addEventListener('DOMContentLoaded', function() {
    // Initialize components
    initSidebar();
    initBotStatus();
    initFlashMessages();
});

/**
 * Sidebar toggle for mobile
 */
function initSidebar() {
    const sidebar = document.getElementById('sidebar');
    const mobileMenuBtn = document.getElementById('mobileMenuBtn');
    
    if (mobileMenuBtn && sidebar) {
        // Create overlay
        const overlay = document.createElement('div');
        overlay.className = 'sidebar-overlay';
        document.body.appendChild(overlay);
        
        mobileMenuBtn.addEventListener('click', function() {
            sidebar.classList.toggle('open');
            overlay.classList.toggle('active');
        });
        
        overlay.addEventListener('click', function() {
            sidebar.classList.remove('open');
            overlay.classList.remove('active');
        });
    }
}

/**
 * Bot status with efficient uptime tracking
 * - Fetches from API once, then increments locally every second
 * - Re-syncs with server every 60 seconds
 */

// Global uptime tracking
let botUptimeSeconds = 0;
let botIsRunning = false;

function parseUptimeToSeconds(uptimeStr) {
    // Parse "1d 2h 30m" or "2h 30m 45s" to total seconds
    let seconds = 0;
    const days = uptimeStr.match(/(\d+)d/);
    const hours = uptimeStr.match(/(\d+)h/);
    const minutes = uptimeStr.match(/(\d+)m/);
    const secs = uptimeStr.match(/(\d+)s/);
    
    if (days) seconds += parseInt(days[1]) * 86400;
    if (hours) seconds += parseInt(hours[1]) * 3600;
    if (minutes) seconds += parseInt(minutes[1]) * 60;
    if (secs) seconds += parseInt(secs[1]);
    
    return seconds;
}

function formatSecondsToUptime(totalSeconds) {
    const days = Math.floor(totalSeconds / 86400);
    const hours = Math.floor((totalSeconds % 86400) / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    
    if (days > 0) {
        return `${days}d ${hours}h ${minutes}m ${seconds}s`;
    }
    return `${hours}h ${minutes}m ${seconds}s`;
}

function updateUptimeDisplay() {
    if (!botIsRunning) return;
    
    const uptimeStr = formatSecondsToUptime(botUptimeSeconds);
    
    // Update top bar uptime
    const uptimeTopBar = document.getElementById('botUptimeTopBar');
    if (uptimeTopBar) {
        uptimeTopBar.textContent = '• ' + uptimeStr;
    }
    
    // Update dashboard uptime
    const uptimeDashboard = document.getElementById('botUptime');
    if (uptimeDashboard) {
        uptimeDashboard.textContent = uptimeStr;
    }
}

function fetchBotStatus() {
    const statusElement = document.getElementById('botStatus');
    
    fetch('/api/bot/status')
        .then(response => response.json())
        .then(data => {
            botIsRunning = data.is_running;
            
            // Update status element
            if (statusElement) {
                const text = statusElement.querySelector('.status-text');
                if (data.is_running) {
                    statusElement.classList.add('online');
                    statusElement.classList.remove('offline');
                    if (text) text.textContent = 'Online';
                } else {
                    statusElement.classList.remove('online');
                    statusElement.classList.add('offline');
                    if (text) text.textContent = 'Offline';
                }
            }
            
            // Update dashboard status indicator
            const statusIndicator = document.querySelector('.status-indicator');
            if (statusIndicator) {
                if (data.is_running) {
                    statusIndicator.classList.add('online');
                    statusIndicator.classList.remove('offline');
                } else {
                    statusIndicator.classList.remove('online');
                    statusIndicator.classList.add('offline');
                }
                const statusLabel = statusIndicator.querySelector('.status-label');
                if (statusLabel) {
                    statusLabel.textContent = data.status;
                }
            }
            
            // Sync uptime from server
            if (data.uptime && data.uptime !== 'Unknown' && data.is_running) {
                botUptimeSeconds = parseUptimeToSeconds(data.uptime);
            } else if (!data.is_running) {
                botUptimeSeconds = 0;
                // Clear uptime displays when offline
                const uptimeTopBar = document.getElementById('botUptimeTopBar');
                if (uptimeTopBar) uptimeTopBar.textContent = '';
                const uptimeDashboard = document.getElementById('botUptime');
                if (uptimeDashboard) uptimeDashboard.textContent = 'Offline';
            }
            
            updateUptimeDisplay();
        })
        .catch(err => {
            console.error('Failed to fetch bot status:', err);
        });
}

function initBotStatus() {
    // Initial fetch from server
    fetchBotStatus();
    
    // Increment uptime locally every second (efficient - no API calls)
    setInterval(() => {
        if (botIsRunning) {
            botUptimeSeconds++;
            updateUptimeDisplay();
        }
    }, 1000);
    
    // Re-sync with server every 10 seconds to stay accurate
    setInterval(fetchBotStatus, 10000);
}

/**
 * Auto-dismiss flash messages
 */
function initFlashMessages() {
    const flashMessages = document.querySelectorAll('.flash-message');
    
    flashMessages.forEach(function(message) {
        // Auto-dismiss after 5 seconds
        setTimeout(function() {
            message.style.opacity = '0';
            message.style.transform = 'translateY(-10px)';
            setTimeout(function() {
                message.remove();
            }, 300);
        }, 5000);
    });
}

/**
 * Confirm action helper
 */
function confirmAction(message, callback) {
    if (confirm(message)) {
        callback();
    }
}

/**
 * Format date helper
 */
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleString();
}

/**
 * Copy to clipboard helper
 */
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(function() {
        alert('Copied to clipboard!');
    }).catch(function(err) {
        console.error('Failed to copy:', err);
    });
}
