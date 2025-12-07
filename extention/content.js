/**
 * CS2 Float Extension - Content Script
 * Version 2.0.0 - Restored filter functionality
 */

console.log('🚀 CS2 Float Extension loaded on:', window.location.href);
console.log('🔧 Extension version: 2.0.0 with Doppler phase detection');

// Global state
let minFloat = 0.00;
let maxFloat = 1.00;
let isProcessing = false;
let processedItems = new Set();
let extensionContextValid = true;

/**
 * Check if extension context is still valid
 */
function isExtensionContextValid() {
  try {
    // Try to access chrome.runtime - this will throw if context is invalidated
    if (!chrome.runtime?.id) {
      return false;
    }
    return true;
  } catch (e) {
    return false;
  }
}

/**
 * Show warning banner when extension context is invalidated
 */
function showExtensionInvalidatedWarning() {
  if (document.getElementById('cs2-extension-warning')) {
    return; // Already shown
  }

  const banner = document.createElement('div');
  banner.id = 'cs2-extension-warning';
  banner.style.cssText = `
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    background: linear-gradient(135deg, #dc2626, #991b1b);
    color: white;
    padding: 12px;
    text-align: center;
    font-size: 14px;
    font-weight: bold;
    z-index: 999999;
    box-shadow: 0 2px 8px rgba(0,0,0,0.3);
  `;
  banner.innerHTML = `
    ⚠️ CS2 Float Extension was updated. <a href="#" style="color: white; text-decoration: underline;">Reload this page</a> to restore functionality.
  `;

  banner.querySelector('a').addEventListener('click', (e) => {
    e.preventDefault();
    window.location.reload();
  });

  document.body.appendChild(banner);
}

// OLD LOADFLOATSORTER FUNCTION REMOVED - NOW USING DIRECT SORTING BAR

/**
 * Update filter status message
 */
function updateStatus(message) {
  const status = document.getElementById('filterStatus');
  if (status) {
    status.textContent = message;
  }
}

/**
 * Filter items based on float values
 */
async function filterItems() {
  if (isProcessing) {
    updateStatus('Already processing...');
    return;
  }

  isProcessing = true;
  updateStatus(`Filtering items (${minFloat.toFixed(2)} - ${maxFloat.toFixed(2)})...`);

  const items = document.querySelectorAll('.market_listing_row');
  let visibleCount = 0;
  let hiddenCount = 0;
  let processedCount = 0;

  for (const item of items) {
    processedCount++;
    
    // Get float value from the item
    const floatElement = item.querySelector('.cs2-float-value');
    if (floatElement) {
      const floatValue = parseFloat(floatElement.textContent);
      
      if (floatValue >= minFloat && floatValue <= maxFloat) {
        item.style.display = '';
        visibleCount++;
      } else {
        item.style.display = 'none';
        hiddenCount++;
      }
    } else {
      // If no float data yet, keep item visible for now
      item.style.display = '';
    }
    
    // Update status periodically
    if (processedCount % 5 === 0) {
      updateStatus(`Processing... ${processedCount}/${items.length}`);
    }
  }

  isProcessing = false;
  updateStatus(`Showing ${visibleCount} items, hidden ${hiddenCount}`);
}

/**
 * Process float values for items on the page
 */
async function processFloatValues() {
  const items = document.querySelectorAll('.market_listing_row');
  console.log(`🔍 Found ${items.length} market listing items to process`);

  for (const item of items) {
    // Skip if already processed
    if (item.querySelector('.cs2-float-enhanced')) {
      console.log('⏭️  Skipping already processed item');
      continue;
    }

    // Find inspect link
    const inspectBtn = item.querySelector('a[href*="steam://rungame/730"]');
    if (!inspectBtn) {
      console.log('❌ No inspect link found in item');
      continue;
    }

    const inspectLink = inspectBtn.href;
    console.log('🔗 Processing inspect link:', inspectLink);

    try {
      // Check if extension context is still valid
      if (!isExtensionContextValid()) {
        console.error('❌ Extension context invalidated');
        showExtensionInvalidatedWarning();
        return;
      }

      // Request float data from background
      console.log('📨 Sending message to background script...');
      const response = await chrome.runtime.sendMessage({
        action: 'fetchEnhancedFloat',
        inspectLink: inspectLink
      });

      console.log('📬 Received response from background:', response);

      if (response && response.enhancedData) {
        console.log('✅ Enhanced data received:', response.enhancedData);
        await addFloatDisplay(item, response.enhancedData);
      } else {
        console.log('❌ No enhanced data in response');
      }
    } catch (error) {
      if (error.message && error.message.includes('Extension context invalidated')) {
        console.error('❌ Extension context invalidated');
        showExtensionInvalidatedWarning();
      } else {
        console.error('❌ Error fetching float:', error);
      }
    }

    // Add delay to avoid rate limiting
    await new Promise(resolve => setTimeout(resolve, 500));
  }

  console.log('🏁 Finished processing all items');
}

/**
 * Process single item page (like individual Doppler listings)
 */
async function processSingleItemPage() {
  console.log('🔍 Processing single item page...');

  // Skip if already processed
  if (document.querySelector('.cs2-float-enhanced-single')) {
    console.log('Single item already processed');
    return;
  }

  // Look for inspect link in various locations on single item pages
  const inspectSelectors = [
    'a[href*="steam://rungame/730"]',
    '.market_listing_actions a[href*="steam://rungame/730"]',
    '.market_listing_iteminfo a[href*="steam://rungame/730"]',
    '.item_market_actions a[href*="steam://rungame/730"]'
  ];

  let inspectBtn = null;
  for (const selector of inspectSelectors) {
    inspectBtn = document.querySelector(selector);
    if (inspectBtn) {
      console.log('Found inspect link using selector:', selector);
      break;
    }
  }

  if (!inspectBtn) {
    console.log('No inspect link found on single item page');
    return;
  }

  const inspectLink = inspectBtn.href;
  console.log('Processing inspect link:', inspectLink);

  try {
    // Request float data from background
    const response = await chrome.runtime.sendMessage({
      action: 'fetchEnhancedFloat',
      inspectLink: inspectLink
    });

    if (response && response.enhancedData) {
      await addSingleItemFloatDisplay(response.enhancedData);
    } else {
      console.log('No enhanced data received for single item');
    }
  } catch (error) {
    console.error('Error fetching float for single item:', error);
  }
}

/**
 * Track item price and float data for market intelligence
 */
