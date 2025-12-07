/**
 * Trade Protection Display
 * Shows if item can be trade-reversed (within 7-day window)
 *
 * KILLER FEATURE: Warns about reversible trades
 * User Impact: Prevents scams where items get reversed after trade
 */

class TradeProtectionDisplay {
    constructor() {
        this.apiBaseUrl = 'https://api.cs2floatchecker.com';
        this.cache = new Map();
        this.cacheTimeout = 5 * 60 * 1000; // 5 minutes

        this.init();
    }

    /**
     * Initialize trade protection display
     */
    init() {
        console.log('[CS2 Float] Trade Protection Display initialized');
        this.injectCSS();
    }

    /**
     * Get trade risk analysis for an item
     * @param {string} floatId - The float ID of the item
     * @returns {Promise<Object>} Trade risk data
     */
    async getTradeRisk(floatId) {
        if (!floatId) {
            console.log('[TradeProtection] No floatId provided');
            return null;
        }

        // Check cache first
        const cached = this.cache.get(floatId);
        if (cached && Date.now() - cached.timestamp < this.cacheTimeout) {
            console.log('[TradeProtection] Using cached data for', floatId);
            return cached.data;
        }

        console.log('[TradeProtection] Fetching trade risk for floatId:', floatId);

        try {
            const response = await fetch(`${this.apiBaseUrl}/api/ownership-history/${floatId}`);

            if (!response.ok) {
                console.error('[TradeProtection] API error:', response.status);
                return null;
            }

            const data = await response.json();
            console.log('[TradeProtection] Received data:', data);

            // Cache result
            this.cache.set(floatId, {
                data: data,
                timestamp: Date.now()
            });

            return data;

        } catch (error) {
            console.error('[TradeProtection] Fetch error:', error);
            return null;
        }
    }

    /**
     * Display trade protection info below float display
     * @param {HTMLElement} floatContainer - The float display container
     * @param {string} floatId - The float ID
     */
    async display(floatContainer, floatId) {
        console.log('🟢 [TradeProtection] ========== START DISPLAY ==========');
        console.log('[TradeProtection] FloatId:', floatId);

        if (!floatContainer) {
            console.log('🔴 [TradeProtection] No float container provided');
            return;
        }

        // Check if already displayed
        if (floatContainer.parentNode.querySelector('.trade-protection-display')) {
            console.log('⏭️  [TradeProtection] Already displayed');
            return;
        }

        // Get trade risk data
        const riskData = await this.getTradeRisk(floatId);

        if (!riskData) {
            console.log('[TradeProtection] No risk data available');
            return;
        }

        // Create display element
        const displayElement = this.createDisplay(riskData);

        // Insert after float display
        floatContainer.parentNode.insertBefore(displayElement, floatContainer.nextSibling);

        console.log('🎉 [TradeProtection] ========== DISPLAY COMPLETE ==========');
    }

    /**
     * Create trade protection display element
     * @param {Object} riskData - Trade risk data from API
     * @returns {HTMLElement} Display element
     */
    createDisplay(riskData) {
        const container = document.createElement('div');
        container.className = 'trade-protection-display';

        const risk = riskData.tradeRisk;

        if (risk.risk === 'HIGH') {
            container.classList.add('risk-high');
            container.innerHTML = `
                <div class="tp-header">
                    <div class="tp-badge risk-high">⚠️ REVERSIBLE (${risk.daysRemaining}d left)</div>
                    <div class="tp-title">🛡️ Trade Protection Analysis</div>
                </div>
                <div class="tp-warning-box">
                    <p><strong>⚠️ WARNING: Trade Reversal Risk!</strong></p>
                    <p>Reversible Until: <strong>${new Date(risk.reversibleUntil).toLocaleString()}</strong></p>
                    <p>Days Remaining: <strong>${risk.daysRemaining} days</strong></p>
                    <p>Last Trade: ${new Date(risk.lastTradeDate).toLocaleString()}</p>
                    <p class="tp-advice">💡 Wait ${risk.daysRemaining} days before trading to avoid scams</p>
                </div>
                <div class="tp-footer">
                    <span>Total Owners: ${riskData.totalOwners}</span>
                </div>
            `;
        } else if (risk.risk === 'SAFE') {
            container.classList.add('risk-safe');
            container.innerHTML = `
                <div class="tp-header">
                    <div class="tp-badge risk-safe">✅ SAFE TO TRADE</div>
                    <div class="tp-title">🛡️ Trade Protection Analysis</div>
                </div>
                <div class="tp-safe-box">
                    <p><strong>✅ Safe to Trade!</strong></p>
                    <p>Last Trade: ${new Date(risk.lastTradeDate).toLocaleString()}</p>
                    <p>Days Since Trade: <strong>${risk.daysSinceLastTrade} days</strong></p>
                </div>
                <div class="tp-footer">
                    <span>Total Owners: ${riskData.totalOwners}</span>
                </div>
            `;
        } else {
            container.classList.add('risk-unknown');
            container.innerHTML = `
                <div class="tp-header">
                    <div class="tp-badge risk-unknown">❓ UNKNOWN</div>
                    <div class="tp-title">🛡️ Trade Protection Analysis</div>
                </div>
                <div class="tp-info-box">
                    <p>No trade history available for this item yet.</p>
                    <p class="tp-note">Trade history builds up as items are checked over time.</p>
                </div>
            `;
        }

        return container;
    }

