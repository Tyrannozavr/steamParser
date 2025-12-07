/**
 * Скрипт для перехвата fetch запросов в background script расширения
 * 
 * ИНСТРУКЦИЯ:
 * 1. Откройте chrome://extensions/
 * 2. Найдите "CS2 Float Checker"
 * 3. Нажмите "Inspect views: background page" или "service worker"
 * 4. Откройте DevTools для background script
 * 5. Перейдите на вкладку Console
 * 6. Вставьте этот код и нажмите Enter
 * 7. Обновите страницу Steam Market
 * 8. Смотрите вывод в консоли background script
 */

(function() {
    console.log('🔍 Перехватчик fetch для background script активирован!');
    console.log('📋 Обновите страницу Steam Market, чтобы увидеть запросы\n');

    // Перехватываем fetch в background script
    const originalFetch = self.fetch || window.fetch;
    
    if (originalFetch) {
        const fetchWrapper = function(...args) {
            const url = args[0];
            const options = args[1] || {};
            
            // Фильтруем только интересующие нас запросы
            const urlString = typeof url === 'string' ? url : url.toString();
            const isInteresting = urlString.includes('api') || 
                                 urlString.includes('float') || 
                                 urlString.includes('inspect') ||
                                 urlString.includes('paintseed') ||
                                 urlString.includes('cs2floatchecker');
            
            if (isInteresting) {
                console.group('🔵 BACKGROUND SCRIPT FETCH');
                console.log('📍 URL:', urlString);
                console.log('📤 Method:', options.method || 'GET');
                
                if (options.headers) {
                    console.log('📋 Headers:');
                    if (options.headers instanceof Headers) {
                        options.headers.forEach((value, key) => {
                            console.log(`   ${key}: ${value}`);
                        });
                    } else {
                        Object.entries(options.headers).forEach(([key, value]) => {
                            console.log(`   ${key}: ${value}`);
                        });
                    }
                }
                
                if (options.body) {
                    console.log('📦 Body:', options.body);
                    try {
                        const bodyObj = typeof options.body === 'string' ? JSON.parse(options.body) : options.body;
                        console.log('📦 Body (parsed):', bodyObj);
                    } catch (e) {
                        // Не JSON
                    }
                }
                
                console.groupEnd();
            }
            
            return originalFetch.apply(this, args).then(response => {
                if (isInteresting) {
                    console.group('✅ BACKGROUND SCRIPT RESPONSE');
                    console.log('📍 URL:', urlString);
                    console.log('📊 Status:', response.status, response.statusText);
                    
                    // Клонируем response для чтения
                    response.clone().json().then(data => {
                        console.log('📦 Response Data:', data);
                        
                        // Проверяем наличие paintSeed
                        const dataStr = JSON.stringify(data).toLowerCase();
                        if (dataStr.includes('paintseed') || dataStr.includes('paint_seed')) {
                            console.log('🎯 ✅ НАЙДЕН PAINTSEED (PATTERN)!');
                            console.log('   Полные данные:', JSON.stringify(data, null, 2));
                        }
                        if (dataStr.includes('floatvalue') || dataStr.includes('float_value')) {
                            console.log('🎯 ✅ НАЙДЕН FLOAT!');
                        }
                    }).catch(() => {
                        response.clone().text().then(text => {
                            console.log('📦 Response Text:', text.substring(0, 500));
                        });
                    });
                    
                    console.groupEnd();
                }
                return response;
            }).catch(error => {
                if (isInteresting) {
                    console.error('❌ BACKGROUND SCRIPT FETCH ERROR:', error);
                }
                throw error;
            });
        };
        
        // Заменяем fetch
        if (self.fetch) {
            self.fetch = fetchWrapper;
        }
        if (window.fetch) {
            window.fetch = fetchWrapper;
        }
        
        console.log('✅ Перехватчик установлен! Теперь обновите страницу Steam Market.');
        console.log('💡 Все запросы к API будут показаны в консоли background script');
    } else {
        console.error('❌ Fetch не найден в этом контексте');
    }
})();