async function trackItemPrice(itemElement, floatData) {
  console.log('[trackItemPrice] Called with floatData:', floatData);

  try {
    // Extract price from the item element
    const priceElement = itemElement.querySelector('.market_listing_price_with_fee, .market_listing_price, .normal_price');
    if (!priceElement) {
      console.log('[trackItemPrice] No price element found');
      return;
    }

    const priceText = priceElement.textContent.trim();
    const priceMatch = priceText.match(/[\d.,]+/);
    if (!priceMatch) {
      console.log('[trackItemPrice] No price match found in:', priceText);
      return;
    }

    const price = parseFloat(priceMatch[0].replace(',', '.'));
    console.log('[trackItemPrice] Extracted price:', price);

    // Try multiple strategies to get a consistent item name
    let itemName = floatData.fullItemName || floatData.skinName || 'Unknown Item';

    // Also try to get the name from the market listing element
    const marketItemNameEl = itemElement.querySelector('.market_listing_item_name');
    const marketItemName = marketItemNameEl ? marketItemNameEl.textContent.trim() : null;

    // Use market listing name if available, otherwise use float data name
    if (marketItemName && marketItemName !== 'Unknown Item') {
      itemName = marketItemName;
    }

    // Get inspect link for tracking
    const inspectBtn = itemElement.querySelector('a[href*="steam://rungame/730"]');
    const inspectLink = inspectBtn ? inspectBtn.href : '';

    // Send tracking data to background
    chrome.runtime.sendMessage({
      action: 'trackItemPrice',
      itemName: itemName,
      price: price,
      floatValue: floatData.floatValue,
      inspectLink: inspectLink
    });

    console.log(`📊 Tracking: ${itemName} - $${price} (Float: ${floatData.floatValue})`);

    // Display Buff163 price if integration is available
    if (window.buff163Integration && itemName && price > 0) {
      await window.buff163Integration.displayBuff163Price(itemElement, itemName, price);
    }

  } catch (error) {
    console.error('Price tracking error:', error);
  }
}

/**
 * Add click-to-copy functionality to float display elements
 */
function addCopyToClipboardFunctionality(container, floatData) {
  // Create copy notification
  function showCopyNotification(element, text) {
    // Highlight the element briefly
    const originalBg = element.style.backgroundColor;
    element.style.backgroundColor = 'rgba(34, 197, 94, 0.3)';

    // Show notification
    const notification = document.createElement('div');
    notification.style.cssText = `
      position: absolute;
      background: #22c55e;
      color: white;
      padding: 4px 8px;
      border-radius: 4px;
      font-size: 11px;
      z-index: 10000;
      pointer-events: none;
      white-space: nowrap;
    `;
    notification.textContent = `Copied: ${text}`;

    // Position notification
    const rect = element.getBoundingClientRect();
    notification.style.left = (rect.left + window.scrollX) + 'px';
    notification.style.top = (rect.top + window.scrollY - 30) + 'px';

    document.body.appendChild(notification);

    // Remove notification and reset background after delay
    setTimeout(() => {
      element.style.backgroundColor = originalBg;
      if (notification.parentNode) {
        notification.parentNode.removeChild(notification);
      }
    }, 1500);
  }

  // Copy float value
  const floatElement = container.querySelector('.cs2-float-copyable');
  if (floatElement) {
    floatElement.addEventListener('click', async (e) => {
      e.preventDefault();
      e.stopPropagation();

      const floatText = floatData.floatValue.toFixed(floatData.precision || 4);

      try {
        await navigator.clipboard.writeText(floatText);
        showCopyNotification(floatElement, floatText);
        console.log('📋 Copied float:', floatText);
      } catch (err) {
        // Fallback for older browsers
        const textArea = document.createElement('textarea');
        textArea.value = floatText;
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
        showCopyNotification(floatElement, floatText);
        console.log('📋 Copied float (fallback):', floatText);
      }
    });

    // Add hover effect
    floatElement.addEventListener('mouseenter', () => {
      floatElement.style.backgroundColor = 'rgba(255, 255, 255, 0.1)';
    });

    floatElement.addEventListener('mouseleave', () => {
      floatElement.style.backgroundColor = 'transparent';
    });
  }

  // Copy pattern seed
  const patternElement = container.querySelector('.cs2-pattern-copyable');
  if (patternElement) {
    patternElement.addEventListener('click', async (e) => {
      e.preventDefault();
      e.stopPropagation();

      const patternText = floatData.paintSeed.toString();

      try {
        await navigator.clipboard.writeText(patternText);
        showCopyNotification(patternElement, patternText);
        console.log('📋 Copied pattern:', patternText);
      } catch (err) {
        // Fallback
        const textArea = document.createElement('textarea');
        textArea.value = patternText;
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
        showCopyNotification(patternElement, patternText);
      }
    });

    // Add hover effect
    patternElement.addEventListener('mouseenter', () => {
      patternElement.style.backgroundColor = 'rgba(255, 255, 255, 0.1)';
    });

    patternElement.addEventListener('mouseleave', () => {
      patternElement.style.backgroundColor = 'transparent';
    });
  }

  // Copy investment score
  const scoreElement = container.querySelector('.cs2-score-copyable');
  if (scoreElement) {
    scoreElement.addEventListener('click', async (e) => {
      e.preventDefault();
      e.stopPropagation();

      const scoreText = `${floatData.investmentScore}/10`;

      try {
        await navigator.clipboard.writeText(scoreText);
        showCopyNotification(scoreElement, scoreText);
        console.log('📋 Copied score:', scoreText);
      } catch (err) {
        // Fallback
        const textArea = document.createElement('textarea');
        textArea.value = scoreText;
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
        showCopyNotification(scoreElement, scoreText);
      }
    });

    // Add hover effect
    scoreElement.addEventListener('mouseenter', () => {
      scoreElement.style.backgroundColor = 'rgba(255, 255, 255, 0.1)';
    });

    scoreElement.addEventListener('mouseleave', () => {
      scoreElement.style.backgroundColor = 'transparent';
    });
  }
}

/**
 * Add float display to a single item page
 */
