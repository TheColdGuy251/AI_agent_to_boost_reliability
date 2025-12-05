document.addEventListener('DOMContentLoaded', function() {
    // Элементы DOM, специфичные для чата
    const backToTasksBtn = document.getElementById('backToTasksBtn');
    const messageInput = document.getElementById('messageInput');
    const sendButton = document.getElementById('sendButton');
    const messagesContainer = document.getElementById('messages');
    const chatStatus = document.getElementById('chatStatus');

    // Данные сессии
    const sessionId = document.getElementById('sessionId')?.value;
    const taskId = document.getElementById('taskId')?.value;

    // Переменные для непрочитанных сообщений
    let unreadMessages = new Set();
    let checkUnreadInterval = null;
    let isProcessingDocument = false;

    // Текущее состояние подписки/стрима
    let currentStreaming = {
        assistantId: null,    // активный assistant_message.id (int)
        controller: null,     // AbortController для fetch
        reader: null,         // reader от response.body.getReader()
        active: false,        // флаг активности подписки
        lastSeqSeen: 0        // последний seq, который клиент увидел
    };

    // Хранит id последнего ассистентского сообщения из истории (если есть)
    let lastAssistantId = null;

    // Инициализация
    if (sessionId) {
        loadMessages();
        if (chatStatus) chatStatus.textContent = 'Онлайн';
        // Запускаем проверку непрочитанных сообщений через 1 секунду
        setTimeout(startUnreadCheck, 1000);
    } else if (chatStatus) {
        chatStatus.textContent = 'Сессия не найдена';
    }

    // Навигация
    if (backToTasksBtn) {
        backToTasksBtn.addEventListener('click', () => {
            window.location.href = '/tasks';
        });
    }

    // Устанавливаем один обработчик для кнопки: поведение зависит от режима (send/abort)
async function handleSendButtonClick(e) {
    if (currentStreaming.active) {
        // режим: прервать — вызываем серверный abort, затем локально отменяем
        try {
            const payload = {
                session_id: sessionId,
                assistant_message_id: currentStreaming.assistantId || null
            };
            await fetch('/api/chat/stream/abort', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
        } catch (err) {
            console.error('Не удалось отправить запрос на отмену генерации:', err);
            // Продолжаем: всё равно нужно локально закрыть подписку
        } finally {
            // Добавим локальную пометку "прервано" для временного ассистентского пузыря
            markLocalAssistantAsCancelled();
            // Закрываем подписку/stream
            abortCurrentSubscription();
        }
    } else {
        sendMessage();
    }
}

    if (sendButton && messageInput) {
        sendButton.addEventListener('click', handleSendButtonClick);
        messageInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                // если в стриме — не отправляем, иначе отправляем
                if (!currentStreaming.active) sendMessage();
            }
        });
    }

    // При возврате в фокус — попытаемся переподписаться на активный стрим
    window.addEventListener('focus', () => {
        if (lastAssistantId && !currentStreaming.active) {
            startStreaming({ assistantId: lastAssistantId, lastSeqSeen: currentStreaming.lastSeqSeen });
        } else {
            if (!currentStreaming.active) loadMessages();
        }
    });

    // При видимости страницы — переподписываемся
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) {
            if (lastAssistantId && !currentStreaming.active) {
                startStreaming({ assistantId: lastAssistantId, lastSeqSeen: currentStreaming.lastSeqSeen });
            } else {
                if (!currentStreaming.active) loadMessages();
            }
        }
    });

    // Не забудем остановить интервал при размонтировании
    window.addEventListener('beforeunload', () => {
        if (checkUnreadInterval) {
            clearInterval(checkUnreadInterval);
        }
        abortCurrentSubscription();
    });
