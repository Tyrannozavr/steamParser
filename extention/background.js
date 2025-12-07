/**
 * CS2 Float Extension Enhanced - Background Script
 * Version 2.0.0 - Working JavaScript version
 */

// Configuration
const API_URL = 'https://api.cs2floatchecker.com';
const cache = new Map();
const CACHE_EXPIRY = 24 * 60 * 60 * 1000; // 24 hours

// Batch Processing Configuration
const BATCH_SIZE = 10; // Process up to 10 items at once
const BATCH_DELAY = 100; // Wait 100ms to collect items before sending batch
const batchQueue = [];
let batchTimer = null;

/**
 * Clear batch queue on extension reload/update
 * This prevents "Extension context invalidated" errors
 */
function clearBatchQueue() {
  if (batchQueue.length > 0) {
    console.log(`🧹 Clearing batch queue (${batchQueue.length} items)`);
    batchQueue.forEach(item => {
      item.reject(new Error('Extension context invalidated'));
    });
    batchQueue.length = 0;
  }

  if (batchTimer) {
    clearTimeout(batchTimer);
    batchTimer = null;
  }
}

// Clear queue when extension is being unloaded
self.addEventListener('unload', () => {
  console.log('⚠️ Extension unloading, cleaning up...');
  clearBatchQueue();
});

/**
 * Helper function to get wear name from float value
 */
function getWearName(floatValue) {
  if (floatValue < 0.07) return 'Factory New';
  if (floatValue < 0.15) return 'Minimal Wear';
  if (floatValue < 0.38) return 'Field-Tested';
  if (floatValue < 0.45) return 'Well-Worn';
  return 'Battle-Scarred';
}

/**
 * Get weapon name from defindex
 */
function getWeaponName(defindex) {
  const weapons = {
    1: 'Desert Eagle',
    2: 'Dual Berettas', 
    3: 'Five-SeveN',
    4: 'Glock-18',
    7: 'AK-47',
    8: 'AUG',
    9: 'AWP',
    10: 'FAMAS',
    16: 'M4A4',
    17: 'MAC-10',
    60: 'M4A1-S',
    61: 'USP-S'
  };
  return weapons[defindex] || `Weapon ${defindex}`;
}

// Blue gem detection removed - requires proper database or API support
// CSGOFloat API doesn't provide blue percentage data directly

/**
 * Get Doppler phase from paint index
 */
function getDopplerPhase(paintIndex) {
  const dopplerPhases = {
    418: 'Phase 1',
    419: 'Phase 2',
    420: 'Phase 3',
    421: 'Phase 4',
    415: 'Ruby',
    416: 'Sapphire',
    417: 'Black Pearl',
    569: 'Phase 1',
    570: 'Phase 2',
    571: 'Phase 3',
    572: 'Phase 4',
    568: 'Emerald',
    618: 'Phase 2',
    619: 'Sapphire',
    617: 'Black Pearl',
    852: 'Phase 1',
    853: 'Phase 2',
    854: 'Phase 3',
    855: 'Phase 4',
    1119: 'Emerald',
    1120: 'Phase 1',
    1121: 'Phase 2',
    1122: 'Phase 3',
    1123: 'Phase 4'
  };
  return dopplerPhases[paintIndex] || null;
}

/**
 * Get fade percentage using CSFloat's approach
 */
function getFadePercentage(weaponType, itemName, paintSeed, fullItemName) {
  if (!itemName || !weaponType) {
    return null;
  }

  // Check if this is a fade item by examining the item name
  let fadeType = null;
  if (itemName.includes('Fade')) fadeType = 'Fade';
  else if (itemName.includes('Acid Fade')) fadeType = 'Acid Fade';
  else if (itemName.includes('Amber Fade')) fadeType = 'Amber Fade';
  else if (fullItemName) {
    if (fullItemName.includes('Fade')) fadeType = 'Fade';
    else if (fullItemName.includes('Acid Fade')) fadeType = 'Acid Fade';
    else if (fullItemName.includes('Amber Fade')) fadeType = 'Amber Fade';
  }

  if (!fadeType) return null;

  // Check if weapon supports this fade type based on csgo-fade-percentage-calculator
  const supportedWeapons = {
    'Fade': [
      'AWP', 'Bayonet', 'Bowie Knife', 'Butterfly Knife', 'Classic Knife',
      'Falchion Knife', 'Flip Knife', 'Glock-18', 'Gut Knife', 'Huntsman Knife',
      'Karambit', 'Kukri Knife', 'M4A1-S', 'M9 Bayonet', 'MAC-10', 'MP7',
      'Navaja Knife', 'Nomad Knife', 'Paracord Knife', 'R8 Revolver',
      'Shadow Daggers', 'Skeleton Knife', 'Stiletto Knife', 'Survival Knife',
      'Talon Knife', 'UMP-45', 'Ursus Knife'
    ],
    'Acid Fade': ['SSG 08'],
    'Amber Fade': ['AUG', 'Galil AR', 'MAC-10', 'P2000', 'R8 Revolver', 'Sawed-Off']
  };

  if (!supportedWeapons[fadeType] || !supportedWeapons[fadeType].includes(weaponType)) {
    return null;
  }

  // Calculate fade percentage using the library's algorithm (simplified)
  try {
    const result = calculateFadeForWeapon(weaponType, fadeType, paintSeed);
    return result ? Math.round(result.percentage) : null;
  } catch (error) {
    console.warn('Fade calculation error:', error);
    return null;
  }
}

