/**
 * Buff163 Price Integration
 * Shows Buff163 prices alongside Steam Market prices
 *
 * HIGH-VALUE FEATURE: Arbitrage opportunity detection
 * User Impact: Find profitable trading opportunities instantly
 *
 * Buff163 is the largest Chinese CS2 skin marketplace, often with
 * lower prices than Steam, creating arbitrage opportunities
 */

class Buff163Integration {
    constructor() {
        this.enabled = true;
        // Use Skin Broker API - works without CORS issues
        this.apiBaseUrl = 'https://skin.broker/api/ext';
        this.priceCache = new Map();
        this.cacheTimeout = 5 * 60 * 1000; // 5 minutes
        this.exchangeRate = null; // CNY to USD
        this.pendingRequests = new Map();
        this.defaultCurrency = 'USD';

        this.init();
    }

    /**
     * Initialize Buff163 integration
     */
    async init() {
        console.log('[CS2 Float] Buff163 Integration initialized');

        // Get exchange rate
        await this.updateExchangeRate();

        // Create CSS
        this.injectCSS();
    }

    /**
     * Get current CNY to USD exchange rate
     */
    async updateExchangeRate() {
        try {
            // Use a free exchange rate API
            const response = await fetch('https://api.exchangerate-api.com/v4/latest/CNY');
            const data = await response.json();
            this.exchangeRate = data.rates.USD;
            console.log(`[CS2 Float] Exchange rate: 1 CNY = $${this.exchangeRate.toFixed(4)} USD`);
        } catch (error) {
            console.error('[CS2 Float] Error fetching exchange rate:', error);
            // Fallback exchange rate (approximate)
            this.exchangeRate = 0.14;
        }
    }

    /**
     * Fetch Buff163 price for an item
     * @param {string} itemName - Steam market name
     * @returns {Object|null} Price data
     */
    async fetchBuff163Price(itemName) {
        // Check cache first
        const cached = this.priceCache.get(itemName);
        if (cached && Date.now() - cached.timestamp < this.cacheTimeout) {
            return cached.data;
        }

        // Check if request is already pending
        if (this.pendingRequests.has(itemName)) {
            return this.pendingRequests.get(itemName);
        }

        // Create new request
        const requestPromise = this._fetchFromBuff163(itemName);
        this.pendingRequests.set(itemName, requestPromise);

        try {
            const data = await requestPromise;

            // Cache result
            this.priceCache.set(itemName, {
                data: data,
                timestamp: Date.now()
            });

            return data;
        } finally {
            this.pendingRequests.delete(itemName);
        }
    }

    /**
     * Internal method to fetch from Skin Broker API
     * @private
     */
    async _fetchFromBuff163(itemName) {
        try {
            // Use Skin Broker API which provides real Buff163 prices without CORS issues
            const url = new URL(this.apiBaseUrl);
            url.searchParams.append('marketName', itemName);
            url.searchParams.append('currency', this.defaultCurrency);

            const response = await fetch(url, {
                method: 'GET',
                headers: {
                    'Accept': 'application/json'
                }
            });

            if (!response.ok) {
                throw new Error(`Skin Broker API error: ${response.status}`);
            }

            const data = await response.json();

            // Skin Broker API returns price data in the response
            if (data && data.buff_price) {
                const buffPriceCNY = parseFloat(data.buff_price);
                const buffPriceUSD = parseFloat(data.buff_price_usd || buffPriceCNY * this.exchangeRate);

                return {
                    itemName: itemName,
                    priceCNY: buffPriceCNY,
                    priceUSD: buffPriceUSD,
                    volume: parseInt(data.buff_volume || 0),
                    url: data.buff_url || `https://buff.163.com/market/csgo#tab=selling&page_num=1&search=${encodeURIComponent(itemName)}`,
                    available: true
                };
            }

            return null;

        } catch (error) {
            console.error('[CS2 Float] Error fetching Buff163 price:', error);
            return null;
        }
    }


    /**
     * Calculate arbitrage opportunity
     * @param {number} steamPrice - Steam Market price in USD
     * @param {number} buffPrice - Buff163 price in USD
     * @returns {Object} Arbitrage data
     */
    calculateArbitrage(steamPrice, buffPrice) {
        const difference = steamPrice - buffPrice;
        const percentage = ((difference / buffPrice) * 100).toFixed(2);

        return {
            difference: difference,
            percentage: percentage,
            profitable: difference > 0,
            worthIt: difference > 1 && parseFloat(percentage) > 10 // At least $1 and 10% profit
        };
    }

