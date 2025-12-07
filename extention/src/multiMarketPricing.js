/**
 * Multi-Market Price Comparison
 * Shows prices from Buff163, Skinport, CS.MONEY, and Market.CSGO
 *
 * KILLER FEATURE: Compare prices across ALL major CS2 marketplaces
 * User Impact: Find the best prices and arbitrage opportunities instantly
 */

class MultiMarketPricing {
    constructor() {
        this.apiBaseUrl = 'https://api.cs2floatchecker.com';
        this.cache = new Map();
        this.cacheTimeout = 10 * 60 * 1000; // 10 minutes

        this.init();
    }

    /**
     * Initialize multi-market pricing
     */
    init() {
        console.log('[CS2 Float] Multi-Market Pricing initialized');
        this.injectCSS();
    }

    /**
     * Get prices from all markets via Skin.Broker API
     * @param {string} itemName - Market hash name (e.g., "AK-47 | Redline (Field-Tested)")
     * @returns {Promise<Object>} Price data from all markets
     */
    async getPrices(itemName) {
        if (!itemName) {
            console.log('[MultiMarket] No item name provided');
            return null;
        }

        // Check cache first
        const cached = this.cache.get(itemName);
        if (cached && Date.now() - cached.timestamp < this.cacheTimeout) {
            console.log('[MultiMarket] Using cached data for:', itemName);
            return cached.data;
        }

        console.log('[MultiMarket] Fetching prices for:', itemName);

        try {
            const response = await fetch(
                `${this.apiBaseUrl}/api/price/${encodeURIComponent(itemName)}`
            );

            if (!response.ok) {
                console.error('[MultiMarket] API error:', response.status);
                return null;
            }

            const data = await response.json();

            if (!data.success) {
                console.log('[MultiMarket] No price data available:', data.error);
                return null;
            }

            console.log('[MultiMarket] Received data:', data);

            // Cache result
            this.cache.set(itemName, {
                data: data,
                timestamp: Date.now()
            });

            return data;

        } catch (error) {
            console.error('[MultiMarket] Fetch error:', error);
            return null;
        }
    }

    /**
     * Display multi-market prices
     * @param {HTMLElement} floatContainer - The float display container
     * @param {string} itemName - Market hash name
     * @param {number} steamPrice - Current Steam Market price (optional)
     */
    async display(floatContainer, itemName, steamPrice) {
        console.log('🟢 [MultiMarket] ========== START DISPLAY ==========');
        console.log('[MultiMarket] Parameters:', {itemName, steamPrice});

        if (!floatContainer) {
            console.log('🔴 [MultiMarket] No float container provided');
            return;
        }

        // Check if already displayed
        if (floatContainer.parentNode.querySelector('.multi-market-pricing')) {
            console.log('⏭️  [MultiMarket] Already displayed');
            return;
        }

        // Get price data
        const priceData = await this.getPrices(itemName);

        if (!priceData || !priceData.prices) {
            console.log('[MultiMarket] No price data available');
            return;
        }

        // Create display element
        const displayElement = this.createDisplay(priceData, steamPrice);

        // Insert after float rarity (or trade protection if rarity doesn't exist)
        const insertAfter = floatContainer.parentNode.querySelector('.float-rarity-display') ||
                           floatContainer.parentNode.querySelector('.trade-protection-display') ||
                           floatContainer;
        insertAfter.parentNode.insertBefore(displayElement, insertAfter.nextSibling);

        console.log('🎉 [MultiMarket] ========== DISPLAY COMPLETE ==========');
    }

