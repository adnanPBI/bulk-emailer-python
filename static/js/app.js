// Modern Email Platform - JavaScript
const API_BASE = '/api';

// Utility Functions
function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    toast.style.cssText = `
        position: fixed;
        top: 2rem;
        right: 2rem;
        padding: 1rem 1.5rem;
        background: ${type === 'success' ? '#10B981' : '#EF4444'};
        color: white;
        border-radius: 0.75rem;
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3);
        z-index: 9999;
        animation: slideInRight 0.3s ease-out;
    `;
    document.body.appendChild(toast);
    setTimeout(() => {
        toast.style.animation = 'slideOutRight 0.3s ease-out';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

function formatDate(date) {
    return new Date(date).toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

// API Functions
async function apiRequest(endpoint, options = {}) {
    try {
        const response = await fetch(`${API_BASE}${endpoint}`, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        return await response.json();
    } catch (error) {
        console.error('API Error:', error);
        showToast('An error occurred. Please try again.', 'error');
        throw error;
    }
}

// Dashboard Functions
async function loadStats() {
    const stats = await apiRequest('/stats');
    document.getElementById('totalCampaigns').textContent = stats.total_campaigns || 0;
    document.getElementById('totalSent').textContent = stats.total_sent || 0;
    document.getElementById('deliveryRate').textContent = `${stats.delivery_rate || 0}%`;
}

async function loadCampaigns() {
    const campaigns = await apiRequest('/campaigns');
    const tbody = document.getElementById('campaignsTable');

    if (campaigns.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="6" style="text-align: center; padding: 3rem;">
                    <div class="empty-state">
                        <div class="empty-state-icon">📧</div>
                        <h3>No campaigns yet</h3>
                        <p>Create your first campaign to get started</p>
                        <button class="btn btn-primary" onclick="showNewCampaignModal()">
                            <span>+</span> New Campaign
                        </button>
                    </div>
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = campaigns.map(campaign => `
        <tr>
            <td><strong>${campaign.name}</strong></td>
            <td>${campaign.subject}</td>
            <td>
                <span class="badge badge-${getStatusBadge(campaign.status)}">
                    ${campaign.status}
                </span>
            </td>
            <td>${campaign.total_recipients || 0}</td>
            <td>${campaign.sent_count || 0}</td>
            <td>
                <button class="btn btn-sm btn-secondary" onclick="viewCampaign(${campaign.id})">
                    View
                </button>
                <button class="btn btn-sm btn-danger" onclick="deleteCampaign(${campaign.id})">
                    Delete
                </button>
            </td>
        </tr>
    `).join('');
}

function getStatusBadge(status) {
    const badges = {
        'draft': 'info',
        'sending': 'warning',
        'completed': 'success',
        'paused': 'warning',
        'failed': 'danger'
    };
    return badges[status] || 'info';
}

// Modal Functions
function showModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('active');
    }
}

function hideModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('active');
    }
}

function showNewCampaignModal() {
    showModal('newCampaignModal');
}

async function createCampaign(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);

    const campaignData = {
        name: formData.get('name'),
        subject: formData.get('subject'),
        body_html: formData.get('body_html'),
        body_text: formData.get('body_text') || '',
        throttle_rate: parseFloat(formData.get('throttle_rate')) || 0.1
    };

    try {
        const result = await apiRequest('/campaigns', {
            method: 'POST',
            body: JSON.stringify(campaignData)
        });

        showToast('Campaign created successfully!');
        hideModal('newCampaignModal');
        form.reset();
        loadCampaigns();
        loadStats();
    } catch (error) {
        showToast('Failed to create campaign', 'error');
    }
}

async function deleteCampaign(id) {
    if (!confirm('Are you sure you want to delete this campaign?')) {
        return;
    }

    try {
        await apiRequest(`/campaigns/${id}`, { method: 'DELETE' });
        showToast('Campaign deleted successfully!');
        loadCampaigns();
        loadStats();
    } catch (error) {
        showToast('Failed to delete campaign', 'error');
    }
}

async function viewCampaign(id) {
    try {
        const campaign = await apiRequest(`/campaigns/${id}`);
        alert(`Campaign: ${campaign.name}\nSubject: ${campaign.subject}\nStatus: ${campaign.status}\nRecipients: ${campaign.total_recipients}`);
    } catch (error) {
        showToast('Failed to load campaign details', 'error');
    }
}

// Provider Functions
async function loadProviders() {
    const [smtp, api] = await Promise.all([
        apiRequest('/smtp-accounts'),
        apiRequest('/api-providers')
    ]);

    const tbody = document.getElementById('providersTable');
    const providers = [
        ...smtp.map(p => ({ ...p, type: 'SMTP' })),
        ...api.map(p => ({ ...p, type: p.provider_type.toUpperCase() }))
    ];

    if (providers.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="5" style="text-align: center; padding: 3rem;">
                    <div class="empty-state">
                        <div class="empty-state-icon">🔌</div>
                        <h3>No providers configured</h3>
                        <p>Add an email provider to start sending</p>
                        <button class="btn btn-primary" onclick="showModal('newProviderModal')">
                            <span>+</span> Add Provider
                        </button>
                    </div>
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = providers.map(provider => `
        <tr>
            <td><strong>${provider.name}</strong></td>
            <td><span class="badge badge-info">${provider.type}</span></td>
            <td>${provider.from_email}</td>
            <td>
                <span class="badge badge-${provider.enabled ? 'success' : 'danger'}">
                    ${provider.enabled ? 'Active' : 'Disabled'}
                </span>
            </td>
            <td>
                <button class="btn btn-sm btn-danger" onclick="deleteProvider('${provider.type}', ${provider.id})">
                    Delete
                </button>
            </td>
        </tr>
    `).join('');
}

async function deleteProvider(type, id) {
    if (!confirm('Are you sure you want to delete this provider?')) {
        return;
    }

    try {
        const endpoint = type === 'SMTP' ? '/smtp-accounts' : '/api-providers';
        await apiRequest(`${endpoint}/${id}`, { method: 'DELETE' });
        showToast('Provider deleted successfully!');
        loadProviders();
    } catch (error) {
        showToast('Failed to delete provider', 'error');
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    // Load data based on current page
    const currentPage = window.location.pathname;

    if (currentPage === '/' || currentPage === '/index.html') {
        loadStats();
        loadCampaigns();
    } else if (currentPage === '/providers.html') {
        loadProviders();
    }

    // Close modals when clicking overlay
    document.querySelectorAll('.modal-overlay').forEach(overlay => {
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) {
                overlay.classList.remove('active');
            }
        });
    });

    // Auto-refresh stats every 30 seconds
    if (window.location.pathname === '/' || window.location.pathname === '/index.html') {
        setInterval(() => {
            loadStats();
            loadCampaigns();
        }, 30000);
    }
});

// Add CSS animations
const style = document.createElement('style');
style.textContent = `
    @keyframes slideInRight {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    
    @keyframes slideOutRight {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(100%);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);