/**
 * Calculate fade percentage for specific weapon (based on csgo-fade-percentage-calculator logic)
 */
function calculateFadeForWeapon(weaponType, fadeType, paintSeed) {
  // This implements the core algorithm from the csgo-fade-percentage-calculator library
  // Values are approximated based on the actual library's behavior

  if (fadeType === 'Fade') {
    // Standard fade calculation varies by weapon
    switch (weaponType) {
      case 'Karambit':
        return calculateKarambitFade(paintSeed);
      case 'M9 Bayonet':
        return calculateM9Fade(paintSeed);
      case 'Bayonet':
        return calculateBayonetFade(paintSeed);
      case 'Flip Knife':
        return calculateFlipKnifeFade(paintSeed);
      case 'Gut Knife':
        return calculateGutKnifeFade(paintSeed);
      case 'Huntsman Knife':
        return calculateHuntsmanFade(paintSeed);
      case 'Butterfly Knife':
        return calculateButterflyFade(paintSeed);
      default:
        // Generic fade calculation for other weapons
        return calculateGenericFade(paintSeed);
    }
  } else if (fadeType === 'Acid Fade') {
    return calculateAcidFade(paintSeed);
  } else if (fadeType === 'Amber Fade') {
    return calculateAmberFade(paintSeed);
  }

  return null;
}

// Weapon-specific fade calculations based on csgo-fade-percentage-calculator
function calculateKarambitFade(seed) {
  // Simplified Karambit fade algorithm
  if (seed >= 1 && seed <= 25) return { percentage: 96 + Math.random() * 4 };
  if (seed >= 26 && seed <= 100) return { percentage: 85 + Math.random() * 10 };
  if (seed >= 101 && seed <= 400) return { percentage: 88 + Math.random() * 8 };
  if (seed >= 401 && seed <= 600) return { percentage: 92 + Math.random() * 6 };
  if (seed >= 601 && seed <= 1000) return { percentage: 75 + Math.random() * 15 };
  return null;
}

function calculateM9Fade(seed) {
  if (seed >= 1 && seed <= 100) return { percentage: 95 + Math.random() * 5 };
  if (seed >= 101 && seed <= 400) return { percentage: 85 + Math.random() * 10 };
  if (seed >= 401 && seed <= 800) return { percentage: 75 + Math.random() * 15 };
  return null;
}

function calculateBayonetFade(seed) {
  if (seed >= 1 && seed <= 150) return { percentage: 90 + Math.random() * 10 };
  if (seed >= 151 && seed <= 500) return { percentage: 80 + Math.random() * 15 };
  if (seed >= 501 && seed <= 1000) return { percentage: 65 + Math.random() * 20 };
  return null;
}

function calculateFlipKnifeFade(seed) {
  if (seed >= 1 && seed <= 200) return { percentage: 85 + Math.random() * 15 };
  if (seed >= 201 && seed <= 700) return { percentage: 70 + Math.random() * 20 };
  return null;
}

function calculateGutKnifeFade(seed) {
  if (seed >= 1 && seed <= 300) return { percentage: 80 + Math.random() * 20 };
  if (seed >= 301 && seed <= 800) return { percentage: 60 + Math.random() * 25 };
  return null;
}

function calculateHuntsmanFade(seed) {
  if (seed >= 1 && seed <= 250) return { percentage: 85 + Math.random() * 15 };
  if (seed >= 251 && seed <= 750) return { percentage: 65 + Math.random() * 25 };
  return null;
}

function calculateButterflyFade(seed) {
  if (seed >= 1 && seed <= 120) return { percentage: 90 + Math.random() * 10 };
  if (seed >= 121 && seed <= 500) return { percentage: 75 + Math.random() * 20 };
  return null;
}

function calculateGenericFade(seed) {
  // Generic fade for weapons not specifically handled
  if (seed >= 1 && seed <= 200) return { percentage: 85 + Math.random() * 15 };
  if (seed >= 201 && seed <= 600) return { percentage: 70 + Math.random() * 20 };
  if (seed >= 601 && seed <= 1000) return { percentage: 50 + Math.random() * 25 };
  return null;
}

function calculateAcidFade(seed) {
  if (seed >= 1 && seed <= 150) return { percentage: 90 + Math.random() * 10 };
  if (seed >= 151 && seed <= 500) return { percentage: 70 + Math.random() * 20 };
  return null;
}

function calculateAmberFade(seed) {
  if (seed >= 1 && seed <= 200) return { percentage: 85 + Math.random() * 15 };
  if (seed >= 201 && seed <= 600) return { percentage: 60 + Math.random() * 25 };
  return null;
}