    /**
     * Inject CSS styles
     */
    injectCSS() {
        if (document.getElementById('trade-protection-styles')) {
            return;
        }

        const style = document.createElement('style');
        style.id = 'trade-protection-styles';
        style.textContent = `
            .trade-protection-display {
                margin: 8px 0;
                padding: 12px;
                border-radius: 8px;
                font-size: 12px;
                box-sizing: border-box;
                border: 2px solid;
            }

            .trade-protection-display.risk-high {
                background: linear-gradient(135deg, rgba(244, 67, 54, 0.15) 0%, rgba(244, 67, 54, 0.08) 100%);
                border-color: rgba(244, 67, 54, 0.6);
            }

            .trade-protection-display.risk-safe {
                background: linear-gradient(135deg, rgba(76, 175, 80, 0.15) 0%, rgba(76, 175, 80, 0.08) 100%);
                border-color: rgba(76, 175, 80, 0.6);
            }

            .trade-protection-display.risk-unknown {
                background: linear-gradient(135deg, rgba(158, 158, 158, 0.15) 0%, rgba(158, 158, 158, 0.08) 100%);
                border-color: rgba(158, 158, 158, 0.6);
            }

            .tp-header {
                margin-bottom: 10px;
            }

            .tp-badge {
                display: inline-block;
                padding: 4px 12px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 11px;
                margin-bottom: 8px;
            }

            .tp-badge.risk-high {
                background: #f44336;
                color: white;
            }

            .tp-badge.risk-safe {
                background: #4caf50;
                color: white;
            }

            .tp-badge.risk-unknown {
                background: #9e9e9e;
                color: white;
            }

            .tp-title {
                font-weight: bold;
                font-size: 13px;
                color: white;
            }

            .tp-warning-box,
            .tp-safe-box,
            .tp-info-box {
                padding: 10px;
                border-radius: 4px;
                margin: 8px 0;
                background: rgba(0, 0, 0, 0.3);
            }

            .tp-warning-box p,
            .tp-safe-box p,
            .tp-info-box p {
                margin: 6px 0;
                color: rgba(255, 255, 255, 0.9);
            }

            .tp-advice {
                font-style: italic;
                color: rgba(255, 255, 255, 0.8) !important;
                margin-top: 10px !important;
            }

            .tp-note {
                font-size: 11px;
                color: rgba(255, 255, 255, 0.7) !important;
            }

            .tp-footer {
                margin-top: 8px;
                font-size: 11px;
                color: rgba(255, 255, 255, 0.7);
                text-align: right;
            }
        `;

        document.head.appendChild(style);
    }

    /**
     * Clear cache
     */
    clearCache() {
        this.cache.clear();
        console.log('[TradeProtection] Cache cleared');
    }
}

// Initialize on page load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        window.tradeProtectionDisplay = new TradeProtectionDisplay();
    });
} else {
    window.tradeProtectionDisplay = new TradeProtectionDisplay();
}

// Make available globally
if (typeof window !== 'undefined') {
    window.TradeProtectionDisplay = TradeProtectionDisplay;
}
