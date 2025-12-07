/**
 * Float Filter and Sorter Component
 * Provides Min Float, Max Float filtering and Sort by Float functionality
 */

class FloatSorter {
    constructor() {
        this.sortDirection = 'none'; // none, asc, desc
        this.minFloatValue = '';
        this.maxFloatValue = '';
        this.sortButton = null;
        this.resetButton = null;
        this.observer = null;
        this.debounceTimer = null;
        this.container = null;
        
        this.init();
    }
    
    init() {
        // Only show filters on individual CS2 item listing pages, not search pages
        if (!this.isValidPageForFilters()) {
            console.log('[FloatSorter] Skipping filter creation - not a valid page');
            return;
        }
        
        this.createFilterInterface();
        this.setupEventListeners();
        this.initMutationObserver();
        
        // Auto-filter when float values change
        setInterval(() => {
            if (this.minFloatValue || this.maxFloatValue) {
                this.filterItems();
            }
        }, 1000);
    }
    
    isValidPageForFilters() {
        const url = window.location.href;
        // Only show on individual item listing pages, not search pages
        return url.includes('/market/listings/') && !url.includes('/market/search');
    }
    
    createFilterInterface() {
        // Remove any existing old filter controls first
        this.removeOldFilters();
        
        // Create container
        this.container = document.createElement('div');
        this.container.id = 'cs2-float-filter';
        this.container.innerHTML = `
            <style>
                #cs2-float-filter {
                    margin: 15px 0;
                    display: flex;
                    align-items: center;
                    flex-wrap: wrap;
                    gap: 12px;
                    background: linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 100%);
                    padding: 15px;
                    border-radius: 8px;
                    border: 1px solid #3a3a3a;
                    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.3);
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                }
                
                #cs2-float-filter label {
                    margin-right: 8px;
                    font-weight: 600;
                    color: #e0e0e0;
                    font-size: 14px;
                }
                
                #cs2-float-filter input[type="text"] {
                    padding: 8px 12px;
                    border: 1px solid #4a4a4a;
                    border-radius: 6px;
                    background: #3a3a3a;
                    color: #e0e0e0;
                    width: 80px;
                    font-size: 14px;
                    transition: all 0.2s ease;
                }
                
                #cs2-float-filter input[type="text"]:focus {
                    outline: none;
                    border-color: #22c55e;
                    background: #4a4a4a;
                    box-shadow: 0 0 0 2px rgba(34, 197, 94, 0.2);
                }
                
                #cs2-float-filter input[type="text"]::placeholder {
                    color: #888;
                }
                
                #cs2-float-filter button {
                    padding: 8px 16px;
                    border: none;
                    border-radius: 6px;
                    font-size: 14px;
                    font-weight: 600;
                    cursor: pointer;
                    transition: all 0.2s ease;
                    user-select: none;
                }
                
                #cs2-float-filter #cs2-sort-button {
                    background: #22c55e;
                    color: #1a1a1a;
                }
                
                #cs2-float-filter #cs2-sort-button:hover {
                    background: #16a34a;
                    transform: translateY(-1px);
                }
                
                #cs2-float-filter #cs2-reset-button {
                    background: #6b7280;
                    color: #e0e0e0;
                }
                
                #cs2-float-filter #cs2-reset-button:hover {
                    background: #4b5563;
                    transform: translateY(-1px);
                }
                
                #cs2-float-filter .filter-stats {
                    margin-left: auto;
                    color: #888;
                    font-size: 12px;
                    padding: 4px 8px;
                    background: rgba(255, 255, 255, 0.05);
                    border-radius: 4px;
                }
            </style>
            
            <label for="cs2-min-float">Min Float:</label>
            <input type="text" id="cs2-min-float" placeholder="0.0" />
            
            <label for="cs2-max-float">Max Float:</label>
            <input type="text" id="cs2-max-float" placeholder="1.0" />
            
            <button id="cs2-sort-button">Sort by Float</button>
            <button id="cs2-reset-button">Reset Filter</button>
            
            <div class="filter-stats" id="cs2-filter-stats"></div>
        `;
        
        // Insert into page
        const searchResults = document.querySelector('#searchResultsRows, .market_listing_table');
        if (searchResults && searchResults.parentNode) {
            searchResults.parentNode.insertBefore(this.container, searchResults);
        }
    }
    
    setupEventListeners() {
        const minFloatInput = this.container.querySelector('#cs2-min-float');
        const maxFloatInput = this.container.querySelector('#cs2-max-float');
        this.sortButton = this.container.querySelector('#cs2-sort-button');
        this.resetButton = this.container.querySelector('#cs2-reset-button');
        
        minFloatInput.addEventListener('input', (e) => {
            this.minFloatValue = e.target.value.trim();
            this.filterItems();
        });
        
        maxFloatInput.addEventListener('input', (e) => {
            this.maxFloatValue = e.target.value.trim();
            this.filterItems();
        });
        
        this.sortButton.addEventListener('click', this.toggleSort.bind(this));
        this.resetButton.addEventListener('click', this.resetFilter.bind(this));
    }
    
    initMutationObserver() {
        const searchResults = document.querySelector('#searchResultsRows, .market_listing_table');
        if (!searchResults) return;
        
        const options = {
            childList: true,
            subtree: false
        };
        
        this.observer = new MutationObserver((mutations) => {
            clearTimeout(this.debounceTimer);
            this.debounceTimer = setTimeout(() => {
                this.filterItems();
            }, 100);
        });
        
        this.observer.observe(searchResults, options);
    }
    