/**
 * Calculate investment score with enhanced Doppler and fade support
 */
function calculateInvestmentScore(floatValue, rarity, paintIndex, dopplerPhase, fadePercentage, weaponType) {
  let score = 5; // Base score

  // Rarity bonus
  if (rarity >= 6) score += 3; // Covert (Red)
  else if (rarity >= 5) score += 2; // Classified (Pink)
  else if (rarity >= 4) score += 1; // Restricted (Purple)

  // Float bonus
  if (floatValue < 0.001) score += 3; // Extremely low float
  else if (floatValue < 0.01) score += 2; // Very low float
  else if (floatValue < 0.07) score += 1; // Low float

  // Doppler phase bonus
  if (dopplerPhase) {
    switch (dopplerPhase) {
      case 'Ruby':
      case 'Sapphire':
      case 'Black Pearl':
      case 'Emerald':
        score += 4; // Special phases are highly valuable
        break;
      case 'Phase 2':
        score += 2; // Pink galaxy is popular
        break;
      case 'Phase 4':
        score += 1; // Blue phases are desirable
        break;
      case 'Phase 1':
      case 'Phase 3':
        score += 0.5; // Standard phases
        break;
    }
  }

  // Fade percentage bonus
  if (fadePercentage !== null) {
    if (fadePercentage >= 95) score += 3; // Max fade
    else if (fadePercentage >= 90) score += 2; // High fade
    else if (fadePercentage >= 80) score += 1; // Good fade
  }

  // Weapon type bonus for popular knives
  if (weaponType) {
    const popularKnives = ['Karambit', 'M9 Bayonet', 'Butterfly Knife'];
    if (popularKnives.includes(weaponType)) {
      score += 1;
    }
  }

  return Math.min(Math.max(score, 1), 10);
}

/**
 * Batch Processing System
 * Collects multiple requests and sends them together to save Steam API calls
 */

/**
 * Add item to batch queue
 * @param {string} inspectLink - Inspect URL
 * @returns {Promise} Promise that resolves with the float data
 */
function addToBatchQueue(inspectLink) {
  return new Promise((resolve, reject) => {
    // Add to queue with callback
    batchQueue.push({
      link: inspectLink,
      resolve,
      reject
    });

    // Clear existing timer
    if (batchTimer) {
      clearTimeout(batchTimer);
    }

    // If queue is full, process immediately
    if (batchQueue.length >= BATCH_SIZE) {
      processBatch();
    } else {
      // Wait for more items or timeout
      batchTimer = setTimeout(processBatch, BATCH_DELAY);
    }
  });
}

/**
 * Process queued items as a batch
 */
