/**
 * Float Rarity Display
 * Shows float rarity score based on REAL database statistics
 *
 * KILLER FEATURE: Shows how rare your float is (top 1%, top 5%, etc.)
 * User Impact: Know if you have a rare float worth more money
 */

class FloatRarityDisplay {
    constructor() {
        this.apiBaseUrl = 'https://api.cs2floatchecker.com';
        this.cache = new Map();
        this.cacheTimeout = 10 * 60 * 1000; // 10 minutes (rarity data changes slowly)

        this.init();
    }

    /**
     * Initialize float rarity display
     */
    init() {
        console.log('[CS2 Float] Float Rarity Display initialized');
        this.injectCSS();
    }

    /**
     * Get float rarity analysis
     * @param {number} defindex - Weapon definition index
     * @param {number} paintindex - Skin paint index
     * @param {number} floatvalue - Float value to analyze
     * @returns {Promise<Object>} Rarity data
     */
    async getFloatRarity(defindex, paintindex, floatvalue) {
        if (!defindex || !paintindex || floatvalue === undefined) {
            console.log('[FloatRarity] Missing required parameters');
            return null;
        }

        // Cache key
        const cacheKey = `${defindex}_${paintindex}_${floatvalue}`;

        // Check cache first
        const cached = this.cache.get(cacheKey);
        if (cached && Date.now() - cached.timestamp < this.cacheTimeout) {
            console.log('[FloatRarity] Using cached data');
            return cached.data;
        }

        console.log('[FloatRarity] Fetching rarity for:', {defindex, paintindex, floatvalue});

        try {
            const response = await fetch(
                `${this.apiBaseUrl}/api/float-rarity/${defindex}/${paintindex}/${floatvalue}`
            );

            if (!response.ok) {
                console.error('[FloatRarity] API error:', response.status);
                return null;
            }

            const data = await response.json();

            // Check if there's an error (not enough data)
            if (data.error) {
                console.log('[FloatRarity] Not enough data:', data.error);
                return null;
            }

            console.log('[FloatRarity] Received data:', data);

            // Cache result
            this.cache.set(cacheKey, {
                data: data,
                timestamp: Date.now()
            });

            return data;

        } catch (error) {
            console.error('[FloatRarity] Fetch error:', error);
            return null;
        }
    }

    /**
     * Display float rarity info below float display
     * @param {HTMLElement} floatContainer - The float display container
     * @param {number} defindex - Weapon definition index
     * @param {number} paintindex - Skin paint index
     * @param {number} floatvalue - Float value
     */
    async display(floatContainer, defindex, paintindex, floatvalue) {
        console.log('🟢 [FloatRarity] ========== START DISPLAY ==========');
        console.log('[FloatRarity] Parameters:', {defindex, paintindex, floatvalue});

        if (!floatContainer) {
            console.log('🔴 [FloatRarity] No float container provided');
            return;
        }

        // Check if already displayed
        if (floatContainer.parentNode.querySelector('.float-rarity-display')) {
            console.log('⏭️  [FloatRarity] Already displayed');
            return;
        }

        // Get rarity data
        const rarityData = await this.getFloatRarity(defindex, paintindex, floatvalue);

        if (!rarityData) {
            console.log('[FloatRarity] No rarity data available (not enough samples)');
            return;
        }

        // Create display element
        const displayElement = this.createDisplay(rarityData, floatvalue);

        // Insert after float display (or after trade protection if it exists)
        const insertAfter = floatContainer.parentNode.querySelector('.trade-protection-display') || floatContainer;
        insertAfter.parentNode.insertBefore(displayElement, insertAfter.nextSibling);

        console.log('🎉 [FloatRarity] ========== DISPLAY COMPLETE ==========');
    }

    /**
     * Create float rarity display element
     * @param {Object} rarityData - Rarity data from API
     * @param {number} floatvalue - The float value
     * @returns {HTMLElement} Display element
     */
    createDisplay(rarityData, floatvalue) {
        const container = document.createElement('div');
        container.className = 'float-rarity-display';

        // Calculate stars (1-5 based on rarity score)
        const stars = Math.min(5, Math.ceil(rarityData.rarityScore / 20));
        const starDisplay = '⭐'.repeat(stars);

        // Get rarity color
        const rarityColor = this.getRarityColor(rarityData.rarityScore);

        // Compact one-liner format
        container.innerHTML = `
            <span style="color: rgba(255, 255, 255, 0.9); font-weight: 600;">💎 Rarity:</span>
            <span style="color: ${rarityColor}; font-weight: bold;">${rarityData.rarityTier}</span>
            <span style="color: rgba(255, 255, 255, 0.7);">${starDisplay}</span>
            <span style="color: rgba(255, 255, 255, 0.7);">(${rarityData.rarityScore.toFixed(1)}/100)</span>
            <span style="color: rgba(255, 255, 255, 0.6); margin-left: 8px;">Top ${rarityData.percentile.toFixed(2)}%</span>
            <span style="color: rgba(255, 255, 255, 0.5); margin-left: 8px; font-size: 11px;">${rarityData.betterFloats} better · ${rarityData.worseFloats} worse</span>
        `;

        return container;
    }

    /**
     * Get color based on rarity score
     * @param {number} score - Rarity score (0-100)
     * @returns {string} CSS color
     */
    getRarityColor(score) {
        if (score >= 99.9) return '#FFD700'; // Ultra Rare - Gold
        if (score >= 99) return '#E040FB';   // Extremely Rare - Purple
        if (score >= 95) return '#2196F3';   // Very Rare - Blue
        if (score >= 90) return '#4CAF50';   // Rare - Green
        if (score >= 75) return '#FF9800';   // Uncommon - Orange
        return '#9E9E9E';                    // Common - Gray
    }

    /**
     * Inject CSS styles
     */
    injectCSS() {
        if (document.getElementById('float-rarity-styles')) {
            return;
        }

        const style = document.createElement('style');
        style.id = 'float-rarity-styles';
        style.textContent = `
            .float-rarity-display {
                margin: 4px 0;
                padding: 6px 10px;
                background: rgba(33, 150, 243, 0.1);
                border: 1px solid rgba(33, 150, 243, 0.4);
                border-radius: 4px;
                font-size: 12px;
                box-sizing: border-box;
                display: flex;
                align-items: center;
                gap: 6px;
                flex-wrap: wrap;
            }
        `;

        document.head.appendChild(style);
    }

    /**
     * Clear cache
     */
    clearCache() {
        this.cache.clear();
        console.log('[FloatRarity] Cache cleared');
    }
}

// Initialize on page load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        window.floatRarityDisplay = new FloatRarityDisplay();
    });
} else {
    window.floatRarityDisplay = new FloatRarityDisplay();
}

// Make available globally
if (typeof window !== 'undefined') {
    window.FloatRarityDisplay = FloatRarityDisplay;
}