    /**
     * Create multi-market pricing display element
     * @param {Object} priceData - Price data from API
     * @param {number} steamPrice - Steam Market price (optional)
     * @returns {HTMLElement} Display element
     */
    createDisplay(priceData, steamPrice) {
        const container = document.createElement('div');
        container.className = 'multi-market-pricing';

        let lowestMarket = null;
        let lowestPrice = Infinity;
        const markets = [];

        // Buff163
        if (priceData.prices.buff163) {
            const price = priceData.prices.buff163.price_usd;
            const diff = steamPrice ? ((price - steamPrice) / steamPrice * 100).toFixed(1) : null;

            if (price < lowestPrice) {
                lowestPrice = price;
                lowestMarket = 'Buff163';
            }

            markets.push({
                name: 'Buff163',
                emoji: '🇨🇳',
                price: price,
                diff: diff,
                listings: priceData.prices.buff163.listings,
                url: priceData.prices.buff163.url || 'https://buff.163.com'
            });
        }

        // Skinport
        if (priceData.prices.skinport) {
            const price = priceData.prices.skinport.price_usd;
            const diff = steamPrice ? ((price - steamPrice) / steamPrice * 100).toFixed(1) : null;

            if (price < lowestPrice) {
                lowestPrice = price;
                lowestMarket = 'Skinport';
            }

            markets.push({
                name: 'Skinport',
                emoji: '🌐',
                price: price,
                diff: diff,
                listings: priceData.prices.skinport.listings || 0,
                url: priceData.prices.skinport.url || 'https://skinport.com'
            });
        }

        // CS.MONEY
        if (priceData.prices.marketCsgo) {
            const price = priceData.prices.marketCsgo.price_usd;
            const diff = steamPrice ? ((price - steamPrice) / steamPrice * 100).toFixed(1) : null;

            if (price < lowestPrice) {
                lowestPrice = price;
                lowestMarket = 'CS.MONEY';
            }

            markets.push({
                name: 'CS.MONEY',
                emoji: '💎',
                price: price,
                diff: diff,
                listings: priceData.prices.marketCsgo.listings || 0,
                url: priceData.prices.marketCsgo.url || 'https://cs.money'
            });
        }

        // Build compact one-line display
        const marketLinks = markets.map((market, index) => {
            const diffColor = market.diff < 0 ? '#4CAF50' : market.diff > 0 ? '#f44336' : '#9e9e9e';
            const diffText = market.diff ? `${market.diff > 0 ? '+' : ''}${market.diff}%` : '';
            const isBest = market.price === lowestPrice;

            return `<a href="${market.url}" target="_blank" class="market-link" style="
                color: ${isBest ? '#4CAF50' : 'rgba(255, 255, 255, 0.9)'};
                text-decoration: none;
                font-weight: ${isBest ? 'bold' : 'normal'};
                display: inline-flex;
                align-items: center;
                gap: 4px;
            ">
                ${market.emoji} ${market.name}: $${market.price.toFixed(2)}${diffText ? ` <span style="color: ${diffColor}; font-size: 10px;">(${diffText})</span>` : ''}
            </a>`;
        }).join('<span style="color: rgba(255, 255, 255, 0.4); margin: 0 6px;">|</span>');

        // Steam price
        const steamDisplay = steamPrice ? `<span style="color: rgba(255, 255, 255, 0.7);">⚙️ Steam: $${steamPrice.toFixed(2)}</span>` : '';

        container.innerHTML = `
            <span style="color: rgba(255, 255, 255, 0.9); font-weight: 600;">💰 Markets:</span>
            ${marketLinks}
            ${steamDisplay ? '<span style="color: rgba(255, 255, 255, 0.4); margin: 0 6px;">|</span>' + steamDisplay : ''}
            ${lowestMarket ? `<span style="color: #4CAF50; font-size: 11px; margin-left: 8px;">(Best: ${lowestMarket})</span>` : ''}
        `;

        return container;
    }

    /**
     * Inject CSS styles
     */
    injectCSS() {
        if (document.getElementById('multi-market-pricing-styles')) {
            return;
        }

        const style = document.createElement('style');
        style.id = 'multi-market-pricing-styles';
        style.textContent = `
            .multi-market-pricing {
                margin: 4px 0;
                padding: 6px 10px;
                background: rgba(255, 167, 38, 0.1);
                border: 1px solid rgba(255, 167, 38, 0.4);
                border-radius: 4px;
                font-size: 12px;
                box-sizing: border-box;
                display: flex;
                align-items: center;
                gap: 6px;
                flex-wrap: wrap;
            }

            .market-link {
                transition: opacity 0.2s;
            }

            .market-link:hover {
                opacity: 0.8;
                text-decoration: underline !important;
            }
        `;

        document.head.appendChild(style);
    }

    /**
     * Clear cache
     */
    clearCache() {
        this.cache.clear();
        console.log('[MultiMarket] Cache cleared');
    }
}

// Initialize on page load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        window.multiMarketPricing = new MultiMarketPricing();
    });
} else {
    window.multiMarketPricing = new MultiMarketPricing();
}

// Make available globally
if (typeof window !== 'undefined') {
    window.MultiMarketPricing = MultiMarketPricing;
}
