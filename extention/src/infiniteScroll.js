/**
 * Infinite Scroll for Steam Market Listings
 * Auto-loads next page when user scrolls near bottom
 *
 * HIGH-VALUE FEATURE: Solves CSFloat pagination complaints
 * User Impact: No more manual page clicking, seamless browsing
 */

class InfiniteScrollManager {
    constructor() {
        this.enabled = true;
        this.isLoading = false;
        this.currentPage = 1;
        this.hasMorePages = true;
        this.totalResults = 0;
        this.loadThreshold = 500; // px from bottom to trigger load
        this.retryAttempts = 0;
        this.maxRetries = 3;

        // Cache for preventing duplicate requests
        this.loadedPages = new Set([1]); // Start page is already loaded

        this.init();
    }

    /**
     * Initialize infinite scroll
     */
    init() {
        // Only run on Steam Market pages
        if (!this.isSteamMarketPage()) {
            return;
        }

        console.log('[CS2 Float] Infinite Scroll initialized');

        // Get initial state from page
        this.parseInitialState();

        // Set up scroll listener
        this.setupScrollListener();

        // Add UI indicator
        this.createLoadingIndicator();

        // Monitor for manual pagination (disable infinite scroll if user clicks pagination)
        this.monitorManualPagination();
    }

    /**
     * Check if we're on a Steam Market page
     */
    isSteamMarketPage() {
        // Check if window.location exists
        if (!window.location || !window.location.href) {
            return false;
        }

        const url = window.location.href;

        // Only enable on search/browse pages, NOT on individual listing pages
        // Individual listings have /market/listings/ in URL - we skip those
        if (url.includes('steamcommunity.com/market/listings/')) {
            console.log('[CS2 Float] Infinite scroll disabled on individual listing page');
            return false;
        }

        // Enable on search and main market pages
        return url.includes('steamcommunity.com/market/search') ||
               url.includes('steamcommunity.com/market/?appid=');
    }

    /**
     * Parse initial page state from Steam's market data
     */
    parseInitialState() {
        try {
            // Steam exposes market data in g_oSearchResults
            if (typeof g_oSearchResults !== 'undefined' && g_oSearchResults) {
                this.totalResults = g_oSearchResults.total_count || 0;
                this.currentPage = this.getCurrentPageNumber();

                // Check if there are more pages
                const itemsPerPage = 10; // Steam default
                const totalPages = Math.ceil(this.totalResults / itemsPerPage);
                this.hasMorePages = this.currentPage < totalPages;

                console.log(`[CS2 Float] Total: ${this.totalResults}, Page: ${this.currentPage}/${totalPages}`);
            } else {
                console.log('[CS2 Float] No search results found - infinite scroll disabled');
                this.hasMorePages = false;
            }
        } catch (error) {
            console.error('[CS2 Float] Error parsing initial state:', error);
            this.hasMorePages = false;
        }
    }

    /**
     * Get current page number from URL or Steam variables
     */
    getCurrentPageNumber() {
        // Try URL parameter first
        const urlParams = new URLSearchParams(window.location.search);
        const pageParam = urlParams.get('p');
        if (pageParam) {
            return parseInt(pageParam, 10);
        }

        // Try Steam's global variable
        if (typeof g_oSearchResults !== 'undefined' && g_oSearchResults.pagesize) {
            const start = g_oSearchResults.start || 0;
            const pagesize = g_oSearchResults.pagesize || 10;
            return Math.floor(start / pagesize) + 1;
        }

        return 1;
    }

    /**
     * Set up scroll event listener
     */
    setupScrollListener() {
        let scrollTimeout;

        window.addEventListener('scroll', () => {
            // Debounce scroll events
            clearTimeout(scrollTimeout);
            scrollTimeout = setTimeout(() => {
                this.handleScroll();
            }, 100);
        }, { passive: true });

        console.log('[CS2 Float] Scroll listener attached');
    }

    /**
     * Handle scroll event
     */
    handleScroll() {
        if (!this.enabled || this.isLoading || !this.hasMorePages) {
            return;
        }

        const scrollPosition = window.scrollY + window.innerHeight;
        const documentHeight = document.documentElement.scrollHeight;
        const distanceFromBottom = documentHeight - scrollPosition;

        if (distanceFromBottom < this.loadThreshold) {
            console.log('[CS2 Float] Near bottom, loading next page...');
            this.loadNextPage();
        }
    }