function markLocalAssistantAsCancelled() {
    if (!messagesContainer) return;
    try {
        // Пытаемся найти элемент с текущим assistantId
        let el = null;
        if (currentStreaming.assistantId) {
            el = messagesContainer.querySelector(`[data-message-id="${currentStreaming.assistantId}"]`);
        }
        // Если не найден — возьмём последний бот-пузырь (temp)
        if (!el) {
            const botMessages = messagesContainer.querySelectorAll('.message.bot');
            if (botMessages && botMessages.length > 0) {
                el = botMessages[botMessages.length - 1];
            }
        }
        if (el) {
            const contentEl = el.querySelector('.message-content');
            if (contentEl) {
                // Добавим пометку в конце
                if (!contentEl.textContent.includes('(Генерация прервана)')) {
                    contentEl.textContent = (contentEl.textContent || '') + '\n\n(Генерация прервана)';
                }
            }
        }
    } catch (e) {
        console.error('markLocalAssistantAsCancelled error', e);
    }
}

    // ----------------- UI helper: режим стрима -----------------
    function setStreamingUI(active) {
        if (!messageInput || !sendButton) return;
        if (active) {
            // блокируем ввод и меняем поведение/вид кнопки
            messageInput.disabled = true;
            sendButton.textContent = 'Прервать';
            sendButton.classList.add('abort');
            sendButton.setAttribute('aria-pressed', 'true');
            chatStatus.textContent = 'Генерация...';
        } else {
            messageInput.disabled = false;
            sendButton.textContent = 'Отправить';
            sendButton.classList.remove('abort');
            sendButton.setAttribute('aria-pressed', 'false');
            chatStatus.textContent = 'Онлайн';
        }
    }

    // ----------------- Функции -----------------
    async function loadMessages() {
        if (!sessionId || !messagesContainer) return;

        try {
            const response = await fetch(`/api/chat/messages?session_id=${sessionId}&mark_as_read=false`);
            const data = await response.json();

            if (data.success) {
                renderMessages(data.messages);
                updateUnreadCount(data.unread_count || 0);
                messagesContainer.scrollTop = messagesContainer.scrollHeight;

                // Проверяем активные фоновые стримы на сервере для этой сессии
                try {
                    const activeResp = await fetch(`/api/chat/stream/active?session_id=${sessionId}`);
                    if (activeResp.ok) {
                        const activeData = await activeResp.json();
                        if (activeData && activeData.success && Array.isArray(activeData.active) && activeData.active.length > 0) {
                            // Берём самую свежую активную задачу (последняя по started_at)
                            const sorted = activeData.active.sort((a, b) => {
                                const ta = a.started_at ? new Date(a.started_at).getTime() : 0;
                                const tb = b.started_at ? new Date(b.started_at).getTime() : 0;
                                return tb - ta;
                            });
                            const active = sorted[0];
                            if (active && active.message_id) {
                                // Обновим UI текущим содержимым (если есть) и подпишемся
                                const elem = messagesContainer.querySelector(`[data-message-id="${active.message_id}"]`);
                                if (elem) {
                                    const contentEl = elem.querySelector('.message-content');
                                    if (contentEl && active.content) contentEl.textContent = active.content;
                                } else {
                                    addMessageToUI('assistant', active.content || '', active.message_id, false);
                                }

                                lastAssistantId = active.message_id;
                                currentStreaming.lastSeqSeen = active.last_seq || 0;
                                startStreaming({ assistantId: lastAssistantId, lastSeqSeen: currentStreaming.lastSeqSeen });
                                return;
                            }
                        }
                    }
                } catch (err) {
                    console.error('Не удалось проверить активный стрим:', err);
                }

                // Если активных стримов не найдено — используем старую эвристику
                maybeSubscribeToStreaming(data.messages);
            } else {
                showErrorMessage('Ошибка загрузки сообщений: ' + data.error);
            }
        } catch (error) {
            console.error('Error:', error);
            showErrorMessage('Ошибка подключения');
        }
    }

    function maybeSubscribeToStreaming(messages) {
        if (!messages || messages.length === 0) return;

        // Берём последний ассистентский message
        const lastAssistant = [...messages].reverse().find(m => m.role === 'assistant');
        if (!lastAssistant) return;

        lastAssistantId = lastAssistant.id;

        // Эвристика: если сообщение создано недавно или короткое — считаем, что оно возможно ещё в процессе генерации
        const CREATED_THRESHOLD_MINUTES = 30;
        let shouldSubscribe = false;
        try {
            if (lastAssistant.created_at) {
                const createdAt = new Date(lastAssistant.created_at);
                const diffMin = (Date.now() - createdAt.getTime()) / 60000;
                if (diffMin <= CREATED_THRESHOLD_MINUTES) shouldSubscribe = true;
            } else {
                shouldSubscribe = true;
            }
        } catch (e) {
            shouldSubscribe = true;
        }
        if (!lastAssistant.content || lastAssistant.content.length < 20) shouldSubscribe = true;

        if (shouldSubscribe) {
            // Подписываемся на уже существующую генерацию
            startStreaming({ assistantId: lastAssistantId, lastSeqSeen: 0 });
        }
    }

    function abortCurrentSubscription() {
        try {
            if (currentStreaming.reader) {
                currentStreaming.reader.cancel && currentStreaming.reader.cancel();
            }
        } catch (e) {}
        try {
            if (currentStreaming.controller) {
                currentStreaming.controller.abort();
            }
        } catch (e) {}
        currentStreaming.active = false;
        currentStreaming.controller = null;
        currentStreaming.reader = null;
        // Не очищаем assistantId и lastSeqSeen — полезно для автоподписки

        // Обновляем UI (включая кнопку)
        setStreamingUI(false);
    }

    async function startStreaming({ assistantId = null, message = null, use_rag = true, temperature = 0.7, lastSeqSeen = undefined } = {}) {
        // Если уже подписаны на тот же assistantId — ничего не делаем
        if (assistantId && currentStreaming.active && currentStreaming.assistantId === assistantId) {
            return;
        }

        // Отменяем предыдущую подписку (если есть)
        abortCurrentSubscription();

        // Создаём temp element если ассистентский элемент отсутствует
        let tempAssistantElement = null;
        let isTemp = false;
        if (assistantId) {
            tempAssistantElement = messagesContainer.querySelector(`[data-message-id="${assistantId}"]`);
            if (!tempAssistantElement) {
                addMessageToUI('assistant', '', assistantId, false);
                tempAssistantElement = messagesContainer.querySelector(`[data-message-id="${assistantId}"]`);
            }
        } else {
            // Если хотим стартовать новую генерацию (message), добавим временный элемент
            const tempId = `temp-${Date.now()}`;
            addMessageToUI('assistant', '__typing__', tempId, false); // помечаем как typing-пузырь
            tempAssistantElement = messagesContainer.querySelector(`[data-message-id="${tempId}"]`);
            isTemp = true;
        }
        const assistantContentEl = tempAssistantElement ? tempAssistantElement.querySelector('.message-content') : null;

        // Показываем режим стрима (блокируем ввод и меняем кнопку)
        setStreamingUI(true);

        const controller = new AbortController();
        currentStreaming.controller = controller;
        currentStreaming.active = true;

        // Подготовим тело запроса — либо подписка по assistant_message_id, либо запуск новой генерации по message
        const lastSeq = (typeof lastSeqSeen !== 'undefined') ? lastSeqSeen : (currentStreaming.lastSeqSeen || 0);

        const body = assistantId ? { session_id: sessionId, assistant_message_id: assistantId, last_seq: lastSeq } :
            { session_id: sessionId, message: message };

        try {
            const resp = await fetch('/api/chat/stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
                signal: controller.signal
            });

            if (!resp.ok || !resp.body) {
                currentStreaming.active = false;
                console.error('Streaming response not ok');
                setStreamingUI(false);
                return;
            }

            const reader = resp.body.getReader();
            currentStreaming.reader = reader;
            currentStreaming.assistantId = assistantId || null;
            if (assistantId && lastSeq !== undefined) currentStreaming.lastSeqSeen = lastSeq;

            const decoder = new TextDecoder('utf-8');
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });

                // SSE события разделяются пустой строкой
                const parts = buffer.split('\n\n');
                buffer = parts.pop(); // остаток

                for (const partRaw of parts) {
                    const part = partRaw.trim();
                    if (!part) continue;

                    const prefix = 'data: ';
                    let payload = null;
                    if (part.startsWith(prefix)) {
                        const jsonStr = part.slice(prefix.length).trim();
                        try {
                            payload = JSON.parse(jsonStr);
                        } catch (e) {
                            console.error('SSE JSON parse error', e, jsonStr);
                            continue;
                        }
                    } else {
                        payload = { chunk: part };
                    }

                    // Обновление server last_seq, установка message_id
                    if (payload.message_id && !currentStreaming.assistantId) {
                        currentStreaming.assistantId = payload.message_id;
                        // заменим temp-id на реальный id, если нужно
                        if (isTemp && tempAssistantElement && tempAssistantElement.dataset.messageId && String(tempAssistantElement.dataset.messageId).startsWith('temp-')) {
                            tempAssistantElement.dataset.messageId = String(currentStreaming.assistantId);
                            tempAssistantElement.dataset.isRead = 'false';
                            unreadMessages.add(String(currentStreaming.assistantId));
                            updateUnreadIndicator();
                            isTemp = false;
                        }
                    }

                    // Если сервер прислал last_seq при initial header
                    // (будем применять при обработке initial-пayload)
                    // special handling for initial snapshot (replace, not append)
                    if (payload.initial) {
                        const initialText = (typeof payload.initial_chunk !== 'undefined') ? payload.initial_chunk : (payload.chunk || '');
                        if (assistantContentEl) {
                            assistantContentEl.textContent = initialText;
                            messagesContainer.scrollTop = messagesContainer.scrollHeight;
                        }
                        if (payload.last_seq !== undefined) {
                            currentStreaming.lastSeqSeen = Number(payload.last_seq) || 0;
                        }
                        // продолжаем (не аппендим initial как обычный chunk)
                        continue;
                    }

                    if (payload.error) {
                        if (assistantContentEl) assistantContentEl.textContent = 'Ошибка: ' + payload.error;
                    } else if (payload.seq !== undefined) {
                        const seq = Number(payload.seq);
                        // игнорируем дубликаты
                        if (seq <= (currentStreaming.lastSeqSeen || 0)) {
                            // пропускаем
                            continue;
                        }
                        if (assistantContentEl) {
                            assistantContentEl.textContent = (assistantContentEl.textContent || '') + (payload.chunk || '');
                            messagesContainer.scrollTop = messagesContainer.scrollHeight;
                        }
                        currentStreaming.lastSeqSeen = seq;
                    } else if (payload.chunk !== undefined) {
                        // backward-compat: если нет seq и нет initial, просто добавляем (редкий случай)
                        if (assistantContentEl) {
                            assistantContentEl.textContent = (assistantContentEl.textContent || '') + payload.chunk;
                            messagesContainer.scrollTop = messagesContainer.scrollHeight;
                        }
                    } else if (payload.done) {
                        // завершение стрима — синхронизируем историю и завершаем подписку
                        await loadMessages(); // гарантируем корректные timestamps и id
                        abortCurrentSubscription();
                        return;
                    }
                }
            }

            // завершение чтения
            currentStreaming.active = false;
            currentStreaming.controller = null;
            currentStreaming.reader = null;

        } catch (err) {
            if (err.name === 'AbortError') {
                console.log('Streaming aborted by client');
                // пометим временный ассистентский элемент как прерванный (если есть)
                try {
                    if (tempAssistantElement) {
                        const el = tempAssistantElement.querySelector('.message-content');
                        if (el) el.textContent = el.textContent ? el.textContent + '\n\n(Генерация прервана)' : '(Генерация прервана)';
                    }
                } catch (e) {}
            } else {
                console.error('Streaming error', err);
            }
            currentStreaming.active = false;
            currentStreaming.controller = null;
            currentStreaming.reader = null;
            setStreamingUI(false);
        } finally {
            // В конце — убедимся, что UI возвращён в нормальное состояние
            setStreamingUI(false);
        }
    }

    async function sendMessage() {
        if (!sessionId || !messageInput || !messageInput.value.trim()) return;

        const message = messageInput.value.trim();

        // Добавляем сообщение пользователя в интерфейс
        addMessageToUI('user', message);
        messageInput.value = '';

        try {
            // Стартуем поток — это запустит серверную генерацию и подпишется на SSE
            // startStreaming сам создаст временный assistant элемент и заменит его на реальный message_id
            await startStreaming({ message: message });

            // После завершения стрима loadMessages() уже был вызван при done
        } catch (err) {
            console.error('sendMessage error', err);
            addMessageToUI('assistant', 'Ошибка соединения с сервером');
            setStreamingUI(false);
        }
    }

    function renderMessages(messages) {
        if (!messagesContainer) return;

        if (!messages || messages.length === 0) {
            messagesContainer.innerHTML = `
                <div class="no-messages">
                    <p>Нет сообщений. Начните диалог!</p>
                </div>
            `;
            return;
        }

        messagesContainer.innerHTML = messages.map(msg => `
            <div class="message ${msg.role === 'assistant' ? 'bot' : msg.role} ${msg.role === 'assistant' && !msg.is_read ? 'unread' : ''}"
                 data-message-id="${msg.id}"
                 data-is-read="${msg.is_read}">
                <div class="message-avatar">
                    ${msg.role === 'user' ? '👤' : '🤖'}
                </div>
                <div class="message-wrapper">
                    <div class="message-content">${escapeHtml(msg.content)}</div>
                    <div class="message-time">
                        ${formatDateTime(msg.created_at)}
                        ${msg.role === 'assistant' && !msg.is_read ? ' <span class="unread-badge">Новое</span>' : ''}
                    </div>
                </div>
            </div>
        `).join('');

        // Инициализируем набор непрочитанных сообщений
        updateUnreadMessagesSet();
    }

    function addMessageToUI(role, content, messageId = null, isRead = false) {
        if (!messagesContainer) return;

        const messageDiv = document.createElement('div');
        // role может быть 'user' или 'assistant' — для визуала используем 'bot' для ассистента
        const visualRole = (role === 'assistant') ? 'bot' : role;
        messageDiv.className = `message ${visualRole} ${role === 'assistant' && !isRead ? 'unread' : ''}`;
        if (messageId) {
            messageDiv.dataset.messageId = messageId;
            messageDiv.dataset.isRead = isRead;
        } else {
            // если нет id, оставим (будет temp-...)
        }

        // Если content == '__typing__' — рендерим typing-indicator внутри одного ассистентского пузыря
        let contentHtml = '';
        if (content === '__typing__') {
            contentHtml = `
                <div class="typing-indicator typing-inline">
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                </div>
            `;
        } else {
            contentHtml = escapeHtml(content || '');
        }

        messageDiv.innerHTML = `
            <div class="message-avatar">
                ${role === 'user' ? '👤' : '🤖'}
            </div>
            <div class="message-wrapper">
                <div class="message-content">${contentHtml}</div>
                <div class="message-time">
                    ${formatDateTime(new Date().toISOString())}
                    ${role === 'assistant' && !isRead ? ' <span class="unread-badge">Новое</span>' : ''}
                </div>
            </div>
        `;

        messagesContainer.appendChild(messageDiv);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;

        // Если это непрочитанное сообщение от бота, добавляем в набор
        if (role === 'assistant' && !isRead) {
            if (messageId) {
                unreadMessages.add(String(messageId));
            }
            updateUnreadIndicator();
        }
    }
    function showTypingIndicator() {
        if (!messagesContainer) return document.createElement('div');

        const typingDiv = document.createElement('div');
        typingDiv.className = 'message assistant typing-indicator-row';
        typingDiv.innerHTML = `
            <div class="message-avatar">🤖</div>
            <div class="message-wrapper">
                <div class="typing-indicator">
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                </div>
            </div>
        `;

        messagesContainer.appendChild(typingDiv);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;

        return typingDiv;
    }

    // Новая функция для обновления набора непрочитанных сообщений
    function updateUnreadMessagesSet() {
        if (!messagesContainer) return;

        unreadMessages.clear();
        const unreadElements = messagesContainer.querySelectorAll('.message.assistant.unread');
        unreadElements.forEach(element => {
            const messageId = element.dataset.messageId;
            if (messageId) {
                unreadMessages.add(String(messageId));
            }
        });
        updateUnreadIndicator();
    }

    // Функция для обновления индикатора непрочитанных
    function updateUnreadIndicator() {
        const unreadCount = unreadMessages.size;

        // Обновляем бейдж в заголовке
        if (chatStatus) {
            if (unreadCount > 0) {
                chatStatus.innerHTML = `Онлайн • <span class="unread-indicator">${unreadCount} непрочитанных</span>`;
                chatStatus.classList.add('has-unread');
            } else {
                chatStatus.textContent = 'Онлайн';
                chatStatus.classList.remove('has-unread');
            }
        }

        // Обновляем плавающий индикатор
        updateFloatingIndicator();
    }

    // Функция для проверки видимости сообщений
    function checkVisibleMessages() {
        if (!messagesContainer) return;

        const messages = messagesContainer.querySelectorAll('.message.assistant.unread');
        const visibleUnread = [];

        messages.forEach(message => {
            const rect = message.getBoundingClientRect();
            const containerRect = messagesContainer.getBoundingClientRect();

            // Сообщение видимо, если оно находится в пределах контейнера
            const isVisible = (
                rect.top >= containerRect.top &&
                rect.bottom <= containerRect.bottom &&
                rect.left >= containerRect.left &&
                rect.right <= containerRect.right
            );

            if (isVisible) {
                const messageId = message.dataset.messageId;
                if (messageId) {
                    visibleUnread.push(messageId);
                }
            }
        });

        // Если есть видимые непрочитанные сообщения, отмечаем их как прочитанные
        if (visibleUnread.length > 0) {
            markMessagesAsRead(visibleUnread);
        }
    }

    // Функция для отметки сообщений как прочитанных
    async function markMessagesAsRead(messageIds) {
        try {
            const response = await fetch('/api/chat/mark-as-read', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    session_id: sessionId,
                    message_ids: messageIds
                })
            });

            const data = await response.json();

            if (data.success) {
                // Обновляем UI
                messageIds.forEach(id => {
                    const messageElement = messagesContainer.querySelector(`[data-message-id="${id}"]`);
                    if (messageElement) {
                        messageElement.classList.remove('unread');
                        messageElement.dataset.isRead = 'true';

                        // Убираем бейдж "Новое"
                        const badge = messageElement.querySelector('.unread-badge');
                        if (badge) {
                            badge.remove();
                        }
                    }

                    // Удаляем из набора
                    unreadMessages.delete(String(id));
                });

                updateUnreadIndicator();
            }
        } catch (error) {
            console.error('Error marking messages as read:', error);
        }
    }

    // Функция для запуска проверки непрочитанных сообщений
    function startUnreadCheck() {
        // Очищаем предыдущий интервал, если был
        if (checkUnreadInterval) {
            clearInterval(checkUnreadInterval);
        }

        // Проверяем каждые 500ms видимость сообщений
        checkUnreadInterval = setInterval(checkVisibleMessages, 500);

        // Также проверяем при прокрутке
        if (messagesContainer) {
            messagesContainer.addEventListener('scroll', debounce(checkVisibleMessages, 100));
        }
    }

    // Функция для обновления плавающего индикатора
    function updateFloatingIndicator() {
        const floatingIndicator = document.getElementById('floatingUnreadIndicator');
        const floatingCount = document.getElementById('floatingUnreadCount');
        const unreadCount = unreadMessages.size;

        if (floatingIndicator && floatingCount) {
            if (unreadCount > 0) {
                floatingCount.textContent = unreadCount;
                floatingIndicator.classList.add('visible');

                // Добавляем обработчик клика для прокрутки к непрочитанным
                floatingIndicator.onclick = scrollToFirstUnread;
            } else {
                floatingIndicator.classList.remove('visible');
            }
        }
    }

    // Функция для прокрутки к первому непрочитанному сообщению
    function scrollToFirstUnread() {
        if (!messagesContainer) return;

        const firstUnread = messagesContainer.querySelector('.message.assistant.unread');
        if (firstUnread) {
            firstUnread.scrollIntoView({ behavior: 'smooth', block: 'center' });

            // Подсвечиваем сообщение
            firstUnread.style.backgroundColor = 'rgba(255, 215, 0, 0.2)';
            setTimeout(() => {
                firstUnread.style.backgroundColor = '';
            }, 2000);
        }
    }

    function updateUnreadCount(count) {
        // Синхронизируем (не стираем сообщения, только используем для инициализации)
        // оставляем место для логики инициализации набора
    }

    function showErrorMessage(message) {
        if (!messagesContainer) return;

        messagesContainer.innerHTML = `
            <div class="error-message">
                ${escapeHtml(message)}
            </div>
        `;
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // Функция debounce для оптимизации
    function debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }
    async function uploadDocument(file) {
    if (!sessionId || !file || isProcessingDocument) return;

    // Блокируем интерфейс
    isProcessingDocument = true;
    setUILocked(true);

    // Показываем статус загрузки
    const uploadStatus = document.getElementById('uploadStatus');
    const uploadText = uploadStatus.querySelector('.upload-text');
    const uploadProgressBar = uploadStatus.querySelector('.upload-progress-bar');

    uploadStatus.style.display = 'block';
    uploadStatus.className = 'upload-status';
    uploadText.textContent = 'Загрузка и обработка документа...';
    uploadProgressBar.style.width = '0%';

    const formData = new FormData();
    formData.append('file', file);
    formData.append('session_id', sessionId);

    try {
        const response = await fetch('/api/chat/upload-document', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        // Анимация прогресса
        uploadProgressBar.style.width = '100%';

        if (data.success) {
            // Показываем успех
            uploadStatus.className = 'upload-status success';
            uploadText.textContent = `✓ Файл "${file.name}" успешно загружен!`;

            // Добавляем сообщение от бота
            setTimeout(() => {
                addMessageToUI('assistant',
                    `Документ "${file.name}" успешно загружен и добавлен в базу знаний.\n\n` +
                    `Файл: ${data.file.name} (${Math.round(data.file.size / 1024)} KB)\n` +
                    `Добавлено фрагментов: ${data.collection_info.total_chunks}\n` +
                    `Теперь вы можете задавать вопросы по содержанию этого документа.`
                );
            }, 500);

            // Скрываем статус через 3 секунды
            setTimeout(() => {
                uploadStatus.style.display = 'none';
            }, 3000);

        } else {
            // Показываем ошибку
            uploadStatus.className = 'upload-status error';
            uploadText.textContent = `Ошибка: ${data.error}`;

            // Скрываем статус через 5 секунд
            setTimeout(() => {
                uploadStatus.style.display = 'none';
            }, 5000);
        }

    } catch (error) {
        console.error('Ошибка при загрузке файла:', error);

        uploadStatus.className = 'upload-status error';
        uploadText.textContent = 'Ошибка подключения к серверу';

        setTimeout(() => {
            uploadStatus.style.display = 'none';
        }, 5000);

    } finally {
        // Разблокируем интерфейс
        isProcessingDocument = false;
        setUILocked(false);
    }
}

// Добавьте эту функцию для блокировки/разблокировки интерфейса
function setUILocked(locked) {
    const messageInput = document.getElementById('messageInput');
    const sendButton = document.getElementById('sendButton');
    const attachButton = document.getElementById('attachButton');
    const fileInput = document.getElementById('fileInput');

    if (messageInput) messageInput.disabled = locked;
    if (sendButton) sendButton.disabled = locked;
    if (attachButton) attachButton.disabled = locked;
    if (fileInput) fileInput.disabled = locked;

    if (locked) {
        if (messageInput) messageInput.placeholder = 'Обработка документа...';
        if (attachButton) attachButton.style.opacity = '0.5';
    } else {
        if (messageInput) messageInput.placeholder = 'Задайте вопрос о задаче или оборудовании...';
        if (attachButton) attachButton.style.opacity = '1';
    }
}
    // Добавьте эти элементы после существующего кода
    const fileInput = document.getElementById('fileInput');
    const attachButton = document.getElementById('attachButton');

    // Обработчик клика на скрепку
    if (attachButton && fileInput) {
        attachButton.addEventListener('click', (e) => {
            if (!isProcessingDocument && sessionId) {
                fileInput.click();
            }
        });

        attachButton.addEventListener('dragenter', (e) => {
            if (!isProcessingDocument && sessionId) {
                e.preventDefault();
                attachButton.style.backgroundColor = 'rgba(255, 215, 0, 0.2)';
            }
        });

        attachButton.addEventListener('dragleave', (e) => {
            e.preventDefault();
            attachButton.style.backgroundColor = '';
        });

        attachButton.addEventListener('dragover', (e) => {
            if (!isProcessingDocument && sessionId) {
                e.preventDefault();
            }
        });

        attachButton.addEventListener('drop', (e) => {
            e.preventDefault();
            attachButton.style.backgroundColor = '';

            if (!isProcessingDocument && sessionId && e.dataTransfer.files.length > 0) {
                const file = e.dataTransfer.files[0];
                if (file.name.endsWith('.docx')) {
                    uploadDocument(file);
                } else {
                    addMessageToUI('assistant', 'Поддерживаются только файлы формата .docx');
                }
            }
        });
    }

    // Обработчик выбора файла через input
    if (fileInput) {
        fileInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                const file = e.target.files[0];
                if (file.name.endsWith('.docx')) {
                    uploadDocument(file);
                    // Сбрасываем значение input, чтобы можно было загрузить тот же файл снова
                    fileInput.value = '';
                } else {
                    addMessageToUI('assistant', 'Поддерживаются только файлы формата .docx');
                    fileInput.value = '';
                }
            }
        });
    }
});

