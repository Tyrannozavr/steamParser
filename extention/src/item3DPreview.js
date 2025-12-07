/**
 * 3D Item Preview - Displays item image on hover
 * Similar to CSFloat's item preview feature
 */

class Item3DPreview {
    constructor() {
        this.previewElement = null;
        this.currentImageUrl = null;
        this.isVisible = false;
        this.init();
    }

    init() {
        console.log('[CS2 Float] 3D Item Preview initialized');
        this.createPreviewElement();
        this.injectCSS();
    }

    /**
     * Create the preview element
     */
    createPreviewElement() {
        this.previewElement = document.createElement('div');
        this.previewElement.className = 'cs2-item-preview-tooltip';
        this.previewElement.style.display = 'none';

        this.previewElement.innerHTML = `
            <div class="preview-container">
                <img class="preview-image" src="" alt="Item Preview">
                <div class="preview-loader">
                    <div class="spinner"></div>
                    <span>Loading...</span>
                </div>
            </div>
        `;

        document.body.appendChild(this.previewElement);
    }

    /**
     * Show preview for an item
     * @param {string} imageUrl - CDN URL for the item image
     * @param {HTMLElement} triggerElement - Element that triggered the preview
     */
    showPreview(imageUrl, triggerElement) {
        if (!imageUrl || !this.previewElement) return;

        const img = this.previewElement.querySelector('.preview-image');
        const loader = this.previewElement.querySelector('.preview-loader');

        // Show loader
        loader.style.display = 'flex';
        img.style.display = 'none';

        // If same image, just reposition
        if (this.currentImageUrl === imageUrl && img.complete) {
            img.style.display = 'block';
            loader.style.display = 'none';
        } else {
            // Load new image
            this.currentImageUrl = imageUrl;
            img.src = imageUrl;

            img.onload = () => {
                img.style.display = 'block';
                loader.style.display = 'none';
            };

            img.onerror = () => {
                loader.innerHTML = '<span style="color: #ef4444;">Failed to load image</span>';
            };
        }

        // Position and show tooltip
        this.positionPreview(triggerElement);
        this.previewElement.style.display = 'block';
        this.isVisible = true;
    }

    /**
     * Hide preview
     */
    hidePreview() {
        if (this.previewElement) {
            this.previewElement.style.display = 'none';
            this.isVisible = false;
        }
    }

    /**
     * Position preview relative to trigger element
     */
    positionPreview(triggerElement) {
        if (!this.previewElement || !triggerElement) return;

        const rect = triggerElement.getBoundingClientRect();
        const previewWidth = 400;
        const previewHeight = 300;

        // Calculate position (prefer right side, fallback to left)
        let left = rect.right + 10;
        let top = rect.top + (rect.height / 2) - (previewHeight / 2);

        // Check if it would go off screen
        if (left + previewWidth > window.innerWidth) {
            left = rect.left - previewWidth - 10;
        }

        // Adjust vertical position if needed
        if (top < 10) {
            top = 10;
        } else if (top + previewHeight > window.innerHeight) {
            top = window.innerHeight - previewHeight - 10;
        }

        this.previewElement.style.left = `${left}px`;
        this.previewElement.style.top = `${top}px`;
    }

    /**
     * Attach preview to market listing items
     * @param {HTMLElement} listingElement - Market listing row
     * @param {string} imageUrl - Item image URL from API
     */
    attachToListing(listingElement, imageUrl) {
        if (!listingElement || !imageUrl) return;

        // Find the image container
        const imgContainer = listingElement.querySelector('.market_listing_item_img_container, .market_listing_item_img');
        if (!imgContainer) return;

        // Add hover listeners
        imgContainer.addEventListener('mouseenter', () => {
            this.showPreview(imageUrl, imgContainer);
        });

        imgContainer.addEventListener('mouseleave', () => {
            // Small delay to allow moving to tooltip
            setTimeout(() => {
                if (!this.previewElement.matches(':hover')) {
                    this.hidePreview();
                }
            }, 100);
        });

        // Keep visible when hovering over preview itself
        this.previewElement.addEventListener('mouseenter', () => {
            this.isVisible = true;
        });

        this.previewElement.addEventListener('mouseleave', () => {
            this.hidePreview();
        });

        // Add visual indicator
        imgContainer.style.cursor = 'pointer';
        imgContainer.title = 'Hover to preview 3D model';
    }

    /**
     * Inject CSS styles
     */
    injectCSS() {
        if (document.getElementById('cs2-3d-preview-styles')) {
            return;
        }

        const style = document.createElement('style');
        style.id = 'cs2-3d-preview-styles';
        style.textContent = `
            .cs2-item-preview-tooltip {
                position: fixed;
                z-index: 10000;
                width: 400px;
                height: 300px;
                background: linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 100%);
                border: 2px solid #3a3a3a;
                border-radius: 12px;
                box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
                pointer-events: auto;
                transition: opacity 0.2s ease-in-out;
                overflow: hidden;
            }

            .preview-container {
                width: 100%;
                height: 100%;
                display: flex;
                align-items: center;
                justify-content: center;
                position: relative;
            }

            .preview-image {
                max-width: 100%;
                max-height: 100%;
                object-fit: contain;
                display: none;
            }

            .preview-loader {
                display: flex;
                flex-direction: column;
                align-items: center;
                gap: 15px;
                color: #a1a1aa;
                font-size: 14px;
            }

            .spinner {
                width: 40px;
                height: 40px;
                border: 4px solid rgba(255, 255, 255, 0.1);
                border-top-color: #60a5fa;
                border-radius: 50%;
                animation: cs2-spin 0.8s linear infinite;
            }

            @keyframes cs2-spin {
                to { transform: rotate(360deg); }
            }

            /* Hover effect on market listing images */
            .market_listing_item_img_container:hover,
            .market_listing_item_img:hover {
                transform: scale(1.05);
                transition: transform 0.2s ease;
            }

            .market_listing_item_img_container,
            .market_listing_item_img {
                transition: transform 0.2s ease;
            }
        `;

        document.head.appendChild(style);
    }
}

// Initialize on page load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        window.item3DPreview = new Item3DPreview();
    });
} else {
    window.item3DPreview = new Item3DPreview();
}

// Make available globally
if (typeof window !== 'undefined') {
    window.Item3DPreview = Item3DPreview;
}