async function addSingleItemFloatDisplay(floatData) {
  console.log('Adding float display to single item page:', floatData);

  // Get current settings
  const settingsResponse = await chrome.runtime.sendMessage({ action: 'getSettings' });
  const settings = settingsResponse?.settings || {};

  // Create container for single item
  const container = document.createElement('div');
  container.className = 'cs2-float-enhanced-single';
  container.style.cssText = `
    background: linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 100%);
    color: white;
    padding: 15px 20px;
    margin: 15px 0;
    border-radius: 8px;
    font-size: 14px;
    border: 1px solid #3a3a3a;
    box-shadow: 0 2px 10px rgba(0,0,0,0.3);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  `;

  // Build display content
  let displayHtml = `
    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;">
      <h3 style="margin: 0; color: #22c55e; font-size: 18px;">🎯 CS2 Float Data</h3>
      <span style="opacity: 0.8; font-size: 12px;">Enhanced Analysis</span>
    </div>

    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px;">
      <div>
        <div style="font-weight: bold; margin-bottom: 8px;">Float Information</div>
        <div style="font-size: 24px; color: #ffd700; margin-bottom: 4px;">${floatData.floatValue.toFixed(floatData.precision || 4)}</div>
        <div style="color: #999; font-size: 12px;">Pattern: #${floatData.paintSeed}</div>
      </div>`;

  // Add Doppler phase if available
  if (floatData.dopplerPhase) {
    const phaseColors = {
      'Ruby': '#ff0000',
      'Sapphire': '#0066ff',
      'Black Pearl': '#1a1a1a',
      'Emerald': '#00ff00',
      'Phase 1': '#8b4513',
      'Phase 2': '#ff69b4',
      'Phase 3': '#00ced1',
      'Phase 4': '#ffd700'
    };
    const color = phaseColors[floatData.dopplerPhase] || '#ffffff';
    displayHtml += `
      <div>
        <div style="font-weight: bold; margin-bottom: 8px;">Doppler Phase</div>
        <div style="font-size: 20px; color: ${color}; font-weight: bold; text-shadow: 0 0 4px rgba(0,0,0,0.8);">
          ◆ ${floatData.dopplerPhase}
        </div>
      </div>`;
  }

  // Add fade percentage if available
  if (floatData.fadePercentage !== null && floatData.fadePercentage !== undefined) {
    const fadeColor = floatData.fadePercentage >= 95 ? '#ff6b6b' :
                     floatData.fadePercentage >= 90 ? '#ffa500' :
                     floatData.fadePercentage >= 80 ? '#ffeb3b' : '#9e9e9e';
    displayHtml += `
      <div>
        <div style="font-weight: bold; margin-bottom: 8px;">Fade Percentage</div>
        <div style="font-size: 20px; color: ${fadeColor}; font-weight: bold;">
          🌈 ${floatData.fadePercentage}%
        </div>
      </div>`;
  }

  // Add origin info if available
  if (floatData.origin && floatData.origin !== 'Unknown' && floatData.origin !== '') {
    displayHtml += `
      <div>
        <div style="font-weight: bold; margin-bottom: 8px;">Origin</div>
        <div style="color: #999;">${floatData.origin}</div>
      </div>`;
  }

  displayHtml += '</div>';

  // Add custom name if available
  if (floatData.customName) {
    displayHtml += `
      <div style="margin-top: 12px; padding: 8px; background: rgba(255, 215, 0, 0.1); border-radius: 4px;">
        <span style="color: #ffd700; font-style: italic; font-size: 16px;">📛 "${floatData.customName}"</span>
      </div>`;
  }

  // Add sticker details with wear if available
  if (floatData.stickers && floatData.stickers.length > 0) {
    displayHtml += '<div style="margin-top: 12px;"><div style="font-weight: bold; margin-bottom: 8px;">Stickers</div>';
    floatData.stickers.forEach((sticker, index) => {
      if (sticker && sticker.name) {
        const wearPercent = sticker.wear ? `(${Math.round(sticker.wear * 100)}% wear)` : '';
        displayHtml += `<div style="margin-bottom: 4px; color: #ccc;">🏷️ Slot ${index + 1}: ${sticker.name} ${wearPercent}</div>`;
      }
    });
    displayHtml += '</div>';
  }

  container.innerHTML = displayHtml;

  // Find a good place to insert the float display
  const insertionTargets = [
    '.market_listing_iteminfo',
    '.market_listing_largeimage',
    '.market_listing_nav',
    '.market_listing_item_name_block'
  ];

  let inserted = false;
  for (const selector of insertionTargets) {
    const target = document.querySelector(selector);
    if (target) {
      target.parentNode.insertBefore(container, target.nextSibling);
      inserted = true;
      console.log(`Float display inserted after ${selector}`);
      break;
    }
  }

  if (!inserted) {
    // Fallback: append to body
    document.body.appendChild(container);
    console.log('Float display appended to body as fallback');
  }
}

/**
 * Add float display to an item
 */