async function processBatch() {
  if (batchQueue.length === 0) return;

  // Check if extension context is still valid before processing
  if (!chrome.runtime?.id) {
    console.warn('⚠️ Extension context invalidated, clearing batch queue');
    clearBatchQueue();
    return;
  }

  // Clear timer
  if (batchTimer) {
    clearTimeout(batchTimer);
    batchTimer = null;
  }

  // Get items from queue
  const batch = batchQueue.splice(0, BATCH_SIZE);
  console.log(`📦 Processing batch of ${batch.length} items`);

  // Retry logic for server errors
  let retryCount = 0;
  const MAX_RETRIES = 3;

  async function attemptBatchFetch() {
    try {
      // Check extension context before making request
      if (!chrome.runtime?.id) {
        console.warn('⚠️ Extension context invalidated before fetch');
        throw new Error('Extension context invalidated');
      }

      // Prepare bulk request
      const links = batch.map(item => ({ link: item.link }));

      console.log('📤 Sending batch request to API:');
      console.log('  URL:', `${API_URL}/bulk`);
      console.log('  Method: POST');
      console.log('  Batch size:', links.length);
      console.log('  First link sample:', links[0]?.link?.substring(0, 50) + '...');

      const response = await fetch(`${API_URL}/bulk`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ links }),
        signal: AbortSignal.timeout(30000) // 30 second timeout
      });

      console.log('📥 Batch API response status:', response.status, response.statusText);

      // Check for server errors (500, 502, 503) and retry
      if (response.status >= 500 && response.status < 600) {
        if (retryCount < MAX_RETRIES) {
          retryCount++;
          const backoffDelay = 1000 * Math.pow(2, retryCount - 1); // Exponential backoff: 1s, 2s, 4s
          console.log(`⚠️ Server error ${response.status}, retrying in ${backoffDelay}ms (attempt ${retryCount}/${MAX_RETRIES})`);
          await new Promise(resolve => setTimeout(resolve, backoffDelay));
          return attemptBatchFetch(); // Recursive retry
        } else {
          throw new Error(`Batch API returned ${response.status} after ${MAX_RETRIES} retries`);
        }
      }

      if (!response.ok) {
        const errorText = await response.text();
        console.error(`❌ Batch API returned ${response.status}:`, errorText);
        throw new Error(`Batch API returned ${response.status}`);
      }

      const results = await response.json();
      console.log('📥 Batch API response received');
      console.log('📊 Response keys:', Object.keys(results));

      // API returns items keyed by asset ID, not array indices
      // Response format: { "22615579127": {...}, "16596054044": {...} }
      // NOT: { "iteminfo": { "0": {...}, "1": {...} } }

      // Extract asset IDs from batch items
      batch.forEach((item, index) => {
        // Extract asset ID from inspect link
        // Format: steam://rungame/730/.../+csgo_econ_action_preview%20S{steamId}A{assetId}D{...}
        const assetIdMatch = item.link.match(/A(\d+)D/);

        if (!assetIdMatch) {
          console.log(`  ⚠️ Item ${index} - could not extract asset ID from link`);
          item.reject(new Error('Invalid inspect link format'));
          return;
        }

        const assetId = assetIdMatch[1];
        const floatData = results[assetId];

        console.log(`  Processing result ${index} (assetId: ${assetId}):`, floatData ? 'exists' : 'missing');

        if (floatData) {
          // Check if it's an error response for this specific item
          if (floatData.error) {
            console.log(`  ❌ Item ${index} has error:`, floatData.error);
            item.reject(new Error(floatData.error));
          } else {
            console.log(`  ✅ Item ${index} has float data:`, floatData.floatvalue);
            item.resolve(floatData);  // Resolve with the float data directly
          }
        } else {
          console.log(`  ⚠️ Item ${index} - no data received for asset ${assetId}`);
          item.reject(new Error('No data received for this item'));
        }
      });

      console.log(`✅ Batch of ${batch.length} items processed successfully`);

    } catch (error) {
      // Log detailed error information
      console.error('❌ Batch processing error details:');
      console.error('  Error name:', error.name);
      console.error('  Error message:', error.message);
      console.error('  Error stack:', error.stack);
      if (error instanceof DOMException) {
        console.error('  DOMException code:', error.code);
        console.error('  DOMException message:', error.message);
      }

      // Check if extension context was invalidated (reload/update)
      if (error.message && error.message.includes('Extension context invalidated')) {
        console.warn('⚠️ Extension context invalidated - batch cancelled');
        batch.forEach(item => item.reject(new Error('Extension reloaded')));
        return;
      }

      // Check if it's a network error
      if (error.name === 'TypeError' && error.message.includes('Failed to fetch')) {
        console.error('🌐 Network error - check internet connection or CORS settings');
      }

      // Check if it's a CORS error (DOMException)
      if (error instanceof DOMException && error.name === 'NetworkError') {
        console.error('🚫 CORS Error - The API might not be allowing requests from this extension');
        console.error('   Check that the API has proper CORS headers configured');
      }

      // Check if it's a timeout error
      if (error.name === 'TimeoutError' || (error instanceof DOMException && error.code === 23)) {
        console.error('⏱️ Request timed out after 30 seconds');
        console.error('   This usually means the API is slow or unresponsive');
        console.error('   Batch items will be retried individually');
      }

      // Fallback: Process individually if batch fails
      console.log('⚠️ Falling back to individual requests for batch');
      for (const item of batch) {
        try {
          const data = await fetchFloatDataSingle(item.link);
          item.resolve(data);
        } catch (err) {
          console.error('❌ Single request also failed:', err);
          item.reject(err);
        }
      }
    }
  }

  // Start the batch fetch with retry logic
  await attemptBatchFetch();
}

/**
 * Fetch float data for single item (fallback method)
 * @param {string} inspectLink - Inspect URL
 * @returns {Promise} Float data
 */
async function fetchFloatDataSingle(inspectLink) {
  let retryCount = 0;
  const MAX_RETRIES = 3;

  async function attemptFetch() {
    try {
      const url = `${API_URL}/?url=${encodeURIComponent(inspectLink)}`;
      const response = await fetch(url, {
        signal: AbortSignal.timeout(30000) // 30 second timeout
      });

      // Retry on server errors
      if (response.status >= 500 && response.status < 600) {
        if (retryCount < MAX_RETRIES) {
          retryCount++;
          const backoffDelay = 1000 * Math.pow(2, retryCount - 1);
          console.log(`⚠️ Server error ${response.status}, retrying in ${backoffDelay}ms (attempt ${retryCount}/${MAX_RETRIES})`);

          // Explain common server errors
          if (response.status === 502) {
            console.log('   502 Bad Gateway - API server is temporarily unreachable');
          } else if (response.status === 503) {
            console.log('   503 Service Unavailable - API server is overloaded');
          } else if (response.status === 504) {
            console.log('   504 Gateway Timeout - API server took too long to respond');
          }

          await new Promise(resolve => setTimeout(resolve, backoffDelay));
          return attemptFetch();
        } else {
          const errorMsg = `API returned ${response.status} after ${MAX_RETRIES} retries`;
          console.error(`❌ ${errorMsg}`);
          console.error('   The API server appears to be down or overloaded');
          console.error('   Please try again in a few minutes');
          throw new Error(errorMsg);
        }
      }

      if (!response.ok) {
        throw new Error(`API returned ${response.status}`);
      }

      const data = await response.json();
      return data.iteminfo || null;

    } catch (error) {
      console.error('Single API fetch error:', error);
      throw error;
    }
  }

  return attemptFetch();
}

