// ExploreEase Custom JavaScript

// Initialize tooltips
document.addEventListener('DOMContentLoaded', function() {
    // Initialize Bootstrap tooltips
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });

    // Form validation enhancement
    enhanceForms();
    
    // Smooth scrolling for anchor links
    enableSmoothScrolling();
    
    // Add loading states to buttons
    addLoadingStates();
});

// Form enhancement function
function enhanceForms() {
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function(e) {
            const submitBtn = this.querySelector('button[type="submit"]');
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.innerHTML = '<span class="loading"></span> Processing...';
            }
        });
    });
}

// Smooth scrolling
function enableSmoothScrolling() {
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                target.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        });
    });
}

// Add loading states to buttons
function addLoadingStates() {
    document.addEventListener('click', function(e) {
        if (e.target.matches('.btn[data-loading]')) {
            const btn = e.target;
            const originalText = btn.innerHTML;
            btn.innerHTML = '<span class="loading"></span> Loading...';
            btn.disabled = true;
            
            // Reset after 3 seconds (for demo)
            setTimeout(() => {
                btn.innerHTML = originalText;
                btn.disabled = false;
            }, 3000);
        }
    });
}

// Price formatter
function formatPrice(price) {
    return new Intl.NumberFormat('en-IN', {
        style: 'currency',
        currency: 'INR',
        minimumFractionDigits: 0,
        maximumFractionDigits: 0
    }).format(price);
}

// Date formatter
function formatDate(dateString) {
    const options = { 
        year: 'numeric', 
        month: 'long', 
        day: 'numeric',
        weekday: 'long'
    };
    return new Date(dateString).toLocaleDateString('en-IN', options);
}

// Debounce function for search
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Search functionality
const searchInput = document.getElementById('search');
if (searchInput) {
    searchInput.addEventListener('input', debounce(function(e) {
        const searchTerm = e.target.value;
        if (searchTerm.length >= 3 || searchTerm.length === 0) {
            // Trigger form submission
            e.target.form.submit();
        }
    }, 500));
}

// Package comparison functionality
let selectedPackages = new Set();

function togglePackageComparison(packageId) {
    if (selectedPackages.has(packageId)) {
        selectedPackages.delete(packageId);
    } else {
        if (selectedPackages.size < 3) {
            selectedPackages.add(packageId);
        } else {
            alert('You can compare up to 3 packages at a time.');
        }
    }
    updateComparisonButton();
}

function updateComparisonButton() {
    const compareBtn = document.getElementById('compareBtn');
    if (compareBtn && selectedPackages.size > 0) {
        compareBtn.href = `/compare?package_id=${Array.from(selectedPackages).join('&package_id=')}`;
        compareBtn.style.display = 'block';
    }
}

// Image lazy loading
function lazyLoadImages() {
    const images = document.querySelectorAll('img[data-src]');
    
    const imageObserver = new IntersectionObserver((entries, observer) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const img = entry.target;
                img.src = img.dataset.src;
                img.classList.remove('lazy');
                imageObserver.unobserve(img);
            }
        });
    });

    images.forEach(img => imageObserver.observe(img));
}

// Initialize lazy loading when DOM is ready
if ('IntersectionObserver' in window) {
    lazyLoadImages();
}

// Toast notification system
function showToast(message, type = 'info') {
    const toastContainer = document.getElementById('toast-container') || createToastContainer();
    
    const toast = document.createElement('div');
    toast.className = `toast align-items-center text-bg-${type} border-0`;
    toast.setAttribute('role', 'alert');
    
    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">${message}</div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
        </div>
    `;
    
    toastContainer.appendChild(toast);
    
    const bsToast = new bootstrap.Toast(toast);
    bsToast.show();
    
    // Remove toast after it's hidden
    toast.addEventListener('hidden.bs.toast', () => {
        toast.remove();
    });
}

function createToastContainer() {
    const container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container position-fixed top-0 end-0 p-3';
    container.style.zIndex = '9999';
    document.body.appendChild(container);
    return container;
}

// Export functions for global use
window.ExploreEase = {
    formatPrice,
    formatDate,
    showToast,
    togglePackageComparison
};

