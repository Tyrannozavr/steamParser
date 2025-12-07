/**
 * CS2 Float Extension - Enhanced Integrated Popup
 */

let currentSettings = {};

// Default settings
const defaultSettings = {
  enablePatternAnalysis: true,
  // enableBlueGemDetection removed - not available without proper API,
  enableMarketIntelligence: true,
  enableVisualFloatBars: true,
  showPercentileRank: true,
  floatPrecision: 4,
  cacheExpiry: 24,
  language: 'en'
};

/**
 * Load settings and stats from storage
 */
async function loadData() {
  try {
    // Load settings
    const settingsResponse = await chrome.runtime.sendMessage({ action: 'getSettings' });
    if (settingsResponse && settingsResponse.settings) {
      currentSettings = { ...defaultSettings, ...settingsResponse.settings };
    } else {
      currentSettings = { ...defaultSettings };
    }

    // Load stats  
    const statsResponse = await chrome.runtime.sendMessage({ action: 'getStats' });
    if (statsResponse && statsResponse.stats) {
      updateStats(statsResponse.stats);
    }

    updateSettingsUI();
    
  } catch (error) {
    console.error('Failed to load data:', error);
    currentSettings = { ...defaultSettings };
    updateSettingsUI();
  }
}

/**
 * Update stats display
 */
function updateStats(stats) {
  document.getElementById('itemsAnalyzed').textContent = stats.itemsAnalyzed || 0;
  // Blue gems detection stat removed - not tracked
  document.getElementById('topTierFloatsFound').textContent = stats.topTierFloatsFound || 0;
}

/**
 * Update settings UI toggles and controls
 */
function updateSettingsUI() {
  // Update toggles
  Object.keys(currentSettings).forEach(key => {
    const element = document.getElementById(key);
    if (element && typeof currentSettings[key] === 'boolean') {
      element.classList.toggle('active', currentSettings[key]);
    }
  });

  // Update input fields
  ['floatPrecision', 'cacheExpiry'].forEach(key => {
    const element = document.getElementById(key);
    if (element && currentSettings[key] !== undefined) {
      element.value = currentSettings[key];
    }
  });

  // Update language dropdown
  const languageSelect = document.getElementById('language');
  if (languageSelect && currentSettings.language) {
    languageSelect.value = currentSettings.language;
  }
}

/**
 * Save settings to storage
 */
async function saveSettings() {
  try {
    await chrome.runtime.sendMessage({
      action: 'saveSettings',
      settings: currentSettings
    });
  } catch (error) {
    console.error('Failed to save settings:', error);
  }
}

/**
 * Clear cache
 */
async function clearCache() {
  try {
    await chrome.runtime.sendMessage({ action: 'clearCache' });
    console.log('Cache cleared');
  } catch (error) {
    console.error('Failed to clear cache:', error);
  }
}

/**
 * Reload floats on current page
 */
async function reloadFloats() {
  try {
    // Get current active tab
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    
    if (tab && (tab.url.includes('steamcommunity.com/market/') || tab.url.includes('steamcommunity.com/id/') && tab.url.includes('/inventory') || tab.url.includes('steamcommunity.com/profiles/') && tab.url.includes('/inventory'))) {
      // Inject script to reload floats
      await chrome.tabs.sendMessage(tab.id, { action: 'reloadFloats' });
      
      // Show feedback
      const button = document.getElementById('reloadFloats');
      const originalText = button.textContent;
      button.textContent = '✓ Reloaded!';
      button.style.background = '#22c55e';
      
      setTimeout(() => {
        button.textContent = originalText;
        button.style.background = '';
      }, 2000);
    } else {
      // Show friendly message in popup
      const button = document.getElementById('reloadFloats');
      const originalText = button.textContent;
      button.textContent = '⚠️ Visit Steam Market/Inventory';
      button.style.background = '#f97316';

      setTimeout(() => {
        button.textContent = originalText;
        button.style.background = '';
      }, 3000);
    }
  } catch (error) {
    console.error('Failed to reload floats:', error);
    // Show friendly error message
    const button = document.getElementById('reloadFloats');
    const originalText = button.textContent;
    button.textContent = '❌ Error - Try Again';
    button.style.background = '#ef4444';

    setTimeout(() => {
      button.textContent = originalText;
      button.style.background = '';
    }, 3000);
  }
}

/**
 * Check manual float
 */
