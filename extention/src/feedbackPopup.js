/**
 * Feedback Popup System
 * Encourages users to leave a review on Chrome Web Store
 * Shows after user has used the extension multiple times
 */

class FeedbackPopup {
    constructor() {
        this.storageKey = 'cs2float_feedback';
        this.usageKey = 'cs2float_usage_count';
        this.showAfterUsages = 15; // Show after 15 float checks

        // Chrome Web Store review page
        this.chromeStoreUrl = 'https://chromewebstore.google.com/detail/cs2-float-checker-the-com/iplljmjdhgpgnaooioidobgfdmjiohmn/reviews';

        this.init();
    }

    /**
     * Initialize feedback popup system
     */
    async init() {
        console.log('[FeedbackPopup] Initializing...');

        // Check if we should show the popup
        const shouldShow = await this.shouldShowPopup();

        if (shouldShow) {
            // Small delay to not interrupt user experience
            setTimeout(() => {
                this.show();
            }, 3000);
        }
    }

    /**
     * Check if popup should be shown
     */
    async shouldShowPopup() {
        try {
            const data = await chrome.storage.local.get([this.storageKey, this.usageKey]);

            const feedbackStatus = data[this.storageKey] || {
                dismissed: false,
                reviewLeft: false,
                lastShown: null
            };

            const usageCount = data[this.usageKey] || 0;

            // Don't show if user already dismissed or left review
            if (feedbackStatus.dismissed || feedbackStatus.reviewLeft) {
                return false;
            }

            // Don't show if shown in last 7 days
            if (feedbackStatus.lastShown) {
                const daysSinceLastShown = (Date.now() - feedbackStatus.lastShown) / (1000 * 60 * 60 * 24);
                if (daysSinceLastShown < 7) {
                    return false;
                }
            }

            // Show if usage count reached threshold
            return usageCount >= this.showAfterUsages;

        } catch (error) {
            console.error('[FeedbackPopup] Error checking if should show:', error);
            return false;
        }
    }

    /**
     * Increment usage count
     */
    static async incrementUsage() {
        try {
            const usageKey = 'cs2float_usage_count';
            const data = await chrome.storage.local.get(usageKey);
            const currentCount = data[usageKey] || 0;

            await chrome.storage.local.set({
                [usageKey]: currentCount + 1
            });

            console.log('[FeedbackPopup] Usage count:', currentCount + 1);
        } catch (error) {
            console.error('[FeedbackPopup] Error incrementing usage:', error);
        }
    }

    /**
     * Show the feedback popup
     */
    show() {
        // Don't show if already exists
        if (document.getElementById('cs2float-feedback-popup')) {
            return;
        }

        console.log('[FeedbackPopup] Showing popup');

        const popup = document.createElement('div');
        popup.id = 'cs2float-feedback-popup';
        popup.innerHTML = `
            <div class="cs2float-feedback-overlay"></div>
            <div class="cs2float-feedback-container">
                <button class="cs2float-feedback-close" aria-label="Close">×</button>

                <div class="cs2float-feedback-content">
                    <div class="cs2float-feedback-header">
                        <img src="${chrome.runtime.getURL('icons/icon64.png')}" alt="CS2 Float Checker" class="cs2float-feedback-icon">
                        <h2>Thanks for using CS2 Float Checker! 💚</h2>
                    </div>

                    <p class="cs2float-feedback-message">
                        We noticed you've been using our extension for a while.
                        If you're finding it useful, please consider leaving a rating on the Chrome Web Store.
                    </p>

                    <p class="cs2float-feedback-submessage">
                        It helps us grow and improve! ⭐⭐⭐⭐⭐
                    </p>

                    <div class="cs2float-feedback-buttons">
                        <button class="cs2float-feedback-btn cs2float-feedback-btn-primary" id="cs2float-leave-review">
                            ⭐ Leave a Rating
                        </button>
                        <button class="cs2float-feedback-btn cs2float-feedback-btn-secondary" id="cs2float-remind-later">
                            Remind Me Later
                        </button>
                        <button class="cs2float-feedback-btn cs2float-feedback-btn-text" id="cs2float-no-thanks">
                            No Thanks
                        </button>
                    </div>

                    <p class="cs2float-feedback-footer">
                        Your feedback means everything to our small team! 🙏
                    </p>
                </div>
            </div>
        `;

        document.body.appendChild(popup);
        this.injectStyles();
        this.attachEventListeners();

        // Update last shown timestamp
        this.updateLastShown();
    }