async function addFloatDisplay(itemElement, floatData) {
  // Get current settings
  const settingsResponse = await chrome.runtime.sendMessage({ action: 'getSettings' });
  const settings = settingsResponse?.settings || {};
  const container = document.createElement('div');
  container.className = 'cs2-float-enhanced';
  container.style.cssText = `
    background: linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 100%);
    color: white;
    padding: 6px 10px;
    margin: 4px 0;
    border-radius: 6px;
    font-size: 12px;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
    border: 1px solid #3a3a3a;
  `;

  // Create float value element for filtering
  const floatValue = document.createElement('span');
  floatValue.className = 'cs2-float-value';
  floatValue.textContent = floatData.floatValue.toFixed(6);
  floatValue.style.display = 'none'; // Hidden but used for filtering

  // Calculate float position percentage for the bar
  const minFloat = floatData.min || 0.0;
  const maxFloat = floatData.max || 1.0;
  const floatRange = maxFloat - minFloat;
  const floatPosition = ((floatData.floatValue - minFloat) / floatRange) * 100;

  // Extract Steam Market price if available
  let steamPrice = null;
  const priceElement = itemElement.querySelector('.market_listing_price_with_fee, .market_listing_price, .normal_price');
  if (priceElement) {
    const priceText = priceElement.textContent.trim();
    const priceMatch = priceText.match(/[\d.,]+/);
    if (priceMatch) {
      steamPrice = parseFloat(priceMatch[0].replace(',', '.'));
    }
  }

  // Create visible display with conditional float bar
  let displayHtml = `
    <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
      <span class="cs2-float-copyable" style="cursor: pointer; transition: background-color 0.2s ease;" title="Click to copy float value">Float: ${floatData.floatValue.toFixed(floatData.precision || 4)}</span>`;

  // Add Steam price if available
  if (steamPrice) {
    displayHtml += `<span style="color: #FFA726; font-weight: bold;">💰 $${steamPrice.toFixed(2)}</span>`;
  }

  // Add visual float bar if enabled
  if (settings.enableVisualFloatBars !== false) {
    displayHtml += `
      <div style="width: 60px; height: 6px; background: linear-gradient(to right, #22c55e 0%, #84cc16 20%, #eab308 40%, #f97316 70%, #dc2626 100%); border-radius: 3px; position: relative;">
        <div style="position: absolute; left: ${floatPosition}%; top: 0; width: 2px; height: 6px; background: white; border-radius: 1px; box-shadow: 0 0 2px rgba(0,0,0,0.5);"></div>
      </div>`;
  }

  displayHtml += `</div>`;

  // Add pattern seed if pattern analysis is enabled
  if (settings.enablePatternAnalysis !== false && floatData.paintSeed) {
    displayHtml += `<div class="cs2-pattern-copyable" style="opacity: 0.9; cursor: pointer; transition: background-color 0.2s ease;" title="Click to copy pattern seed">Pattern: #${floatData.paintSeed}</div>`;
  }

  // Add Doppler phase if available
  if (floatData.dopplerPhase) {
    const phaseColors = {
      'Ruby': '#ff0000',
      'Sapphire': '#0066ff',
      'Black Pearl': '#1a1a1a',
      'Emerald': '#00ff00',
      'Phase 1': '#8b4513',
      'Phase 2': '#ff69b4',
      'Phase 3': '#00ced1',
      'Phase 4': '#ffd700'
    };
    const color = phaseColors[floatData.dopplerPhase] || '#ffffff';
    displayHtml += `<div style="color: ${color}; font-weight: bold; text-shadow: 0 0 2px rgba(0,0,0,0.8);">◆ ${floatData.dopplerPhase}</div>`;
  }

  // Add fade percentage if available
  if (floatData.fadePercentage !== null && floatData.fadePercentage !== undefined) {
    const fadeColor = floatData.fadePercentage >= 95 ? '#ff6b6b' :
                     floatData.fadePercentage >= 90 ? '#ffa500' :
                     floatData.fadePercentage >= 80 ? '#ffeb3b' : '#9e9e9e';
    displayHtml += `<div style="color: ${fadeColor}; font-weight: bold;">🌈 ${floatData.fadePercentage}% Fade</div>`;
  }

  // Add origin info inline with pattern if available
  if (floatData.origin && floatData.origin !== 'Unknown' && floatData.origin !== '') {
    displayHtml += `<div style="opacity: 0.8; font-size: 11px; color: #999;">Origin: ${floatData.origin}</div>`;
  }

  // Add custom name if available
  if (floatData.customName) {
    displayHtml += `<div style="opacity: 0.9; font-style: italic; color: #ffd700; font-size: 11px;">📛 "${floatData.customName}"</div>`;
  }

  // Add sticker details with wear if available
  if (floatData.stickers && floatData.stickers.length > 0) {
    let stickerHtml = '<div style="font-size: 10px; opacity: 0.9; margin-top: 4px;">';
    floatData.stickers.forEach((sticker, index) => {
      if (sticker && sticker.name) {
        const wearPercent = sticker.wear ? `(${Math.round(sticker.wear * 100)}% wear)` : '';
        stickerHtml += `<div>🏷️ Slot ${index + 1}: ${sticker.name} ${wearPercent}</div>`;
      }
    });
    stickerHtml += '</div>';
    displayHtml += stickerHtml;
  }

  // Add investment score if market intelligence is enabled
  if (settings.enableMarketIntelligence !== false && floatData.investmentScore) {
    const color = floatData.investmentScore >= 7 ? '#00ff00' :
                  floatData.investmentScore >= 5 ? '#ffff00' : '#ff9900';
    displayHtml += `
      <div class="cs2-score-copyable" style="color: ${color}; font-weight: bold; cursor: pointer; transition: background-color 0.2s ease;" title="Click to copy investment score">
        ★ ${floatData.investmentScore}/10
      </div>
    `;
  }

  // Add price alert button at the end if on market pages
  if (window.location.pathname.includes('/market/listings/')) {
    displayHtml += `
      <button class="cs2-price-alert-btn" style="
        background: linear-gradient(135deg, #f97316, #ea580c);
        color: white;
        border: none;
        padding: 2px 6px;
        border-radius: 3px;
        font-size: 10px;
        cursor: pointer;
        opacity: 0.8;
        flex-shrink: 0;
      ">🔔 Alert</button>
    `;
  }

  container.innerHTML = displayHtml;
  container.appendChild(floatValue);

  // Add price alert functionality
  const alertBtn = container.querySelector('.cs2-price-alert-btn');
  if (alertBtn) {
    alertBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      showPriceAlertDialog(floatData);
    });
  }

  // Add click-to-copy functionality
  addCopyToClipboardFunctionality(container, floatData);

  // Track price history for market intelligence
  await trackItemPrice(itemElement, floatData);

  // Display Buff163 price comparison if price available
  if (steamPrice && floatData.fullItemName && window.buff163Integration) {
    console.log('[CS2 Float] Calling Buff163 with:', {itemName: floatData.fullItemName, steamPrice});
    await window.buff163Integration.displayBuff163Price(itemElement, floatData.fullItemName, steamPrice);
  } else {
    console.log('[CS2 Float] Buff163 not called:', {
      hasSteamPrice: !!steamPrice,
      hasItemName: !!floatData.fullItemName,
      hasIntegration: !!window.buff163Integration
    });
  }

  // Add 3D item preview if image URL is available
  if (floatData.imageUrl && window.item3DPreview) {
    window.item3DPreview.attachToListing(itemElement, floatData.imageUrl);
  }

  // Insert after the item name
  const itemName = itemElement.querySelector('.market_listing_item_name_block');
  if (itemName) {
    itemName.parentNode.insertBefore(container, itemName.nextSibling);
  } else {
    itemElement.appendChild(container);
  }

  // 🚀 KILLER FEATURES: Add Trade Protection & Float Rarity
  // These are loaded after the main float display

  // Trade Protection Tracker - warns about reversible trades
  if (window.tradeProtectionDisplay && floatData.floatId) {
    console.log('[CS2 Float] Calling Trade Protection for floatId:', floatData.floatId);
    await window.tradeProtectionDisplay.display(container, floatData.floatId);
  } else {
    console.log('[CS2 Float] Trade Protection not available:', {
      hasDisplay: !!window.tradeProtectionDisplay,
      hasFloatId: !!floatData.floatId
    });
  }

  // Float Rarity Display - shows how rare the float is
  if (window.floatRarityDisplay && floatData.defIndex && floatData.paintIndex && floatData.floatValue !== undefined) {
    console.log('[CS2 Float] Calling Float Rarity for:', {
      defIndex: floatData.defIndex,
      paintIndex: floatData.paintIndex,
      floatValue: floatData.floatValue
    });
    await window.floatRarityDisplay.display(container, floatData.defIndex, floatData.paintIndex, floatData.floatValue);
  } else {
    console.log('[CS2 Float] Float Rarity not available:', {
      hasDisplay: !!window.floatRarityDisplay,
      hasDefIndex: !!floatData.defIndex,
      hasPaintIndex: !!floatData.paintIndex,
      hasFloatValue: floatData.floatValue !== undefined
    });
  }

  // Multi-Market Pricing - shows prices from Buff163, Skinport, CS.MONEY
  if (window.multiMarketPricing && floatData.fullItemName) {
    console.log('[CS2 Float] Calling Multi-Market Pricing for:', floatData.fullItemName);
    await window.multiMarketPricing.display(container, floatData.fullItemName, steamPrice);
  } else {
    console.log('[CS2 Float] Multi-Market Pricing not available:', {
      hasDisplay: !!window.multiMarketPricing,
      hasItemName: !!floatData.fullItemName
    });
  }

  // 📊 Track usage for feedback popup (increment after successful float display)
  if (window.FeedbackPopup) {
    FeedbackPopup.incrementUsage();
  }
}

/**
 * Create the sorting bar directly
 */
function createSortingBar() {
  // Don't create if already exists
  if (document.getElementById('cs2-float-filter')) {
    return;
  }

  console.log('🎯 Creating sorting bar...');

  // Create container
  const container = document.createElement('div');
  container.id = 'cs2-float-filter';
  container.innerHTML = `
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
      }

      #cs2-float-filter button {
        padding: 8px 16px;
        border: none;
        border-radius: 6px;
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
        background: #22c55e;
        color: #1a1a1a;
      }

      #cs2-float-filter button:hover {
        background: #16a34a;
      }
    </style>

    <label for="cs2-min-float">Min Float:</label>
    <input type="text" id="cs2-min-float" placeholder="0.0" />

    <label for="cs2-max-float">Max Float:</label>
    <input type="text" id="cs2-max-float" placeholder="1.0" />

    <button id="cs2-sort-button">Sort by Float</button>
    <button id="cs2-reset-button">Reset Filter</button>

    <div style="margin-left: auto; color: #888; font-size: 12px;" id="cs2-filter-stats"></div>
  `;

  // Insert after market_listing_filter, before searchResultsTable
  const marketFilter = document.querySelector('.market_listing_filter');
  const searchTable = document.querySelector('#searchResultsTable');

  if (marketFilter && searchTable) {
    // Insert after market_listing_filter
    marketFilter.parentNode.insertBefore(container, searchTable);
    console.log('✅ Sorting bar created and inserted after market_listing_filter');
  } else {
    // Fallback: Insert before search results
    const searchResults = document.querySelector('#searchResultsRows, .market_listing_table');
    if (searchResults && searchResults.parentNode) {
      searchResults.parentNode.insertBefore(container, searchResults);
      console.log('✅ Sorting bar created and inserted (fallback position)');
    }
  }

  // Setup event listeners
  setupSortingBarEvents();
}

/**
 * Setup sorting bar event listeners
 */
function setupSortingBarEvents() {
  const minInput = document.getElementById('cs2-min-float');
  const maxInput = document.getElementById('cs2-max-float');
  const sortButton = document.getElementById('cs2-sort-button');
  const resetButton = document.getElementById('cs2-reset-button');

  if (minInput) minInput.addEventListener('input', filterListings);
  if (maxInput) maxInput.addEventListener('input', filterListings);
  if (sortButton) sortButton.addEventListener('click', sortListings);
  if (resetButton) resetButton.addEventListener('click', resetFilter);
}

