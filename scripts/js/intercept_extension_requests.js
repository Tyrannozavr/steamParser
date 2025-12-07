/**
 * Скрипт для перехвата запросов расширения CS2 Float Checker
 * 
 * ИНСТРУКЦИЯ:
 * 1. Откройте Chrome DevTools (F12)
 * 2. Перейдите на вкладку Console
 * 3. Вставьте этот код и нажмите Enter
 * 4. Обновите страницу Steam Market
 * 5. Смотрите вывод в консоли - все запросы к cs2floatchecker.com будут показаны
 */

(function() {
    console.log('🔍 Перехватчик запросов активирован!');
    console.log('📋 Обновите страницу Steam Market, чтобы увидеть запросы\n');

    // Перехватываем fetch запросы
    const originalFetch = window.fetch;
    window.fetch = function(...args) {
        const url = args[0];
        const options = args[1] || {};
        
        // Фильтруем только запросы к cs2floatchecker
        if (typeof url === 'string' && url.includes('cs2floatchecker')) {
            console.group('🔵 FETCH ЗАПРОС к cs2floatchecker.com');
            console.log('📍 URL:', url);
            console.log('📤 Method:', options.method || 'GET');
            
            if (options.headers) {
                console.log('📋 Headers:');
                Object.entries(options.headers).forEach(([key, value]) => {
                    console.log(`   ${key}: ${value}`);
                });
            }
            
            if (options.body) {
                console.log('📦 Body:', options.body);
                try {
                    const bodyObj = JSON.parse(options.body);
                    console.log('📦 Body (parsed):', bodyObj);
                } catch (e) {
                    // Не JSON
                }
            }
            
            console.groupEnd();
        }
        
        return originalFetch.apply(this, args).then(response => {
            if (typeof url === 'string' && url.includes('cs2floatchecker')) {
                console.group('✅ FETCH ОТВЕТ от cs2floatchecker.com');
                console.log('📍 URL:', url);
                console.log('📊 Status:', response.status, response.statusText);
                
                // Клонируем response для чтения
                response.clone().json().then(data => {
                    console.log('📦 Response Data:', data);
                    
                    // Проверяем наличие float и pattern
                    const dataStr = JSON.stringify(data).toLowerCase();
                    if (dataStr.includes('float') || dataStr.includes('floatvalue')) {
                        console.log('🎯 ✅ НАЙДЕН FLOAT!');
                    }
                    if (dataStr.includes('pattern') || dataStr.includes('paintseed')) {
                        console.log('🎯 ✅ НАЙДЕН PATTERN!');
                    }
                }).catch(() => {
                    response.clone().text().then(text => {
                        console.log('📦 Response Text:', text.substring(0, 500));
                    });
                });
                
                console.groupEnd();
            }
            return response;
        });
    };

    // Перехватываем XMLHttpRequest
    const originalXHROpen = XMLHttpRequest.prototype.open;
    const originalXHRSend = XMLHttpRequest.prototype.send;
    const originalXHRSetRequestHeader = XMLHttpRequest.prototype.setRequestHeader;

    const xhrHeaders = new WeakMap();

    XMLHttpRequest.prototype.open = function(method, url, ...args) {
        this._url = url;
        this._method = method;
        this._headers = {};
        return originalXHROpen.apply(this, [method, url, ...args]);
    };

    XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
        this._headers[name] = value;
        return originalXHRSetRequestHeader.apply(this, [name, value]);
    };

    XMLHttpRequest.prototype.send = function(...args) {
        const url = this._url;
        const method = this._method;
        
        if (url && url.includes('cs2floatchecker')) {
            console.group('🟡 XHR ЗАПРОС к cs2floatchecker.com');
            console.log('📍 URL:', url);
            console.log('📤 Method:', method);
            
            if (Object.keys(this._headers).length > 0) {
                console.log('📋 Headers:');
                Object.entries(this._headers).forEach(([key, value]) => {
                    console.log(`   ${key}: ${value}`);
                });
            }
            
            if (args[0]) {
                console.log('📦 Body:', args[0]);
                try {
                    const bodyObj = JSON.parse(args[0]);
                    console.log('📦 Body (parsed):', bodyObj);
                } catch (e) {
                    // Не JSON
                }
            }
            
            console.groupEnd();
            
            this.addEventListener('load', function() {
                console.group('✅ XHR ОТВЕТ от cs2floatchecker.com');
                console.log('📍 URL:', url);
                console.log('📊 Status:', this.status, this.statusText);
                
                try {
                    const data = JSON.parse(this.responseText);
                    console.log('📦 Response Data:', data);
                    
                    // Проверяем наличие float и pattern
                    const dataStr = JSON.stringify(data).toLowerCase();
                    if (dataStr.includes('float') || dataStr.includes('floatvalue')) {
                        console.log('🎯 ✅ НАЙДЕН FLOAT!');
                    }
                    if (dataStr.includes('pattern') || dataStr.includes('paintseed')) {
                        console.log('🎯 ✅ НАЙДЕН PATTERN!');
                    }
                } catch (e) {
                    console.log('📦 Response Text:', this.responseText.substring(0, 500));
                }
                
                console.groupEnd();
            });
            
            this.addEventListener('error', function() {
                console.error('❌ XHR ОШИБКА:', url, this.status);
            });
        }
        
        return originalXHRSend.apply(this, args);
    };

    console.log('✅ Перехватчик установлен! Теперь обновите страницу Steam Market.');
})();