    /**
     * Load next page of results
     */
    async loadNextPage() {
        if (this.isLoading || !this.hasMorePages) {
            return;
        }

        const nextPage = this.currentPage + 1;

        // Prevent duplicate loads
        if (this.loadedPages.has(nextPage)) {
            console.log(`[CS2 Float] Page ${nextPage} already loaded`);
            return;
        }

        this.isLoading = true;
        this.showLoadingIndicator();

        try {
            console.log(`[CS2 Float] Loading page ${nextPage}...`);

            // Build request URL
            const url = this.buildNextPageURL(nextPage);

            // Fetch next page
            const response = await fetch(url);

            if (!response.ok) {
                throw new Error(`Steam API returned status ${response.status}`);
            }

            const data = await response.json();

            if (!data || typeof data !== 'object') {
                throw new Error('Invalid JSON response from Steam');
            }

            if (data.success && data.results_html) {
                // Append new results to the page
                this.appendResults(data.results_html);

                // Update state
                this.loadedPages.add(nextPage);
                this.currentPage = nextPage;
                this.totalResults = data.total_count || this.totalResults;

                // Check if there are more pages
                const itemsPerPage = 10;
                const totalPages = Math.ceil(this.totalResults / itemsPerPage);
                this.hasMorePages = nextPage < totalPages;

                // Reset retry counter
                this.retryAttempts = 0;

                console.log(`[CS2 Float] Loaded page ${nextPage}. More pages: ${this.hasMorePages}`);

                // Trigger float processing for new items
                this.processNewItems();

                // Show success message
                this.showSuccessMessage(nextPage, totalPages);

            } else {
                throw new Error('Invalid response from Steam');
            }

        } catch (error) {
            console.error('[CS2 Float] Error loading next page:', error);

            // Retry logic
            this.retryAttempts++;
            if (this.retryAttempts < this.maxRetries) {
                console.log(`[CS2 Float] Retrying... (${this.retryAttempts}/${this.maxRetries})`);
                setTimeout(() => {
                    this.isLoading = false;
                    this.loadNextPage();
                }, 1000 * this.retryAttempts); // Exponential backoff
            } else {
                this.showErrorMessage();
                this.hasMorePages = false; // Stop trying
            }

        } finally {
            this.isLoading = false;
            this.hideLoadingIndicator();
        }
    }

    /**
     * Build URL for next page request
     */
    buildNextPageURL(pageNumber) {
        const urlParams = new URLSearchParams(window.location.search);

        // Get current search query
        const query = urlParams.get('q') || '';
        const appid = urlParams.get('appid') || '730'; // CS2 app ID

        // Calculate start index (Steam uses start index, not page number)
        const pageSize = 10;
        const start = (pageNumber - 1) * pageSize;

        // Build Steam market search URL
        const baseURL = 'https://steamcommunity.com/market/search/render/';
        const params = new URLSearchParams({
            query: query,
            start: start,
            count: pageSize,
            appid: appid,
            norender: 1
        });

        // Add any additional filters from current URL
        ['category_730_ItemSet[]', 'category_730_ProPlayer[]', 'category_730_StickerCapsule[]',
         'category_730_TournamentTeam[]', 'category_730_Weapon[]', 'category_730_Quality[]'].forEach(filter => {
            const value = urlParams.get(filter);
            if (value) {
                params.append(filter, value);
            }
        });

        return `${baseURL}?${params.toString()}`;
    }

    /**
     * Append new results to the page
     */
    appendResults(resultsHTML) {
        const resultsContainer = document.getElementById('searchResultsRows');
        if (!resultsContainer) {
            console.error('[CS2 Float] Results container not found');
            return;
        }

        // Create temporary div to parse HTML
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = resultsHTML;

        // Extract individual listing rows
        const newRows = tempDiv.querySelectorAll('.market_listing_row');

        // Append each row to results
        newRows.forEach(row => {
            resultsContainer.appendChild(row);
        });

        console.log(`[CS2 Float] Appended ${newRows.length} new listings`);
    }