    /**
     * Hide the popup
     */
    hide() {
        const popup = document.getElementById('cs2float-feedback-popup');
        if (popup) {
            popup.style.opacity = '0';
            setTimeout(() => {
                popup.remove();
            }, 300);
        }
    }

    /**
     * Attach event listeners
     */
    attachEventListeners() {
        const closeBtn = document.querySelector('.cs2float-feedback-close');
        const leaveReviewBtn = document.getElementById('cs2float-leave-review');
        const remindLaterBtn = document.getElementById('cs2float-remind-later');
        const noThanksBtn = document.getElementById('cs2float-no-thanks');
        const overlay = document.querySelector('.cs2float-feedback-overlay');

        if (closeBtn) {
            closeBtn.addEventListener('click', () => this.remindLater());
        }

        if (overlay) {
            overlay.addEventListener('click', () => this.remindLater());
        }

        if (leaveReviewBtn) {
            leaveReviewBtn.addEventListener('click', () => this.leaveReview());
        }

        if (remindLaterBtn) {
            remindLaterBtn.addEventListener('click', () => this.remindLater());
        }

        if (noThanksBtn) {
            noThanksBtn.addEventListener('click', () => this.dismiss());
        }
    }

    /**
     * User clicked "Leave a Rating"
     */
    async leaveReview() {
        console.log('[FeedbackPopup] User clicked leave review');

        // Open Chrome Web Store review page
        window.open(this.chromeStoreUrl, '_blank');

        // Mark as reviewed
        await chrome.storage.local.set({
            [this.storageKey]: {
                dismissed: false,
                reviewLeft: true,
                lastShown: Date.now()
            }
        });

        this.hide();
    }

    /**
     * User clicked "Remind Me Later"
     */
    async remindLater() {
        console.log('[FeedbackPopup] User clicked remind later');

        // Update last shown timestamp (will show again in 7 days)
        await this.updateLastShown();

        this.hide();
    }

    /**
     * User clicked "No Thanks"
     */
    async dismiss() {
        console.log('[FeedbackPopup] User dismissed permanently');

        // Mark as dismissed (won't show again)
        await chrome.storage.local.set({
            [this.storageKey]: {
                dismissed: true,
                reviewLeft: false,
                lastShown: Date.now()
            }
        });

        this.hide();
    }

    /**
     * Update last shown timestamp
     */
    async updateLastShown() {
        const data = await chrome.storage.local.get(this.storageKey);
        const feedbackStatus = data[this.storageKey] || {};

        await chrome.storage.local.set({
            [this.storageKey]: {
                ...feedbackStatus,
                lastShown: Date.now()
            }
        });
    }

