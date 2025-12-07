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
 * Bot status polling
 */
function initBotStatus() {
    const statusElement = document.getElementById('botStatus');
    if (!statusElement) return;
    
    function updateStatus() {
        fetch('/api/bot/status')
            .then(response => response.json())
            .then(data => {
                const dot = statusElement.querySelector('.status-dot');
                const text = statusElement.querySelector('.status-text');
                
                if (data.is_running) {
                    statusElement.classList.add('online');
                    statusElement.classList.remove('offline');
                    text.textContent = 'Online';
                } else {
                    statusElement.classList.remove('online');
                    statusElement.classList.add('offline');
                    text.textContent = 'Offline';
                }
                
                // Update uptime in top bar
                const uptimeTopBar = document.getElementById('botUptimeTopBar');
                if (uptimeTopBar && data.uptime) {
                    uptimeTopBar.textContent = data.is_running ? '• ' + data.uptime : '';
                }
                
                // Update uptime in dashboard status card (if on dashboard page)
                const uptimeDashboard = document.getElementById('botUptime');
                if (uptimeDashboard && data.uptime) {
                    uptimeDashboard.textContent = data.uptime;
                }
                
                // Also update the dashboard status indicator if present
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
            })
            .catch(err => {
                console.error('Failed to fetch bot status:', err);
            });
    }
    
    // Initial update
    updateStatus();
    
    // Poll every 30 seconds
    setInterval(updateStatus, 30000);
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