async function checkManualFloat() {
  const inspectLink = document.getElementById('manualInspect').value.trim();
  const resultDiv = document.getElementById('manualResult');
  
  if (!inspectLink) {
    // Show validation message in result area
    resultDiv.style.display = 'block';
    resultDiv.innerHTML = '<div style="color: #f97316;">⚠️ Please enter an inspect link first</div>';
    return;
  }

  if (!inspectLink.includes('steam://rungame/730')) {
    // Show validation message in result area
    resultDiv.style.display = 'block';
    resultDiv.innerHTML = '<div style="color: #f97316;">⚠️ Please enter a valid CS2 inspect link</div>';
    return;
  }
  
  try {
    // Show loading
    resultDiv.style.display = 'block';
    resultDiv.innerHTML = '<div style="text-align: center;">🔍 Analyzing float...</div>';
    
    const response = await chrome.runtime.sendMessage({
      action: 'fetchEnhancedFloat',
      inspectLink: inspectLink
    });
    
    if (response && response.enhancedData) {
      const data = response.enhancedData;
      
      let resultHTML = `
        <div style="border-bottom: 1px solid #3a3a3a; padding-bottom: 8px; margin-bottom: 8px;">
          <strong>${data.weaponName || 'CS2 Item'}</strong>
        </div>
        <div style="margin-bottom: 6px;">
          <strong>Float:</strong> ${data.floatValue.toFixed(data.precision || 4)} (${data.wearName})
        </div>
      `;
      
      if (data.paintSeed) {
        resultHTML += `<div style="margin-bottom: 6px;"><strong>Pattern:</strong> #${data.paintSeed}</div>`;
      }
      
      // Blue gem info removed - not available without proper API
      
      if (data.investmentScore) {
        const scoreColor = data.investmentScore >= 7 ? '#22c55e' : 
                          data.investmentScore >= 5 ? '#fbbf24' : '#f97316';
        resultHTML += `
          <div style="margin-top: 6px;">
            <strong>Investment Score:</strong> 
            <span style="color: ${scoreColor}; font-weight: bold;">${data.investmentScore}/10</span>
          </div>
        `;
      }
      
      if (data.floatPercentile) {
        resultHTML += `
          <div style="margin-top: 6px;">
            <strong>Float Percentile:</strong> Top ${(100-data.floatPercentile).toFixed(1)}%
          </div>
        `;
      }
      
      resultDiv.innerHTML = resultHTML;
      
    } else {
      resultDiv.innerHTML = '<div style="color: #f87171;">❌ Failed to analyze float. Please check the inspect link.</div>';
    }
    
  } catch (error) {
    console.error('Manual float check error:', error);
    resultDiv.innerHTML = '<div style="color: #f87171;">❌ Error analyzing float. Please try again.</div>';
  }
}

/**
 * Initialize popup
 */
function initialize() {
  // Load current data
  loadData();

  // Setup toggle switches
  document.querySelectorAll('.toggle').forEach(toggle => {
    toggle.addEventListener('click', () => {
      const settingKey = toggle.id;
      if (settingKey in currentSettings && typeof currentSettings[settingKey] === 'boolean') {
        currentSettings[settingKey] = !currentSettings[settingKey];
        toggle.classList.toggle('active', currentSettings[settingKey]);
        
        // Auto-save settings
        saveSettings();
      }
    });
  });

  // Setup input fields
  ['floatPrecision', 'cacheExpiry'].forEach(key => {
    const element = document.getElementById(key);
    if (element) {
      element.addEventListener('input', (e) => {
        const value = parseInt(e.target.value);

        if (!isNaN(value)) {
          currentSettings[key] = value;
          saveSettings();
        }
      });
    }
  });

  // Setup language dropdown
  const languageSelect = document.getElementById('language');
  if (languageSelect) {
    languageSelect.addEventListener('change', (e) => {
      currentSettings.language = e.target.value;
      saveSettings();
    });
  }

  // Setup action buttons
  document.getElementById('reloadFloats').addEventListener('click', reloadFloats);
  
  document.getElementById('clearCache').addEventListener('click', async () => {
    const button = document.getElementById('clearCache');
    const originalText = button.textContent;

    try {
      // Show clearing status
      button.textContent = '🗑️ Clearing...';
      button.style.background = '#6b7280';

      await clearCache();

      // Show success
      button.textContent = '✓ Cache Cleared!';
      button.style.background = '#22c55e';

      setTimeout(() => {
        button.textContent = originalText;
        button.style.background = '';
      }, 2000);
    } catch (error) {
      // Show error
      button.textContent = '❌ Clear Failed';
      button.style.background = '#ef4444';

      setTimeout(() => {
        button.textContent = originalText;
        button.style.background = '';
      }, 3000);
    }
  });
  
  // Setup manual float check
  document.getElementById('checkManual').addEventListener('click', checkManualFloat);
  
  // Allow Enter key in manual input
  document.getElementById('manualInspect').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
      checkManualFloat();
    }
  });

  console.log('🚀 CS2 Float Extension Popup loaded');
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', initialize);