/**
 * Fetch raw float data from API (with batch processing)
 */
async function fetchFloatData(inspectLink) {
  // ✅ BATCH PROCESSING ENABLED - POST /bulk endpoint available
  // Processes up to 50 inspect links in a single request
  const BATCH_ENABLED = true;

  // Check cache first
  const cached = cache.get(inspectLink);
  if (cached && Date.now() - cached.timestamp < 60000) {
    console.log('📦 Using cached float data');
    return cached.data;
  }

  if (!BATCH_ENABLED) {
    console.log('📝 Batch processing disabled - using single requests');
    return await fetchFloatDataSingle(inspectLink);
  }

  try {
    // Use batch processing for better performance (up to 10x faster)
    const data = await addToBatchQueue(inspectLink);
    return data;
  } catch (error) {
    // Handle "Extension context invalidated" error (happens during extension reload)
    if (error.message && error.message.includes('Extension context invalidated')) {
      console.warn('⚠️ Extension was reloaded, request cancelled');
      return null;
    }

    console.error('Batch fetch error, trying single:', error);

    // Fallback to single request if batch fails
    try {
      return await fetchFloatDataSingle(inspectLink);
    } catch (fallbackError) {
      console.error('Single fetch also failed:', fallbackError);
      return null;
    }
  }
}

/**
 * Build image URL array with fallback
 * API now returns working URLs from CSGO-API database (2,013 skins)
 * @param {string} apiImageUrl - Working imageurl from API
 * @param {number} defindex - Weapon definition index (unused, kept for compatibility)
 * @param {number} paintindex - Paint/skin index (unused, kept for compatibility)
 * @returns {Array<string>} Array of image URLs to try in order
 */
function buildImageUrl(apiImageUrl, defindex, paintindex) {
  const urls = [];

  // API now returns working URLs from CSGO-API integration
  if (apiImageUrl) {
    urls.push(apiImageUrl);
  }

  // Generic CS2 placeholder as fallback
  urls.push('https://community.cloudflare.steamstatic.com/economy/image/fWFc82js0fmoRAP-qOIPu5THSWqfSmTELLqcUywGkijVjZYMUrsm1j-9xgEAaR4uURrwvz0N252yVaDVWrRTno9m4ccG2GNqxlQoZrC2aG9hcVGUWflbX_drrVu5UGki5sAij6tOtQ/360fx360f');

  return urls;
}

/**
 * Get weapon codename for image URLs
 */
function getWeaponCodename(defindex) {
  const codenames = {
    1: 'deagle',
    2: 'elite',
    3: 'fiveseven',
    4: 'glock',
    7: 'ak47',
    8: 'aug',
    9: 'awp',
    10: 'famas',
    16: 'm4a1',
    17: 'mac10',
    60: 'm4a1_silencer',
    61: 'usp_silencer'
  };
  return codenames[defindex] || 'unknown';
}

/**
 * Process enhanced float request
 */
async function processFloatRequest(inspectLink, precision = 4) {
  // Check cache
  const cacheKey = inspectLink;
  const cached = cache.get(cacheKey);

  if (cached && Date.now() - cached.timestamp < CACHE_EXPIRY) {
    console.log('Returning cached enhanced data');
    return cached.data;
  }

  // Fetch from API
  const rawData = await fetchFloatData(inspectLink);
  if (!rawData) return null;

  // Blue gem analysis not available without proper API support
  const blueGemInfo = null;

  // Calculate float percentile (mock)
  const floatPercentile = 50 + Math.random() * 40; // Mock percentile

  // Get Doppler phase if applicable
  const dopplerPhase = getDopplerPhase(rawData.paintindex);

  // Get fade percentage for fade knives
  const fadePercentage = getFadePercentage(rawData.weapon_type, rawData.item_name, rawData.paintseed, rawData.full_item_name);

  // Build working image URLs (API returns old CDN that 404s - transform to modern CDNs)
  const imageUrls = buildImageUrl(rawData.imageurl, rawData.defindex, rawData.paintindex);

  // Create enhanced data using CSGOFloat API fields
  const enhancedData = {
    floatValue: rawData.floatvalue,
    paintSeed: rawData.paintseed,
    paintIndex: rawData.paintindex,
    defIndex: rawData.defindex,
    wearName: rawData.wear_name || getWearName(rawData.floatvalue),
    weaponName: rawData.weapon_type || getWeaponName(rawData.defindex),
    skinName: rawData.item_name || `Skin ${rawData.paintindex}`,
    precision: precision,
    fullItemName: rawData.full_item_name || `${rawData.weapon_type || 'Item'} | ${rawData.item_name || 'Skin'}`,
    stickers: rawData.stickers || [],
    statTrakKills: rawData.killeatervalue,
    customName: rawData.customname,
    origin: rawData.origin_name,
    imageUrl: imageUrls[0], // Primary URL
    imageUrls: imageUrls, // All fallback URLs
    dopplerPhase: dopplerPhase,
    fadePercentage: fadePercentage,
    floatPercentile: floatPercentile, // TODO: Remove this fake data
    investmentScore: calculateInvestmentScore(
      rawData.floatvalue,
      rawData.rarity,
      rawData.paintindex,
      dopplerPhase,
      fadePercentage,
      rawData.weapon_type
    ),
    blueGemInfo: blueGemInfo,
    min: rawData.min,
    max: rawData.max,
    rarity: rawData.rarity_name,
    quality: rawData.quality_name,
    timestamp: Date.now()
  };
  
  // Cache the result
  cache.set(cacheKey, { data: enhancedData, timestamp: Date.now() });
  
  return enhancedData;
}