/**
 * Filter listings based on float values
 */
function filterListings() {
  const minValue = parseFloat(document.getElementById('cs2-min-float').value) || 0;
  const maxValue = parseFloat(document.getElementById('cs2-max-float').value) || 1;

  const listings = document.querySelectorAll('.market_listing_row');
  let visible = 0;

  listings.forEach(listing => {
    const floatElement = listing.querySelector('.cs2-float-value');
    if (floatElement) {
      const floatValue = parseFloat(floatElement.textContent);
      if (floatValue >= minValue && floatValue <= maxValue) {
        listing.style.display = '';
        visible++;
      } else {
        listing.style.display = 'none';
      }
    } else {
      listing.style.display = ''; // Show items without float data
    }
  });

  // Update stats
  const stats = document.getElementById('cs2-filter-stats');
  if (stats) {
    stats.textContent = `${visible}/${listings.length} items shown`;
  }
}

/**
 * Sort listings by float value
 */
function sortListings() {
  const container = document.querySelector('#searchResultsRows');
  if (!container) return;

  const listings = Array.from(container.querySelectorAll('.market_listing_row'));

  listings.sort((a, b) => {
    const floatA = a.querySelector('.cs2-float-value');
    const floatB = b.querySelector('.cs2-float-value');

    if (!floatA || !floatB) return 0;

    const valueA = parseFloat(floatA.textContent);
    const valueB = parseFloat(floatB.textContent);

    return valueA - valueB; // Ascending order
  });

  // Reorder in DOM
  listings.forEach(listing => container.appendChild(listing));

  const button = document.getElementById('cs2-sort-button');
  if (button) button.textContent = 'Sort by Float ▲';
}

/**
 * Reset filter and sorting
 */
function resetFilter() {
  document.getElementById('cs2-min-float').value = '';
  document.getElementById('cs2-max-float').value = '';

  const listings = document.querySelectorAll('.market_listing_row');
  listings.forEach(listing => {
    listing.style.display = '';
  });

  const stats = document.getElementById('cs2-filter-stats');
  if (stats) stats.textContent = '';

  const button = document.getElementById('cs2-sort-button');
  if (button) button.textContent = 'Sort by Float';
}

/**
 * Initialize the extension
 */
function initialize() {
  console.log('🔧 Initializing CS2 Float Extension...');

  // Handle market pages - both listing pages and individual item pages
  if (window.location.pathname.includes('/market/listings/')) {
    console.log('📈 Market page detected:', window.location.pathname);

    // Check if this is a search results page (multiple listings) or individual item page
    setTimeout(() => {
      const searchResults = document.querySelector('#searchResultsRows');
      const marketListings = document.querySelectorAll('.market_listing_row');

      if (searchResults && marketListings.length > 0) {
        console.log('📊 Multiple listings page - creating sorting bar');
        createSortingBar();
      } else {
        console.log('📋 Individual item page - processing single item');
        processSingleItemPage();
      }
    }, 2000);

    // Initialize integrated market intelligence (replaces floating buttons)
    setTimeout(() => {
      // createFloatingAlertButton(); // Disabled - now integrated into item info panel
      // createMarketIntelligenceButton(); // Disabled - now integrated into item info panel
      if (window.MarketIntelligence) {
        window.MarketIntelligence.integrateMarketIntelligenceIntoItemInfo();
      }
    }, 1500);

    // Process items after a short delay
    setTimeout(() => {
      processFloatValues();
    }, 1000);

    // Monitor for new items (pagination, etc.)
    const observer = new MutationObserver((mutations) => {
      let hasNewItems = false;
      mutations.forEach(mutation => {
        if (mutation.addedNodes.length > 0) {
          mutation.addedNodes.forEach(node => {
            if (node.nodeType === 1 && (node.classList?.contains('market_listing_row') || node.classList?.contains('market_listing_iteminfo'))) {
              hasNewItems = true;
            }
          });
        }
      });

      if (hasNewItems) {
        setTimeout(() => {
          processFloatValues();
          // Also check for single item pages
          setTimeout(processSingleItemPage, 500);
        }, 500);
      }
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true
    });
  } else if (window.location.pathname === '/market/' || window.location.pathname === '/market') {
    console.log('📊 Main market page detected - no float features needed');
  }
  
  // Handle inventory pages
  if (window.location.pathname.includes('/inventory')) {
    console.log('📦 Inventory page detected');
    initializeInventoryChecker();

    // Initialize the enhanced inventory system
    if (window.InventoryEnhancer) {
      setTimeout(() => {
        window.InventoryEnhancer.initializeInventoryEnhancer();
      }, 1000);
    }
  }
}

/**
 * Initialize inventory checker for Steam inventory pages
 */