    /**
     * Trigger float processing for newly loaded items
     */
    processNewItems() {
        // Dispatch custom event that the main extension can listen to
        const event = new CustomEvent('cs2float:newItemsLoaded', {
            detail: { page: this.currentPage }
        });
        window.dispatchEvent(event);

        // Also try to call the global processFloatValues if it exists
        if (typeof window.processFloatValues === 'function') {
            window.processFloatValues();
        }
    }

    /**
     * Monitor for manual pagination clicks
     */
    monitorManualPagination() {
        // Watch for pagination button clicks
        document.addEventListener('click', (e) => {
            const target = e.target;
            if (target.closest('.market_paging_controls')) {
                console.log('[CS2 Float] Manual pagination detected, disabling infinite scroll');
                this.enabled = false;
            }
        });
    }

    /**
     * Create loading indicator UI
     */
    createLoadingIndicator() {
        const indicator = document.createElement('div');
        indicator.id = 'cs2float-loading-indicator';
        indicator.style.cssText = `
            position: fixed;
            bottom: 20px;
            right: 20px;
            background: rgba(34, 197, 94, 0.95);
            color: white;
            padding: 12px 20px;
            border-radius: 8px;
            font-weight: 600;
            display: none;
            align-items: center;
            gap: 10px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
            z-index: 10000;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        `;

        indicator.innerHTML = `
            <div class="spinner" style="
                width: 16px;
                height: 16px;
                border: 2px solid rgba(255, 255, 255, 0.3);
                border-radius: 50%;
                border-top-color: white;
                animation: cs2float-spin 0.8s linear infinite;
            "></div>
            <span>Loading more items...</span>
        `;

        // Add spinner animation
        if (!document.getElementById('cs2float-spin-keyframes')) {
            const style = document.createElement('style');
            style.id = 'cs2float-spin-keyframes';
            style.textContent = `
                @keyframes cs2float-spin {
                    to { transform: rotate(360deg); }
                }
            `;
            document.head.appendChild(style);
        }

        document.body.appendChild(indicator);
        this.loadingIndicator = indicator;
    }

    /**
     * Show loading indicator
     */
    showLoadingIndicator() {
        if (this.loadingIndicator) {
            this.loadingIndicator.style.display = 'flex';
        }
    }

    /**
     * Hide loading indicator
     */
    hideLoadingIndicator() {
        if (this.loadingIndicator) {
            this.loadingIndicator.style.display = 'none';
        }
    }

    /**
     * Show success message
     */
    showSuccessMessage(currentPage, totalPages) {
        if (this.loadingIndicator) {
            this.loadingIndicator.style.background = 'rgba(34, 197, 94, 0.95)';
            this.loadingIndicator.innerHTML = `
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
                <span>Loaded page ${currentPage} of ${totalPages}</span>
            `;

            setTimeout(() => {
                this.hideLoadingIndicator();
            }, 2000);
        }
    }

    /**
     * Show error message
     */
    showErrorMessage() {
        if (this.loadingIndicator) {
            this.loadingIndicator.style.background = 'rgba(239, 68, 68, 0.95)';
            this.loadingIndicator.innerHTML = `
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="12" y1="8" x2="12" y2="12"></line>
                    <line x1="12" y1="16" x2="12.01" y2="16"></line>
                </svg>
                <span>Failed to load more items</span>
            `;

            setTimeout(() => {
                this.hideLoadingIndicator();
            }, 3000);
        }
    }

    /**
     * Enable infinite scroll
     */
    enable() {
        this.enabled = true;
        console.log('[CS2 Float] Infinite scroll enabled');
    }

    /**
     * Disable infinite scroll
     */
    disable() {
        this.enabled = false;
        console.log('[CS2 Float] Infinite scroll disabled');
    }

    /**
     * Check if infinite scroll is enabled
     */
    isEnabled() {
        return this.enabled;
    }
}

// Initialize on page load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        window.cs2FloatInfiniteScroll = new InfiniteScrollManager();
    });
} else {
    window.cs2FloatInfiniteScroll = new InfiniteScrollManager();
}

// Make available globally
if (typeof window !== 'undefined') {
    window.InfiniteScrollManager = InfiniteScrollManager;
}