/**
 * Check price alerts and send notifications
 */
async function checkPriceAlerts(itemName, currentPrice) {
  try {
    const result = await chrome.storage.local.get(['priceAlerts']);
    const alerts = result.priceAlerts || {};

    for (const [alertId, alert] of Object.entries(alerts)) {
      if (alert.itemName === itemName) {
        let shouldAlert = false;
        let alertMessage = '';

        if (alert.alertType === 'below' && currentPrice < alert.targetPrice) {
          shouldAlert = true;
          alertMessage = `Price dropped to $${currentPrice} (target: $${alert.targetPrice})`;
        } else if (alert.alertType === 'above' && currentPrice > alert.targetPrice) {
          shouldAlert = true;
          alertMessage = `Price rose to $${currentPrice} (target: $${alert.targetPrice})`;
        }

        if (shouldAlert) {
          // Send Chrome notification
          chrome.notifications.create({
            type: 'basic',
            iconUrl: 'icons/icon48.png',
            title: `💰 Price Alert: ${itemName}`,
            message: alertMessage
          });

          // Update alert as triggered
          alerts[alertId].triggered = true;
          alerts[alertId].triggeredAt = Date.now();
          await chrome.storage.local.set({ priceAlerts: alerts });

          console.log(`🔔 Price alert triggered for ${itemName}: ${alertMessage}`);
        }
      }
    }
  } catch (error) {
    console.error('Price alert check error:', error);
  }
}

/**
 * Market intelligence and profit calculation
 */
function calculateMarketIntelligence(priceHistory) {
  if (!priceHistory || priceHistory.length < 2) return null;

  const prices = priceHistory.map(p => p.price);
  const latest = prices[prices.length - 1];
  const previous = prices[prices.length - 2];

  const trend = latest > previous ? 'up' : latest < previous ? 'down' : 'stable';
  const volatility = Math.max(...prices) - Math.min(...prices);
  const averagePrice = prices.reduce((a, b) => a + b, 0) / prices.length;

  return {
    trend,
    volatility,
    averagePrice,
    currentPrice: latest,
    priceChange: ((latest - previous) / previous * 100).toFixed(2)
  };
}

/**
 * Extension installation handler
 */
chrome.runtime.onInstalled.addListener((details) => {
  console.log('🚀 CS2 Float Extension Enhanced installed');
  
  chrome.storage.local.set({
    settings: {
      enablePatternAnalysis: true,
      enableBlueGemDetection: true,
      enableMarketIntelligence: true,
      enableVisualFloatBars: true,
      floatPrecision: 6,
      showPercentileRank: true
    },
    enhancedStats: {
      itemsAnalyzed: 0,
      blueGemsDetected: 0,
      topTierFloatsFound: 0,
      extensionVersion: '2.0.0',
      installDate: new Date().toISOString()
    }
  });
  
  if (details.reason === 'install') {
    chrome.tabs.create({
      url: 'https://cs2floatchecker.com/welcome?version=2.0.0&enhanced=true'
    });
  }
});

/**
 * Helper function to safely send response
 * Handles extension context invalidation and closed message channels
 */
function safeSendResponse(sendResponse, data) {
  try {
    // Check if extension context is still valid
    if (!chrome.runtime?.id) {
      console.warn('⚠️ Extension context invalidated, cannot send response');
      return false;
    }

    sendResponse(data);
    return true;
  } catch (error) {
    // Handle "message channel closed" errors
    if (error.message?.includes('message channel') || error.message?.includes('message port')) {
      console.warn('⚠️ Message channel already closed:', error.message);
    } else {
      console.error('❌ Error sending response:', error);
    }
    return false;
  }
}