function initializeInventoryChecker() {
  console.log('🔧 Initializing inventory float checker...');
  
  const InventoryFloatChecker = {
    initialized: false,
    processedAssets: new Set(),
    
    init() {
      if (this.initialized) return;
      this.initialized = true;
      
      console.log('📦 Setting up inventory item click handler...');
      
      // Listen for clicks on inventory items
      document.addEventListener('click', (event) => {
        const clickedItem = event.target.closest('.item.app730.context2');
        if (clickedItem) {
          console.log(`🖱️ Clicked on CS2 item: ${clickedItem.id}`);
          
          // Wait for Steam to update the item info panel
          setTimeout(() => {
            this.processClickedItem(clickedItem.id);
          }, 500);
        }
      });
      
      this.waitForSteamInventory();
    },
    
    processClickedItem(itemId) {
      console.log(`🔍 Processing clicked item: ${itemId}`);
      
      // Extract float from the active item info panel
      const floatData = this.extractFloatFromActiveItemInfo();
      if (floatData) {
        console.log(`✅ Extracted float from Steam UI: ${floatData.float}`);
        this.displayFloatOnInventoryItem(itemId, floatData);
      } else {
        console.log(`❌ Could not extract float data for ${itemId}`);
      }
    },
    
    extractFloatFromActiveItemInfo() {
      // Check both iteminfo panels
      for (let i = 0; i <= 1; i++) {
        const itemInfoId = `iteminfo${i}`;
        const itemInfo = document.getElementById(itemInfoId);
        
        if (itemInfo && (itemInfo.style.opacity === '1' || itemInfo.style.zIndex > 1)) {
          const assetProps = document.getElementById(`${itemInfoId}_item_asset_properties_content`);
          if (assetProps && assetProps.textContent) {
            const text = assetProps.textContent;
            console.log(`📄 Found asset properties in ${itemInfoId}:`, text);
            
            // Extract float value (format: "Wear Rating: 0.359675586")
            const floatMatch = text.match(/Wear Rating:\s*([\d.]+)/);
            const seedMatch = text.match(/Pattern Template:\s*(\d+)/);
            
            if (floatMatch) {
              return {
                float: parseFloat(floatMatch[1]),
                paintSeed: seedMatch ? parseInt(seedMatch[1]) : null
              };
            }
          }
        }
      }
      
      return null;
    },
    
    displayFloatOnInventoryItem(itemId, floatData) {
      const itemElement = document.getElementById(itemId);
      if (!itemElement) return;
      
      // Remove existing float display
      const existingDisplay = itemElement.querySelector('.cs2-inventory-float');
      if (existingDisplay) {
        existingDisplay.remove();
      }
      
      // Create float display overlay
      const floatDisplay = document.createElement('div');
      floatDisplay.className = 'cs2-inventory-float';
      floatDisplay.style.cssText = `
        position: absolute;
        bottom: 2px;
        left: 2px;
        right: 2px;
        background: linear-gradient(135deg, #1e3c72, #2a5298);
        color: white;
        font-size: 10px;
        padding: 2px 4px;
        border-radius: 3px;
        text-align: center;
        font-weight: bold;
        z-index: 10;
        box-shadow: 0 1px 3px rgba(0,0,0,0.5);
      `;
      
      const wearName = this.getWearName(floatData.float);
      floatDisplay.innerHTML = `
        <div>Float: ${floatData.float.toFixed(6)}</div>
        ${floatData.paintSeed ? `<div style="font-size: 9px; opacity: 0.9;">Pattern: #${floatData.paintSeed}</div>` : ''}
      `;
      
      // Add color coding based on float value
      if (floatData.float < 0.07) {
        floatDisplay.style.background = 'linear-gradient(135deg, #22c55e, #16a34a)'; // Factory New - Green
      } else if (floatData.float > 0.8) {
        floatDisplay.style.background = 'linear-gradient(135deg, #ef4444, #dc2626)'; // Battle-Scarred - Red
      }
      
      itemElement.appendChild(floatDisplay);
    },
    
    getWearName(floatValue) {
      if (floatValue < 0.07) return 'Factory New';
      if (floatValue < 0.15) return 'Minimal Wear';
      if (floatValue < 0.38) return 'Field-Tested';
      if (floatValue < 0.45) return 'Well-Worn';
      return 'Battle-Scarred';
    },
    
    waitForSteamInventory() {
      // Check if Steam's inventory system is available
      if (typeof g_ActiveInventory === 'undefined') {
        console.log('Steam inventory not ready, retrying in 1s...');
        setTimeout(() => this.waitForSteamInventory(), 1000);
        return;
      }
      
      console.log('✅ Steam inventory detected');
    }
  };
  
  // Initialize the inventory checker
  InventoryFloatChecker.init();
}

/**
 * Create floating price alert toggle button
 */
function createFloatingAlertButton() {
  // Don't create if already exists
  if (document.getElementById('cs2-floating-alert-toggle')) {
    return;
  }

  console.log('🔔 Creating floating alert button...');

  // Create floating alert container
  const alertContainer = document.createElement('div');
  alertContainer.id = 'cs2-price-alert-container';
  alertContainer.style.cssText = `
    position: fixed;
    top: 80px;
    right: 20px;
    width: 280px;
    background: linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 100%);
    border: 1px solid #3a3a3a;
    border-radius: 8px;
    padding: 15px;
    z-index: 9999;
    display: none;
    box-shadow: 0 4px 20px rgba(0,0,0,0.4);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  `;

  alertContainer.innerHTML = `
    <h4 style="margin: 0 0 10px 0; color: #4CAF50; font-size: 16px;">🔔 Quick Price Alert</h4>
    <div style="margin-bottom: 10px;">
      <input type="number" id="cs2-quick-target-price" placeholder="Target price ($)" style="
        width: 100%;
        padding: 8px;
        border: 1px solid #4a4a4a;
        border-radius: 4px;
        background: #3a3a3a;
        color: white;
        font-size: 14px;
        margin-bottom: 5px;
      ">
      <select id="cs2-quick-alert-type" style="
        width: 100%;
        padding: 8px;
        border: 1px solid #4a4a4a;
        border-radius: 4px;
        background: #3a3a3a;
        color: white;
        font-size: 14px;
      ">
        <option value="below">Alert when price goes below</option>
        <option value="above">Alert when price goes above</option>
      </select>
    </div>
    <button id="cs2-quick-set-alert" style="
      width: 100%;
      background: linear-gradient(135deg, #22c55e, #16a34a);
      color: white;
      border: none;
      padding: 10px;
      border-radius: 4px;
      cursor: pointer;
      font-size: 14px;
      font-weight: 600;
    ">Set Alert for Current Item</button>
  `;

  // Create toggle button
  const alertToggle = document.createElement('button');
  alertToggle.id = 'cs2-floating-alert-toggle';
  alertToggle.innerHTML = '🔔';
  alertToggle.title = 'Quick Price Alert';
  alertToggle.style.cssText = `
    position: fixed;
    top: 80px;
    right: 20px;
    width: 40px;
    height: 40px;
    background: linear-gradient(135deg, #f97316, #ea580c);
    color: white;
    border: none;
    border-radius: 50%;
    cursor: pointer;
    z-index: 10000;
    font-size: 18px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.3);
    transition: all 0.2s ease;
  `;

  // Add hover effect
  alertToggle.addEventListener('mouseenter', () => {
    alertToggle.style.transform = 'scale(1.1)';
    alertToggle.style.boxShadow = '0 4px 15px rgba(0,0,0,0.4)';
  });

  alertToggle.addEventListener('mouseleave', () => {
    alertToggle.style.transform = 'scale(1)';
    alertToggle.style.boxShadow = '0 2px 10px rgba(0,0,0,0.3)';
  });

  // Toggle functionality
  alertToggle.addEventListener('click', () => {
    const isVisible = alertContainer.style.display !== 'none';
    alertContainer.style.display = isVisible ? 'none' : 'block';
    alertToggle.style.right = isVisible ? '20px' : '320px';
  });

  // Quick alert functionality
  document.body.appendChild(alertContainer);
  document.body.appendChild(alertToggle);

  // Handle quick alert setting
  document.getElementById('cs2-quick-set-alert').addEventListener('click', () => {
    const targetPrice = parseFloat(document.getElementById('cs2-quick-target-price').value);
    const alertType = document.getElementById('cs2-quick-alert-type').value;

    if (!targetPrice || targetPrice <= 0) {
      showNotification('Please enter a valid target price', 'error');
      return;
    }

    // Get item name from page
    const itemNameElement = document.querySelector('.market_listing_largeimage .market_listing_item_name') ||
                          document.querySelector('.market_listing_item_name') ||
                          document.querySelector('h1');
    const itemName = itemNameElement ? itemNameElement.textContent.trim() : 'Current Item';

    // Create mock float data for quick alerts
    const mockFloatData = {
      floatValue: 0.0,
      wearName: 'Any Condition',
      precision: 4
    };

    setPriceAlert(itemName, targetPrice, alertType, null, mockFloatData);

    // Clear inputs
    document.getElementById('cs2-quick-target-price').value = '';

    // Hide container
    alertContainer.style.display = 'none';
    alertToggle.style.right = '20px';
  });

  console.log('✅ Floating alert button created');
}

/**
 * Create market intelligence floating button and dashboard
 */
function createMarketIntelligenceButton() {
  // Don't create if already exists
  if (document.getElementById('cs2-market-intelligence-toggle')) {
    return;
  }

  console.log('📊 Creating market intelligence button...');

  // Create floating intelligence container
  const intelligenceContainer = document.createElement('div');
  intelligenceContainer.id = 'cs2-intelligence-container';
  intelligenceContainer.style.cssText = `
    position: fixed;
    top: 80px;
    right: 320px;
    width: 350px;
    background: linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 100%);
    border: 1px solid #3a3a3a;
    border-radius: 8px;
    padding: 15px;
    z-index: 9998;
    display: none;
    box-shadow: 0 4px 20px rgba(0,0,0,0.4);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    color: white;
    max-height: 400px;
    overflow-y: auto;
  `;

  intelligenceContainer.innerHTML = `
    <h4 style="margin: 0 0 10px 0; color: #4CAF50; font-size: 16px;">📊 Market Intelligence</h4>
    <div id="intelligence-content" style="font-size: 13px;">
      <div style="text-align: center; padding: 20px; color: #888;">
        Loading market data...
      </div>
    </div>
  `;

  // Create floating intelligence toggle button
  const intelligenceToggle = document.createElement('button');
  intelligenceToggle.id = 'cs2-market-intelligence-toggle';
  intelligenceToggle.innerHTML = '📊';
  intelligenceToggle.title = 'Market Intelligence Dashboard';
  intelligenceToggle.style.cssText = `
    position: fixed;
    top: 70px;
    right: 20px;
    width: 40px;
    height: 40px;
    border-radius: 50%;
    border: none;
    background: linear-gradient(135deg, #3b82f6, #1d4ed8);
    color: white;
    font-size: 16px;
    cursor: pointer;
    z-index: 10000;
    box-shadow: 0 2px 10px rgba(59, 130, 246, 0.3);
    transition: all 0.2s ease;
  `;

  intelligenceToggle.addEventListener('mouseover', () => {
    intelligenceToggle.style.transform = 'scale(1.1)';
    intelligenceToggle.style.boxShadow = '0 4px 15px rgba(59, 130, 246, 0.5)';
  });

  intelligenceToggle.addEventListener('mouseout', () => {
    intelligenceToggle.style.transform = 'scale(1)';
    intelligenceToggle.style.boxShadow = '0 2px 10px rgba(59, 130, 246, 0.3)';
  });

  intelligenceToggle.addEventListener('click', async () => {
    const isVisible = intelligenceContainer.style.display !== 'none';
    intelligenceContainer.style.display = isVisible ? 'none' : 'block';
    intelligenceToggle.style.right = isVisible ? '20px' : '390px';

    if (!isVisible) {
      await loadMarketIntelligence();
    }
  });

  document.body.appendChild(intelligenceContainer);
  document.body.appendChild(intelligenceToggle);

  console.log('✅ Market intelligence button created');
}

/**
 * Load market intelligence data
 */
async function loadMarketIntelligence() {
  const contentDiv = document.getElementById('intelligence-content');
  if (!contentDiv) return;

  contentDiv.innerHTML = '<div style="text-align: center; padding: 20px; color: #888;">Loading market data...</div>';

  try {
    // Get current item name using the same method as the working floating button
    const itemNameElement = document.querySelector('.market_listing_largeimage .market_listing_item_name') ||
                           document.querySelector('.market_listing_item_name') ||
                           document.querySelector('h1');

    const itemName = itemNameElement ? itemNameElement.textContent.trim() : 'Current Item';

    console.log('📊 Looking for market data for item:', itemName);

    // Request price history from background
    const response = await chrome.runtime.sendMessage({
      action: 'getPriceHistory',
      itemName: itemName
    });

    if (response.success && response.data) {
      displayMarketIntelligence(response.data);
    } else {
      contentDiv.innerHTML = `
        <div style="text-align: center; padding: 20px; color: #888;">
          No historical data yet for this item.<br>
          <small>Data will be collected as you browse market listings.</small>
        </div>
      `;
    }

  } catch (error) {
    console.error('Market intelligence error:', error);
    contentDiv.innerHTML = '<div style="text-align: center; padding: 20px; color: #ff6b6b;">Error loading market data</div>';
  }
}

/**
 * Display market intelligence data
 */
function displayMarketIntelligence(itemData) {
  const contentDiv = document.getElementById('intelligence-content');
  if (!contentDiv || !itemData) return;

  const priceHistory = itemData.priceHistory || [];
  const floatHistory = itemData.floatHistory || [];

  if (priceHistory.length === 0) {
    contentDiv.innerHTML = `
      <div style="text-align: center; padding: 20px; color: #888;">
        No price data collected yet.<br>
        <small>Data will appear as you browse similar items.</small>
      </div>
    `;
    return;
  }

  // Calculate market statistics
  const prices = priceHistory.map(p => p.price);
  const latestPrice = prices[prices.length - 1];
  const oldestPrice = prices[0];
  const avgPrice = prices.reduce((a, b) => a + b, 0) / prices.length;
  const minPrice = Math.min(...prices);
  const maxPrice = Math.max(...prices);
  const priceChange = ((latestPrice - oldestPrice) / oldestPrice * 100).toFixed(1);
  const volatility = ((maxPrice - minPrice) / avgPrice * 100).toFixed(1);

  // Calculate float statistics if available
  let floatStats = '';
  if (floatHistory.length > 1) {
    const floats = floatHistory.map(f => f.floatValue);
    const avgFloat = floats.reduce((a, b) => a + b, 0) / floats.length;
    const minFloatSeen = Math.min(...floats);
    const maxFloatSeen = Math.max(...floats);

    floatStats = `
      <div style="background: rgba(34, 197, 94, 0.1); padding: 8px; border-radius: 4px; margin-bottom: 8px;">
        <strong>Float Trends (${floats.length} samples)</strong><br>
        Average: ${avgFloat.toFixed(4)} | Range: ${minFloatSeen.toFixed(4)} - ${maxFloatSeen.toFixed(4)}
      </div>
    `;
  }

  const trendColor = parseFloat(priceChange) > 0 ? '#22c55e' : parseFloat(priceChange) < 0 ? '#ef4444' : '#6b7280';
  const volatilityColor = parseFloat(volatility) > 30 ? '#ef4444' : parseFloat(volatility) > 15 ? '#f59e0b' : '#22c55e';

  contentDiv.innerHTML = `
    <div style="margin-bottom: 10px;">
      <strong>${itemData.itemName}</strong>
      <div style="font-size: 11px; color: #888;">${priceHistory.length} price points collected</div>
    </div>

    ${floatStats}

    <div style="background: rgba(59, 130, 246, 0.1); padding: 8px; border-radius: 4px; margin-bottom: 8px;">
      <strong>Price Statistics</strong><br>
      Current: $${latestPrice.toFixed(2)} | Average: $${avgPrice.toFixed(2)}<br>
      Range: $${minPrice.toFixed(2)} - $${maxPrice.toFixed(2)}<br>
      <span style="color: ${trendColor};">Trend: ${priceChange > 0 ? '↗' : priceChange < 0 ? '↘' : '→'} ${priceChange}%</span><br>
      <span style="color: ${volatilityColor};">Volatility: ${volatility}%</span>
    </div>

    <div style="background: rgba(168, 85, 247, 0.1); padding: 8px; border-radius: 4px; margin-bottom: 8px;">
      <strong>Investment Signals</strong><br>
      ${latestPrice < avgPrice * 0.9 ? '🟢 Below average price' :
        latestPrice > avgPrice * 1.1 ? '🔴 Above average price' : '🟡 Near average price'}<br>
      ${parseFloat(volatility) > 25 ? '⚠️ High volatility - risky' : '✅ Stable pricing'}
    </div>

    <div style="font-size: 11px; color: #888; text-align: center; margin-top: 10px;">
      Data collected since ${new Date(itemData.firstSeen).toLocaleDateString()}
    </div>
  `;
}

/**
 * Show price alert dialog
 */
function showPriceAlertDialog(floatData) {
  // Remove existing dialog if any
  const existing = document.getElementById('cs2-price-alert-modal');
  if (existing) existing.remove();

  // Get item name from page
  const itemNameElement = document.querySelector('.market_listing_largeimage .market_listing_item_name');
  const itemName = itemNameElement ? itemNameElement.textContent.trim() : 'CS2 Item';

  // Create modal
  const modal = document.createElement('div');
  modal.id = 'cs2-price-alert-modal';
  modal.innerHTML = `
    <div style="
      position: fixed;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      background: rgba(0,0,0,0.7);
      z-index: 10000;
      display: flex;
      align-items: center;
      justify-content: center;
    ">
      <div style="
        background: linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 100%);
        border: 1px solid #3a3a3a;
        border-radius: 8px;
        padding: 20px;
        width: 400px;
        color: white;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      ">
        <h3 style="margin: 0 0 15px 0; color: #4CAF50;">🔔 Set Price Alert</h3>
        <div style="margin-bottom: 15px;">
          <strong>${itemName}</strong><br>
          <span style="opacity: 0.8;">Float: ${floatData.floatValue.toFixed(floatData.precision || 4)} (${floatData.wearName})</span>
        </div>

        <div style="margin-bottom: 15px;">
          <label style="display: block; margin-bottom: 5px;">Target Price:</label>
          <input type="number" id="cs2-target-price" placeholder="Enter price" style="
            width: 100%;
            padding: 8px;
            border: 1px solid #4a4a4a;
            border-radius: 4px;
            background: #3a3a3a;
            color: white;
            font-size: 14px;
          ">
        </div>

        <div style="margin-bottom: 15px;">
          <label style="display: block; margin-bottom: 5px;">Alert Type:</label>
          <select id="cs2-alert-type" style="
            width: 100%;
            padding: 8px;
            border: 1px solid #4a4a4a;
            border-radius: 4px;
            background: #3a3a3a;
            color: white;
            font-size: 14px;
          ">
            <option value="below">Alert when price goes below</option>
            <option value="above">Alert when price goes above</option>
          </select>
        </div>

        <div style="margin-bottom: 15px;">
          <label style="display: block; margin-bottom: 5px;">Max Float (optional):</label>
          <input type="number" id="cs2-max-float" placeholder="Leave empty for any float" step="0.001" min="0" max="1" style="
            width: 100%;
            padding: 8px;
            border: 1px solid #4a4a4a;
            border-radius: 4px;
            background: #3a3a3a;
            color: white;
            font-size: 14px;
          ">
        </div>

        <div style="display: flex; gap: 10px; justify-content: flex-end;">
          <button id="cs2-alert-cancel" style="
            padding: 8px 16px;
            border: none;
            border-radius: 4px;
            background: #6b7280;
            color: white;
            cursor: pointer;
            font-size: 14px;
          ">Cancel</button>
          <button id="cs2-alert-confirm" style="
            padding: 8px 16px;
            border: none;
            border-radius: 4px;
            background: #22c55e;
            color: white;
            cursor: pointer;
            font-size: 14px;
          ">Set Alert</button>
        </div>
      </div>
    </div>
  `;

  document.body.appendChild(modal);

  // Event listeners
  document.getElementById('cs2-alert-cancel').addEventListener('click', () => modal.remove());
  document.getElementById('cs2-alert-confirm').addEventListener('click', () => {
    const targetPrice = parseFloat(document.getElementById('cs2-target-price').value);
    const alertType = document.getElementById('cs2-alert-type').value;
    const maxFloat = document.getElementById('cs2-max-float').value;

    if (!targetPrice || targetPrice <= 0) {
      alert('Please enter a valid target price');
      return;
    }

    setPriceAlert(itemName, targetPrice, alertType, maxFloat || null, floatData);
    modal.remove();
  });

  // Close on background click
  modal.addEventListener('click', (e) => {
    if (e.target === modal) modal.remove();
  });
}

/**
 * Set price alert in storage
 */
async function setPriceAlert(itemName, targetPrice, alertType, maxFloat, floatData) {
  const alertKey = `alert_${itemName}_${Date.now()}`;

  try {
    await chrome.runtime.sendMessage({
      action: 'saveAlert',
      alertData: {
        id: alertKey,
        itemName,
        targetPrice,
        alertType,
        maxFloat,
        currentFloat: floatData.floatValue,
        wearName: floatData.wearName,
        timestamp: Date.now(),
        active: true
      }
    });

    // Show success notification
    showNotification(`Alert set: ${itemName} ${alertType} $${targetPrice}${maxFloat ? ` (max float: ${maxFloat})` : ''}`, 'success');
  } catch (error) {
    showNotification('Failed to set alert. Please try again.', 'error');
    console.error('Alert save error:', error);
  }
}

/**
 * Show notification
 */
function showNotification(message, type = 'info') {
  const notification = document.createElement('div');
  notification.style.cssText = `
    position: fixed;
    top: 80px;
    right: 20px;
    background: ${type === 'success' ? '#22c55e' : type === 'error' ? '#ef4444' : '#3b82f6'};
    color: white;
    padding: 12px 20px;
    border-radius: 6px;
    z-index: 10001;
    font-size: 13px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    animation: slideInRight 0.3s ease-out;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  `;
  notification.textContent = message;

  // Add animation styles
  if (!document.getElementById('cs2-notification-styles')) {
    const style = document.createElement('style');
    style.id = 'cs2-notification-styles';
    style.textContent = `
      @keyframes slideInRight {
        from { transform: translateX(100%); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
      }
    `;
    document.head.appendChild(style);
  }

  document.body.appendChild(notification);

  // Auto-remove after 4 seconds
  setTimeout(() => {
    if (notification.parentNode) {
      notification.style.animation = 'slideInRight 0.3s ease-out reverse';
      setTimeout(() => notification.remove(), 300);
    }
  }, 4000);
}

// Message listener for popup commands
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'reloadFloats') {
    console.log('🔄 Reload floats requested from popup');

    // Clear existing float displays (market and inventory)
    document.querySelectorAll('.cs2-float-enhanced, .cs2-inventory-float').forEach(el => el.remove());

    // Clear processed items tracker
    processedItems.clear();

    if (window.location.pathname.includes('/market/')) {
      // Re-process market items
      processFloatValues();
    } else if (window.location.pathname.includes('/inventory')) {
      // Re-initialize inventory checker
      initializeInventoryChecker();
    }

    sendResponse({ success: true });
    return true; // Required for async response
  }
});

// Listen for infinite scroll new items event
window.addEventListener('cs2float:newItemsLoaded', (event) => {
  console.log(`[CS2 Float] New items loaded by infinite scroll (page ${event.detail.page})`);

  // Process float values for newly loaded items
  setTimeout(() => {
    processFloatValues();
  }, 500); // Small delay to ensure DOM is ready
});

// Make processFloatValues globally accessible for infinite scroll
window.processFloatValues = processFloatValues;

// Initialize feedback popup system (shows after 15 float checks)
if (window.FeedbackPopup) {
  // Small delay to not interfere with page load
  setTimeout(() => {
    new FeedbackPopup();
  }, 2000);
}

// Start when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initialize);
} else {
  initialize();
}