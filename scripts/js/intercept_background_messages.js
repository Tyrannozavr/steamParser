/**
 * Скрипт для перехвата сообщений между content script и background script
 * Помогает найти, какой API использует background script для парсинга inspect ссылок
 * 
 * ВАЖНО: Данные paintSeed видны в логах, потому что расширение само их логирует через console.log()
 * Но мы НЕ видим, какой API использует background script - нужно перехватить сообщения!
 * 
 * ИНСТРУКЦИЯ:
 * 1. Откройте Chrome DevTools (F12)
 * 2. Перейдите на вкладку Console
 * 3. Вставьте этот код и нажмите Enter
 * 4. Обновите страницу Steam Market
 * 5. Смотрите вывод в консоли - все сообщения между content и background будут показаны
 */

(function() {
    console.log('🔍 Перехватчик сообщений background script активирован!');
    console.log('📋 Обновите страницу Steam Market, чтобы увидеть сообщения\n');
    console.log('💡 ВАЖНО: Мы видим paintSeed в логах, потому что расширение само их логирует');
    console.log('💡 Но мы НЕ видим, какой API использует background script - нужно перехватить!\n');

    // Перехватываем chrome.runtime.sendMessage
    const originalSendMessage = chrome.runtime.sendMessage;
    chrome.runtime.sendMessage = function(...args) {
        const message = args[0];
        
        // Проверяем, содержит ли сообщение inspect ссылку
        if (message && (message.inspectLink || message.inspect || (typeof message === 'string' && message.includes('steam://')))) {
            console.group('📤 ОТПРАВКА СООБЩЕНИЯ В BACKGROUND SCRIPT');
            console.log('🔗 Сообщение содержит inspect ссылку!');
            console.log('Полное сообщение:', JSON.stringify(message, null, 2));
            if (args[1]) {
                console.log('Опции:', args[1]);
            }
            console.groupEnd();
        }
        
        // Вызываем оригинальный метод
        const result = originalSendMessage.apply(this, args);
        
        // Если есть callback, перехватываем ответ
        if (args.length > 0 && typeof args[args.length - 1] === 'function') {
            const originalCallback = args[args.length - 1];
            args[args.length - 1] = function(response) {
                if (response && (response.enhancedData || response.floatValue || response.paintSeed)) {
                    console.group('📥 ОТВЕТ ОТ BACKGROUND SCRIPT');
                    console.log('✅ Получены данные с floatValue и paintSeed!');
                    console.log('Полный ответ:', JSON.stringify(response, null, 2));
                    console.groupEnd();
                }
                return originalCallback.apply(this, arguments);
            };
        }
        
        return result;
    };

    // Перехватываем Promise-based sendMessage
    if (chrome.runtime.sendMessage.toString().includes('Promise')) {
        const originalSendMessagePromise = chrome.runtime.sendMessage;
        chrome.runtime.sendMessage = function(...args) {
            const message = args[0];
            
            if (message && (message.inspectLink || message.inspect || (typeof message === 'string' && message.includes('steam://')))) {
                console.group('📤 ОТПРАВКА СООБЩЕНИЯ В BACKGROUND SCRIPT (Promise)');
                console.log('🔗 Сообщение содержит inspect ссылку!');
                console.log('Полное сообщение:', JSON.stringify(message, null, 2));
                console.groupEnd();
            }
            
            const promise = originalSendMessagePromise.apply(this, args);
            
            promise.then(response => {
                if (response && (response.enhancedData || response.floatValue || response.paintSeed)) {
                    console.group('📥 ОТВЕТ ОТ BACKGROUND SCRIPT (Promise)');
                    console.log('✅ Получены данные с floatValue и paintSeed!');
                    console.log('Полный ответ:', JSON.stringify(response, null, 2));
                    console.groupEnd();
                }
            }).catch(err => {
                console.error('❌ Ошибка при отправке сообщения:', err);
            });
            
            return promise;
        };
    }
    
    console.log('✅ Перехватчик установлен! Теперь обновите страницу Steam Market.');
    console.log('💡 Обратите внимание на сообщения с inspect ссылками и ответы с floatValue и paintSeed');
    console.log('💡 Если увидите URL API в сообщениях - это то, что нам нужно!');
})();