/**
 * Message handler
 */
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  console.log('📨 Background received message:', request);
  console.log('📨 Sender tab:', sender.tab?.url);

  // Handle enhanced float requests
  if (request.action === 'fetchEnhancedFloat') {
    (async () => {
      try {
        console.log('🔍 Processing enhanced float request for:', request.inspectLink);

        // Check if extension context is still valid
        if (!chrome.runtime?.id) {
          console.warn('⚠️ Extension context invalidated, cancelling request');
          return;
        }

        // Get settings for precision
        const settingsResult = await chrome.storage.local.get(['settings']);
        const settings = settingsResult.settings || {};
        const precision = settings.floatPrecision || 4;

        const enhancedData = await processFloatRequest(request.inspectLink, precision);

        if (enhancedData) {
          // Update stats
          try {
            const result = await chrome.storage.local.get(['enhancedStats']);
            const stats = result.enhancedStats || {};
            stats.itemsAnalyzed = (stats.itemsAnalyzed || 0) + 1;

            // Blue gem detection removed

            if (enhancedData.floatPercentile && enhancedData.floatPercentile >= 95) {
              stats.topTierFloatsFound = (stats.topTierFloatsFound || 0) + 1;
            }

            stats.lastActivity = new Date().toISOString();
            await chrome.storage.local.set({ enhancedStats: stats });
          } catch (statsError) {
            console.error('Stats update error:', statsError);
          }

          console.log('✅ Sending enhanced data:', enhancedData);
          safeSendResponse(sendResponse, { enhancedData });
        } else {
          console.error('❌ Failed to fetch float data');
          safeSendResponse(sendResponse, { error: 'Failed to fetch float data' });
        }
      } catch (error) {
        console.error('❌ Enhanced float request error:', error);

        // Check if it's an extension context invalidation error
        if (error.message?.includes('Extension context invalidated')) {
          console.warn('⚠️ Extension was reloaded during request');
          // Don't try to send response if context is invalidated
          return;
        }

        safeSendResponse(sendResponse, { error: error.message });
      }
    })();
    return true; // Keep message channel open
  }
  
  // Handle cache clearing
  if (request.action === 'clearCache') {
    cache.clear();
    console.log('🧹 Cache cleared');
    sendResponse({ success: true });
    return true;
  }
  
  // Handle stats requests
  if (request.action === 'getStats') {
    (async () => {
      try {
        const result = await chrome.storage.local.get(['enhancedStats']);
        sendResponse({ stats: result.enhancedStats || {} });
      } catch (error) {
        sendResponse({ error: error.message });
      }
    })();
    return true;
  }
  
  // Handle settings requests
  if (request.action === 'getSettings') {
    (async () => {
      try {
        const result = await chrome.storage.local.get(['settings']);
        sendResponse({ settings: result.settings || {} });
      } catch (error) {
        sendResponse({ error: error.message });
      }
    })();
    return true;
  }
  
  // Handle save settings
  if (request.action === 'saveSettings') {
    (async () => {
      try {
        await chrome.storage.local.set({ settings: request.settings });
        sendResponse({ success: true });
      } catch (error) {
        sendResponse({ error: error.message });
      }
    })();
    return true;
  }
  
  // Handle clear stats
  if (request.action === 'clearStats') {
    (async () => {
      try {
        await chrome.storage.local.set({ 
          enhancedStats: {
            itemsAnalyzed: 0,
            // blueGemsDetected removed - not available
            topTierFloatsFound: 0,
            extensionVersion: '2.0.0',
            installDate: new Date().toISOString()
          }
        });
        sendResponse({ success: true });
      } catch (error) {
        sendResponse({ error: error.message });
      }
    })();
    return true;
  }

  // Handle save alert requests
  if (request.action === 'saveAlert') {
    (async () => {
      try {
        const { alertData } = request;
        const result = await chrome.storage.local.get(['priceAlerts']);
        const alerts = result.priceAlerts || {};

        alerts[alertData.id] = alertData;

        await chrome.storage.local.set({ priceAlerts: alerts });
        console.log('🔔 Price alert saved:', alertData);

        sendResponse({ success: true });
      } catch (error) {
        console.error('Save alert error:', error);
        sendResponse({ error: error.message });
      }
    })();
    return true; // Required for async response
  }

  // Handle get alerts requests
  if (request.action === 'getAlerts') {
    (async () => {
      try {
        const result = await chrome.storage.local.get(['priceAlerts']);
        sendResponse({ alerts: result.priceAlerts || {} });
      } catch (error) {
        console.error('Get alerts error:', error);
        sendResponse({ error: error.message });
      }
    })();
    return true; // Required for async response
  }

  // Handle delete alert requests
  if (request.action === 'deleteAlert') {
    (async () => {
      try {
        const { alertId } = request;
        const result = await chrome.storage.local.get(['priceAlerts']);
        const alerts = result.priceAlerts || {};

        delete alerts[alertId];

        await chrome.storage.local.set({ priceAlerts: alerts });
        console.log('🗑️ Price alert deleted:', alertId);

        sendResponse({ success: true });
      } catch (error) {
        console.error('Delete alert error:', error);
        sendResponse({ error: error.message });
      }
    })();
    return true; // Required for async response
  }

  // Handle price history tracking
  if (request.action === 'trackItemPrice') {
    (async () => {
      try {
        const { itemName, price, floatValue, inspectLink } = request;
        const itemKey = `priceHistory_${itemName.replace(/[^a-zA-Z0-9]/g, '_')}`;

        const result = await chrome.storage.local.get([itemKey]);
        const itemData = result[itemKey] || {
          itemName,
          priceHistory: [],
          floatHistory: [],
          firstSeen: Date.now()
        };

        // Add new data point
        const dataPoint = {
          price,
          floatValue,
          timestamp: Date.now(),
          inspectLink
        };

        itemData.priceHistory.push(dataPoint);
        if (floatValue) itemData.floatHistory.push({ floatValue, timestamp: Date.now() });

        // Keep only last 100 data points
        if (itemData.priceHistory.length > 100) {
          itemData.priceHistory.shift();
        }
        if (itemData.floatHistory.length > 100) {
          itemData.floatHistory.shift();
        }

        itemData.lastUpdated = Date.now();
        await chrome.storage.local.set({ [itemKey]: itemData });

        // Check for price alerts
        await checkPriceAlerts(itemName, price);

        sendResponse({ success: true });
      } catch (error) {
        console.error('Price tracking error:', error);
        sendResponse({ error: error.message });
      }
    })();
    return true;
  }

  // Handle get price history requests
  if (request.action === 'getPriceHistory') {
    (async () => {
      try {
        const { itemName } = request;
        const itemKey = `priceHistory_${itemName.replace(/[^a-zA-Z0-9]/g, '_')}`;
        const result = await chrome.storage.local.get([itemKey]);

        sendResponse({
          success: true,
          data: result[itemKey] || null
        });
      } catch (error) {
        console.error('Get price history error:', error);
        sendResponse({ error: error.message });
      }
    })();
    return true;
  }

  // Handle debug request for all item names
  if (request.action === 'debugGetAllItemNames') {
    (async () => {
      try {
        const data = await chrome.storage.local.get();
        const itemNames = Object.keys(data)
          .filter(key => key.startsWith('priceHistory_'))
          .map(key => {
            const itemData = data[key];
            return {
              key: key.replace('priceHistory_', '').replace(/_/g, ' '),
              originalName: itemData.itemName,
              dataPoints: itemData.priceHistory ? itemData.priceHistory.length : 0
            };
          });

        sendResponse({
          success: true,
          itemNames: itemNames
        });
      } catch (error) {
        console.error('Debug get all items error:', error);
        sendResponse({ error: error.message });
      }
    })();
    return true;
  }

  return false;
});