    getFloatValue(listingElement) {
        // Try different selectors for our float data
        const selectors = [
            '.cs2-float-enhanced',
            '.cs2-float-display',
            '[data-float-value]',
            '.float-value',
            '[title*="Float"]'
        ];
        
        for (const selector of selectors) {
            const element = listingElement.querySelector(selector);
            if (element) {
                // Try data attribute first
                if (element.dataset.floatValue) {
                    const floatVal = parseFloat(element.dataset.floatValue);
                    if (!isNaN(floatVal)) return floatVal;
                }
                
                // Try extracting from text content
                const text = element.textContent || element.innerText;
                const floatMatch = text.match(/Float[:\s]*([0-9.]+)/i) || text.match(/([0-9.]+)/);
                if (floatMatch && floatMatch[1]) {
                    const floatVal = parseFloat(floatMatch[1]);
                    if (!isNaN(floatVal) && floatVal >= 0 && floatVal <= 1) {
                        return floatVal;
                    }
                }
                
                // Try title attribute
                const title = element.title || element.getAttribute('title');
                if (title) {
                    const titleMatch = title.match(/Float[:\s]*([0-9.]+)/i) || title.match(/([0-9.]+)/);
                    if (titleMatch && titleMatch[1]) {
                        const floatVal = parseFloat(titleMatch[1]);
                        if (!isNaN(floatVal) && floatVal >= 0 && floatVal <= 1) {
                            return floatVal;
                        }
                    }
                }
            }
        }
        
        return null;
    }
    
    filterItems() {
        const listings = document.querySelectorAll('.market_listing_row');
        let visibleCount = 0;
        let totalWithFloat = 0;
        
        const minFloat = this.minFloatValue ? parseFloat(this.minFloatValue) : null;
        const maxFloat = this.maxFloatValue ? parseFloat(this.maxFloatValue) : null;
        
        listings.forEach(listing => {
            const floatValue = this.getFloatValue(listing);
            
            if (floatValue !== null) {
                totalWithFloat++;
                let shouldShow = true;
                
                if (minFloat !== null && floatValue < minFloat) {
                    shouldShow = false;
                }
                
                if (maxFloat !== null && floatValue > maxFloat) {
                    shouldShow = false;
                }
                
                if (shouldShow) {
                    listing.style.display = '';
                    listing.style.opacity = '1';
                    visibleCount++;
                } else {
                    listing.style.display = 'none';
                    listing.style.opacity = '0.3';
                }
            } else {
                // If no float value, show by default
                listing.style.display = '';
                listing.style.opacity = '1';
            }
        });
        
        // Update stats
        this.updateFilterStats(visibleCount, totalWithFloat);
    }
    
    updateFilterStats(visible, total) {
        const statsElement = this.container?.querySelector('#cs2-filter-stats');
        if (statsElement) {
            if (total > 0) {
                statsElement.textContent = `${visible}/${total} items shown`;
            } else {
                statsElement.textContent = 'No float data detected yet';
            }
        }
    }
    
    toggleSort() {
        const listings = Array.from(document.querySelectorAll('.market_listing_row'));
        
        // Cycle through sort directions
        if (this.sortDirection === 'none' || this.sortDirection === 'desc') {
            this.sortDirection = 'asc';
            this.sortButton.textContent = 'Sort by Float ↑';
        } else {
            this.sortDirection = 'desc';
            this.sortButton.textContent = 'Sort by Float ↓';
        }
        
        // Sort listings by float value
        const sortedListings = listings.sort((a, b) => {
            const floatA = this.getFloatValue(a);
            const floatB = this.getFloatValue(b);
            
            // Handle null values (put at end)
            if (floatA === null && floatB === null) return 0;
            if (floatA === null) return 1;
            if (floatB === null) return -1;
            
            return this.sortDirection === 'asc' ? floatA - floatB : floatB - floatA;
        });
        
        // Reorder in DOM
        const container = document.querySelector('#searchResultsRows, .market_listing_table');
        if (container) {
            sortedListings.forEach(listing => {
                container.appendChild(listing);
            });
        }
    }
    
    resetFilter() {
        // Clear inputs
        const minFloatInput = this.container.querySelector('#cs2-min-float');
        const maxFloatInput = this.container.querySelector('#cs2-max-float');
        
        minFloatInput.value = '';
        maxFloatInput.value = '';
        
        this.minFloatValue = '';
        this.maxFloatValue = '';
        this.sortDirection = 'none';
        this.sortButton.textContent = 'Sort by Float';
        
        // Show all items
        const listings = document.querySelectorAll('.market_listing_row');
        listings.forEach(listing => {
            listing.style.display = '';
            listing.style.opacity = '1';
        });
        
        // Update stats
        this.updateFilterStats(listings.length, listings.length);
    }
    
    removeOldFilters() {
        // Remove any existing filter controls to prevent duplicates
        const oldFilters = document.querySelectorAll('#cs2-float-filter, [id*="cs2-float"], [id*="cs2-min"], [id*="cs2-max"]');
        oldFilters.forEach(filter => filter.remove());
    }
    
    destroy() {
        if (this.observer) {
            this.observer.disconnect();
        }
        
        if (this.container) {
            this.container.remove();
        }
        
        clearTimeout(this.debounceTimer);
    }
}

// Make available globally
console.log('[FloatSorter] Making FloatSorter available globally...');

// Ensure it's available immediately
if (typeof window !== 'undefined') {
    window.FloatSorter = FloatSorter;
    console.log('[FloatSorter] FloatSorter assigned to window:', typeof window.FloatSorter);

    // Also dispatch an event to signal it's ready
    window.dispatchEvent(new CustomEvent('FloatSorterReady', {
        detail: { FloatSorter: FloatSorter }
    }));
    console.log('[FloatSorter] FloatSorterReady event dispatched');
} else {
    console.error('[FloatSorter] Window object not available!');
}