    /**
     * Display Buff163 price for a market listing
     * @param {HTMLElement} listingElement - Market listing row
     * @param {string} itemName - Item name
     * @param {number} steamPrice - Steam Market price
     */
    async displayBuff163Price(listingElement, itemName, steamPrice) {
        console.log('🟢 [Buff163] ========== START DISPLAY ==========');
        console.log('[Buff163] Called with:', {
            itemName,
            steamPrice,
            enabled: this.enabled,
            listingElement: listingElement ? 'EXISTS' : 'NULL'
        });

        if (!this.enabled) {
            console.log('🔴 [Buff163] Integration DISABLED');
            return;
        }

        if (!listingElement) {
            console.log('🔴 [Buff163] No listing element provided!');
            return;
        }

        // Check if already processed
        if (listingElement.querySelector('.buff163-price-display')) {
            console.log('⏭️  [Buff163] Already processed this listing');
            return;
        }

        console.log('🔍 [Buff163] Fetching price for:', itemName);

        // Fetch Buff163 price
        const buffData = await this.fetchBuff163Price(itemName);

        console.log('📦 [Buff163] Fetched data:', buffData);

        if (!buffData || !buffData.available) {
            console.log('[Buff163] No data available or item not found');
            return;
        }

        // Calculate arbitrage
        const arbitrage = this.calculateArbitrage(steamPrice, buffData.priceUSD);

        console.log('💰 [Buff163] Arbitrage calculated:', arbitrage);

        // Create price display
        const priceDisplay = this.createPriceDisplay(buffData, steamPrice, arbitrage);
        console.log('✅ [Buff163] Price display element created');

        // Find float display container first (insert after float info for better visibility)
        const floatDisplay = listingElement.querySelector('.cs2-float-enhanced, .cs2-float-display, .float-display');
        console.log('🔍 [Buff163] Looking for insertion point...');
        console.log('   - Float display (.cs2-float-enhanced):', floatDisplay ? 'FOUND ✅' : 'NOT FOUND ❌');

        if (floatDisplay) {
            // Insert after float display
            console.log('📌 [Buff163] Inserting after float display');
            floatDisplay.parentNode.insertBefore(priceDisplay, floatDisplay.nextSibling);
            console.log('✅ [Buff163] Successfully inserted after float display');
        } else {
            // Fallback: Find item name block and insert after it
            const itemNameBlock = listingElement.querySelector('.market_listing_item_name_block');
            console.log('   - Item name block:', itemNameBlock ? 'FOUND ✅' : 'NOT FOUND ❌');

            if (itemNameBlock) {
                console.log('📌 [Buff163] Inserting after item name block');
                itemNameBlock.parentNode.insertBefore(priceDisplay, itemNameBlock.nextSibling);
                console.log('✅ [Buff163] Successfully inserted after item name block');
            } else {
                // Last resort: Find the market listing row and append
                const marketRow = listingElement.querySelector('.market_listing_row_inner, .market_listing_right_cell');
                console.log('   - Market row:', marketRow ? 'FOUND ✅' : 'NOT FOUND ❌');

                if (marketRow) {
                    console.log('📌 [Buff163] Appending to market row');
                    marketRow.appendChild(priceDisplay);
                    console.log('✅ [Buff163] Successfully appended to market row');
                } else {
                    console.log('📌 [Buff163] No suitable container found, appending to listing element');
                    listingElement.appendChild(priceDisplay);
                    console.log('✅ [Buff163] Successfully appended to listing element');
                }
            }
        }

        console.log('🎉 [Buff163] ========== DISPLAY COMPLETE ==========');
    }

    /**
     * Create price display HTML element
     */
    createPriceDisplay(buffData, steamPrice, arbitrage) {
        const container = document.createElement('div');
        container.className = 'buff163-price-display';

        // Determine badge class based on profit
        let badgeClass = 'neutral';
        if (arbitrage.worthIt) {
            badgeClass = 'high-profit';
        } else if (arbitrage.profitable) {
            badgeClass = 'low-profit';
        } else {
            badgeClass = 'loss';
        }

        container.innerHTML = `
            <div class="buff163-header">
                <img src="https://buff.163.com/favicon.ico" alt="Buff163" class="buff163-icon">
                <span class="buff163-label">Buff163 Price</span>
            </div>

            <div class="buff163-price-row">
                <span class="buff163-price">¥${buffData.priceCNY.toFixed(2)}</span>
                <span class="buff163-price-usd">($${buffData.priceUSD.toFixed(2)})</span>
            </div>

            <div class="buff163-arbitrage ${badgeClass}">
                <span class="arbitrage-icon">${arbitrage.profitable ? '📈' : '📉'}</span>
                <span class="arbitrage-text">
                    ${arbitrage.profitable ? '+' : ''}$${Math.abs(arbitrage.difference).toFixed(2)}
                    (${arbitrage.profitable ? '+' : ''}${arbitrage.percentage}%)
                </span>
            </div>

            ${arbitrage.worthIt ? `
                <div class="buff163-alert">
                    <span class="alert-icon">⚠️</span>
                    <span class="alert-text">Profitable arbitrage!</span>
                </div>
            ` : ''}

            <div class="buff163-footer">
                <a href="${buffData.url}" target="_blank" rel="noopener noreferrer" class="buff163-link">
                    View on Buff163 →
                </a>
                <span class="buff163-volume">${buffData.volume} available</span>
            </div>
        `;

        // Add click handler to open Buff163
        const link = container.querySelector('.buff163-link');
        link.addEventListener('click', (e) => {
            e.stopPropagation();
        });

        return container;
    }