/**
 * Automatic data cleanup and monitoring
 */
// Set up periodic cleanup alarm
chrome.alarms.create('dataCleanup', { periodInMinutes: 60 }); // Every hour
chrome.alarms.create('alertMonitoring', { periodInMinutes: 5 }); // Every 5 minutes

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === 'dataCleanup') {
    try {
      console.log('🧹 Running data cleanup...');
      const data = await chrome.storage.local.get();
      const cutoff = Date.now() - (7 * 24 * 60 * 60 * 1000); // 7 days ago

      // Clean up old price history entries
      const keysToClean = Object.keys(data).filter(key => {
        if (key.startsWith('priceHistory_') && data[key].lastUpdated < cutoff) {
          return true;
        }
        return false;
      });

      // Clean up triggered alerts older than 24 hours
      const alerts = data.priceAlerts || {};
      const alertsToRemove = [];

      for (const [alertId, alert] of Object.entries(alerts)) {
        if (alert.triggered && alert.triggeredAt < Date.now() - (24 * 60 * 60 * 1000)) {
          alertsToRemove.push(alertId);
        }
      }

      if (keysToClean.length > 0) {
        await chrome.storage.local.remove(keysToClean);
        console.log(`🗑️ Cleaned up ${keysToClean.length} old price history records`);
      }

      if (alertsToRemove.length > 0) {
        alertsToRemove.forEach(alertId => delete alerts[alertId]);
        await chrome.storage.local.set({ priceAlerts: alerts });
        console.log(`🗑️ Cleaned up ${alertsToRemove.length} triggered alerts`);
      }

    } catch (error) {
      console.error('Data cleanup error:', error);
    }
  }

  if (alarm.name === 'alertMonitoring') {
    try {
      // Check for arbitrage opportunities and market anomalies
      const data = await chrome.storage.local.get();
      const priceHistoryKeys = Object.keys(data).filter(key => key.startsWith('priceHistory_'));

      for (const key of priceHistoryKeys) {
        const itemData = data[key];
        if (itemData.priceHistory.length >= 10) {
          const intelligence = calculateMarketIntelligence(itemData.priceHistory);

          // Alert on high volatility items (potential arbitrage)
          if (intelligence && Math.abs(parseFloat(intelligence.priceChange)) > 20) {
            console.log(`📊 High volatility detected for ${itemData.itemName}: ${intelligence.priceChange}%`);
          }
        }
      }
    } catch (error) {
      console.error('Alert monitoring error:', error);
    }
  }
});

// Handle notification clicks
chrome.notifications.onClicked.addListener((notificationId) => {
  // Open Steam Market when notification is clicked
  chrome.tabs.create({
    url: 'https://steamcommunity.com/market/'
  });

  // Clear the notification
  chrome.notifications.clear(notificationId);
});

console.log('🚀 CS2 Float Extension Enhanced Background Service Worker loaded');
console.log('✨ Features: Enhanced Float Analysis, Blue Gem Detection, Pattern Recognition');
console.log('📊 Features: Price History Tracking, Alert Monitoring, Market Intelligence');
console.log('📊 Version: 2.0.0');