    /**
     * Inject CSS styles
     */
    injectStyles() {
        if (document.getElementById('cs2float-feedback-styles')) {
            return;
        }

        const style = document.createElement('style');
        style.id = 'cs2float-feedback-styles';
        style.textContent = `
            .cs2float-feedback-overlay {
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(0, 0, 0, 0.6);
                z-index: 999998;
                backdrop-filter: blur(4px);
            }

            .cs2float-feedback-container {
                position: fixed;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
                background: linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 100%);
                border: 2px solid #4CAF50;
                border-radius: 16px;
                padding: 0;
                max-width: 420px;
                width: 90%;
                z-index: 999999;
                box-shadow: 0 20px 60px rgba(0, 0, 0, 0.8);
                animation: cs2float-feedback-slide-in 0.3s ease-out;
            }

            @keyframes cs2float-feedback-slide-in {
                from {
                    opacity: 0;
                    transform: translate(-50%, -40%);
                }
                to {
                    opacity: 1;
                    transform: translate(-50%, -50%);
                }
            }

            .cs2float-feedback-close {
                position: absolute;
                top: 12px;
                right: 12px;
                background: rgba(255, 255, 255, 0.1);
                border: none;
                color: white;
                font-size: 24px;
                width: 32px;
                height: 32px;
                border-radius: 50%;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                transition: background 0.2s;
                z-index: 1;
            }

            .cs2float-feedback-close:hover {
                background: rgba(255, 255, 255, 0.2);
            }

            .cs2float-feedback-content {
                padding: 32px 28px 28px;
            }

            .cs2float-feedback-header {
                text-align: center;
                margin-bottom: 20px;
            }

            .cs2float-feedback-icon {
                width: 64px;
                height: 64px;
                margin-bottom: 12px;
                border-radius: 12px;
                box-shadow: 0 4px 12px rgba(76, 175, 80, 0.3);
            }

            .cs2float-feedback-header h2 {
                color: white;
                font-size: 22px;
                margin: 0;
                font-weight: 600;
                line-height: 1.3;
            }

            .cs2float-feedback-message {
                color: rgba(255, 255, 255, 0.9);
                font-size: 15px;
                line-height: 1.6;
                margin: 0 0 12px 0;
                text-align: center;
            }

            .cs2float-feedback-submessage {
                color: #4CAF50;
                font-size: 14px;
                text-align: center;
                margin: 0 0 24px 0;
                font-weight: 500;
            }

            .cs2float-feedback-buttons {
                display: flex;
                flex-direction: column;
                gap: 10px;
                margin-bottom: 16px;
            }

            .cs2float-feedback-btn {
                padding: 12px 20px;
                border: none;
                border-radius: 8px;
                font-size: 15px;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.2s;
                font-family: inherit;
            }

            .cs2float-feedback-btn-primary {
                background: linear-gradient(135deg, #4CAF50, #45a049);
                color: white;
                box-shadow: 0 4px 12px rgba(76, 175, 80, 0.3);
            }

            .cs2float-feedback-btn-primary:hover {
                background: linear-gradient(135deg, #45a049, #3d8b40);
                box-shadow: 0 6px 16px rgba(76, 175, 80, 0.4);
                transform: translateY(-2px);
            }

            .cs2float-feedback-btn-secondary {
                background: rgba(255, 255, 255, 0.1);
                color: white;
                border: 1px solid rgba(255, 255, 255, 0.2);
            }

            .cs2float-feedback-btn-secondary:hover {
                background: rgba(255, 255, 255, 0.15);
            }

            .cs2float-feedback-btn-text {
                background: transparent;
                color: rgba(255, 255, 255, 0.6);
                padding: 8px;
                font-size: 13px;
            }

            .cs2float-feedback-btn-text:hover {
                color: rgba(255, 255, 255, 0.8);
            }

            .cs2float-feedback-footer {
                color: rgba(255, 255, 255, 0.5);
                font-size: 12px;
                text-align: center;
                margin: 0;
                line-height: 1.4;
            }

            /* Responsive */
            @media (max-width: 480px) {
                .cs2float-feedback-container {
                    width: 95%;
                }

                .cs2float-feedback-content {
                    padding: 28px 20px 24px;
                }

                .cs2float-feedback-header h2 {
                    font-size: 20px;
                }
            }
        `;

        document.head.appendChild(style);
    }
}

// Export for use in content script
if (typeof window !== 'undefined') {
    window.FeedbackPopup = FeedbackPopup;
}

/**
 * TESTING HELPERS
 * Run these in browser console to test the feedback popup
 */

// Force show popup (for testing)
function testFeedbackPopup() {
    const popup = new FeedbackPopup();
    popup.show();
    console.log('✅ Feedback popup shown (test mode)');
}

// Check current usage count
async function checkFeedbackUsage() {
    const data = await chrome.storage.local.get(['cs2float_usage_count', 'cs2float_feedback']);
    console.log('📊 Usage Count:', data.cs2float_usage_count || 0);
    console.log('📊 Feedback Status:', data.cs2float_feedback || 'Not set');
    console.log('📊 Shows after:', 15, 'usages');
}

// Reset feedback system (for testing)
async function resetFeedbackSystem() {
    await chrome.storage.local.remove(['cs2float_usage_count', 'cs2float_feedback']);
    console.log('✅ Feedback system reset');
}

// Set usage count manually (for testing)
async function setFeedbackUsage(count) {
    await chrome.storage.local.set({ cs2float_usage_count: count });
    console.log(`✅ Usage count set to ${count}`);
}

// Make test functions globally available
if (typeof window !== 'undefined') {
    window.testFeedbackPopup = testFeedbackPopup;
    window.checkFeedbackUsage = checkFeedbackUsage;
    window.resetFeedbackSystem = resetFeedbackSystem;
    window.setFeedbackUsage = setFeedbackUsage;

    console.log('🧪 Feedback test functions loaded:');
    console.log('   - testFeedbackPopup() - Force show popup');
    console.log('   - checkFeedbackUsage() - Check current usage');
    console.log('   - resetFeedbackSystem() - Reset all data');
    console.log('   - setFeedbackUsage(15) - Set usage to trigger popup');
}