    /**
     * Inject CSS styles
     */
    injectCSS() {
        if (document.getElementById('buff163-integration-styles')) {
            return;
        }

        const style = document.createElement('style');
        style.id = 'buff163-integration-styles';
        style.textContent = `
            .buff163-price-display {
                margin: 10px 0;
                padding: 12px;
                background: linear-gradient(135deg, rgba(255, 107, 107, 0.15) 0%, rgba(255, 107, 107, 0.08) 100%);
                border: 2px solid rgba(255, 107, 107, 0.4);
                border-radius: 8px;
                font-size: 12px;
                box-shadow: 0 2px 8px rgba(255, 107, 107, 0.15);
                width: 100%;
                box-sizing: border-box;
            }

            .buff163-header {
                display: flex;
                align-items: center;
                gap: 6px;
                margin-bottom: 6px;
            }

            .buff163-icon {
                width: 14px;
                height: 14px;
            }

            .buff163-label {
                font-weight: 700;
                color: #ff6b6b;
                font-size: 13px;
            }

            .mock-badge {
                background: rgba(251, 191, 36, 0.2);
                color: #fbbf24;
                padding: 2px 6px;
                border-radius: 3px;
                font-size: 9px;
                font-weight: 600;
                border: 1px solid rgba(251, 191, 36, 0.3);
            }

            .buff163-price-row {
                display: flex;
                align-items: center;
                gap: 8px;
                margin-bottom: 6px;
            }

            .buff163-price {
                font-weight: 700;
                color: #ff6b6b;
                font-size: 15px;
            }

            .buff163-price-usd {
                color: #a1a1aa;
                font-size: 13px;
                font-weight: 600;
            }

            .buff163-arbitrage {
                display: flex;
                align-items: center;
                gap: 8px;
                padding: 6px 10px;
                border-radius: 6px;
                margin-bottom: 8px;
                font-weight: 700;
                font-size: 13px;
            }

            .buff163-arbitrage.high-profit {
                background: rgba(34, 197, 94, 0.15);
                color: #22c55e;
                border: 1px solid rgba(34, 197, 94, 0.3);
            }

            .buff163-arbitrage.low-profit {
                background: rgba(251, 191, 36, 0.15);
                color: #fbbf24;
                border: 1px solid rgba(251, 191, 36, 0.3);
            }

            .buff163-arbitrage.loss {
                background: rgba(239, 68, 68, 0.15);
                color: #ef4444;
                border: 1px solid rgba(239, 68, 68, 0.3);
            }

            .arbitrage-icon {
                font-size: 12px;
            }

            .buff163-alert {
                display: flex;
                align-items: center;
                gap: 6px;
                padding: 4px 8px;
                background: rgba(34, 197, 94, 0.2);
                border: 1px solid rgba(34, 197, 94, 0.4);
                border-radius: 4px;
                margin-bottom: 6px;
                font-weight: 600;
                font-size: 11px;
                color: #22c55e;
                animation: buff163-pulse 2s infinite;
            }

            @keyframes buff163-pulse {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.7; }
            }

            .alert-icon {
                font-size: 12px;
            }

            .buff163-footer {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding-top: 6px;
                border-top: 1px solid rgba(255, 107, 107, 0.2);
            }

            .buff163-link {
                color: #ff6b6b;
                text-decoration: none;
                font-weight: 700;
                font-size: 12px;
                transition: all 0.2s;
                display: inline-flex;
                align-items: center;
                gap: 4px;
            }

            .buff163-link:hover {
                color: #ff5252;
                text-decoration: underline;
                transform: translateX(2px);
            }

            .buff163-volume {
                color: #a1a1aa;
                font-size: 10px;
            }

            /* Mobile responsive */
            @media (max-width: 768px) {
                .buff163-price-display {
                    padding: 8px;
                }

                .buff163-footer {
                    flex-direction: column;
                    align-items: flex-start;
                    gap: 4px;
                }
            }
        `;

        document.head.appendChild(style);
    }

    /**
     * Enable Buff163 integration
     */
    enable() {
        this.enabled = true;
        console.log('[CS2 Float] Buff163 integration enabled');
    }

    /**
     * Disable Buff163 integration
     */
    disable() {
        this.enabled = false;
        console.log('[CS2 Float] Buff163 integration disabled');
    }

    /**
     * Clear price cache
     */
    clearCache() {
        this.priceCache.clear();
        console.log('[CS2 Float] Buff163 price cache cleared');
    }
}

// Initialize on page load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        window.buff163Integration = new Buff163Integration();
    });
} else {
    window.buff163Integration = new Buff163Integration();
}

// Make available globally
if (typeof window !== 'undefined') {
    window.Buff163Integration = Buff163Integration;
}
