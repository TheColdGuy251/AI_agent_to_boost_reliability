document.addEventListener('DOMContentLoaded', function() {
    // Элементы DOM
    const profileButton = document.getElementById('profileButton');
    const profileModal = document.getElementById('profileModal');
    const backButton = document.getElementById('backButton');
    const notificationsButton = document.getElementById('notificationsButton');
    const notificationsModal = document.getElementById('notificationsModal');
    const notificationsBackButton = document.getElementById('notificationsBackButton');
    const logoutButton = document.getElementById('logoutButton');
    const myTasksButton = document.getElementById('myTasksButton');
    const newTaskButton = document.getElementById('newTaskButton');
    const backToTasksBtn = document.getElementById('backToTasksBtn');

    const messageInput = document.getElementById('messageInput');
    const sendButton = document.getElementById('sendButton');
    const messagesContainer = document.getElementById('messages');
    const chatStatus = document.getElementById('chatStatus');

    // Данные сессии
    const sessionId = document.getElementById('sessionId').value;
    const taskId = document.getElementById('taskId').value;

    // Переменные для непрочитанных сообщений
    let unreadMessages = new Set();
    let checkUnreadInterval = null;

    // Инициализация
    if (sessionId) {
        loadMessages();
        chatStatus.textContent = 'Онлайн';
        // Запускаем проверку непрочитанных сообщений через 1 секунду
        setTimeout(startUnreadCheck, 1000);
    } else {
        chatStatus.textContent = 'Сессия не найдена';
    }

    // События модальных окон
    profileButton.addEventListener('click', () => {
        profileModal.classList.add('active');
    });

    backButton.addEventListener('click', () => {
        profileModal.classList.remove('active');
    });

    notificationsButton.addEventListener('click', () => {
        notificationsModal.classList.add('active');
        loadNotifications();
    });

    notificationsBackButton.addEventListener('click', () => {
        notificationsModal.classList.remove('active');
    });

    // Отправка сообщения
    sendButton.addEventListener('click', sendMessage);
    messageInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // Навигация
    backToTasksBtn.addEventListener('click', () => {
        window.location.href = '/tasks';
    });

    myTasksButton.addEventListener('click', () => {
        window.location.href = '/tasks';
    });

    newTaskButton.addEventListener('click', () => {
        window.location.href = '/tasks';
    });

    logoutButton.addEventListener('click', async () => {
        if (!confirm('Вы уверены, что хотите выйти из системы?')) return;

        try {
            const response = await fetch('/auth/logout', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                }
            });

            const data = await response.json();

            if (data.success) {
                window.location.href = '/auth/login';
            } else {
                alert('Ошибка при выходе: ' + data.error);
            }
        } catch (error) {
            console.error('Error:', error);
            alert('Ошибка соединения');
        }
    });

    // Проверяем непрочитанные при фокусе на окне
    window.addEventListener('focus', checkVisibleMessages);

    // Проверяем при возвращении на вкладку
    document.addEventListener('visibilitychange', function() {
        if (!document.hidden) {
            checkVisibleMessages();
        }
    });

    // Не забудем остановить интервал при размонтировании
    window.addEventListener('beforeunload', () => {
        if (checkUnreadInterval) {
            clearInterval(checkUnreadInterval);
        }
    });

    // Функции
    async function loadMessages() {
        if (!sessionId) return;

        try {
            const response = await fetch(`/api/chat/messages?session_id=${sessionId}&mark_as_read=false`);
            const data = await response.json();

            if (data.success) {
                renderMessages(data.messages);
                updateUnreadCount(data.unread_count || 0);
                messagesContainer.scrollTop = messagesContainer.scrollHeight;
            } else {
                showErrorMessage('Ошибка загрузки сообщений: ' + data.error);
            }
        } catch (error) {
            console.error('Error:', error);
            showErrorMessage('Ошибка подключения');
        }
    }

    async function sendMessage() {
        if (!sessionId || !messageInput.value.trim()) return;

        const message = messageInput.value.trim();

        // Добавляем сообщение пользователя в интерфейс
        addMessageToUI('user', message);
        messageInput.value = '';

        // Показываем индикатор "печатает"
        const typingIndicator = showTypingIndicator();

        try {
            const response = await fetch('/api/chat/send', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    session_id: sessionId,
                    message: message
                })
            });

            const data = await response.json();

            // Убираем индикатор "печатает"
            typingIndicator.remove();

            if (data.success) {
                // Добавляем ответ ассистента
                addMessageToUI('assistant', data.assistant_message.content, data.assistant_message.id, false);

                // Сохраняем ID непрочитанного сообщения
                if (data.assistant_message.id) {
                    unreadMessages.add(data.assistant_message.id);
                    updateUnreadIndicator();
                }
            } else {
                addMessageToUI('assistant', 'Ошибка: ' + data.error);
            }
        } catch (error) {
            console.error('Error:', error);
            typingIndicator.remove();
            addMessageToUI('assistant', 'Ошибка соединения с сервером');
        }
    }

    function renderMessages(messages) {
        if (!messages || messages.length === 0) {
            messagesContainer.innerHTML = `
                <div class="no-messages">
                    <p>Нет сообщений. Начните диалог!</p>
                </div>
            `;
            return;
        }

        messagesContainer.innerHTML = messages.map(msg => `
            <div class="message ${msg.role} ${msg.role === 'assistant' && !msg.is_read ? 'unread' : ''}"
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
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${role} ${role === 'assistant' && !isRead ? 'unread' : ''}`;
        if (messageId) {
            messageDiv.dataset.messageId = messageId;
            messageDiv.dataset.isRead = isRead;
        }

        messageDiv.innerHTML = `
            <div class="message-avatar">
                ${role === 'user' ? '👤' : '🤖'}
            </div>
            <div class="message-wrapper">
                <div class="message-content">${escapeHtml(content)}</div>
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
                unreadMessages.add(messageId);
            }
            updateUnreadIndicator();
        }
    }

    function showTypingIndicator() {
        const typingDiv = document.createElement('div');
        typingDiv.className = 'message assistant';
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
        unreadMessages.clear();
        const unreadElements = messagesContainer.querySelectorAll('.message.assistant.unread');
        unreadElements.forEach(element => {
            const messageId = element.dataset.messageId;
            if (messageId) {
                unreadMessages.add(messageId);
            }
        });
        updateUnreadIndicator();
    }

    // Функция для обновления индикатора непрочитанных
    function updateUnreadIndicator() {
        const unreadCount = unreadMessages.size;

        // Обновляем бейдж в заголовке
        if (unreadCount > 0) {
            chatStatus.innerHTML = `Онлайн • <span class="unread-indicator">${unreadCount} непрочитанных</span>`;
            chatStatus.classList.add('has-unread');
        } else {
            chatStatus.textContent = 'Онлайн';
            chatStatus.classList.remove('has-unread');
        }

        // Также можно обновить бейдж уведомлений
        const notificationBadge = document.getElementById('notificationBadge');
        if (notificationBadge) {
            if (unreadCount > 0) {
                notificationBadge.textContent = unreadCount;
                notificationBadge.style.display = 'flex';
            } else {
                notificationBadge.style.display = 'none';
            }
        }

        // Обновляем плавающий индикатор
        updateFloatingIndicator();
    }

    // Функция для проверки видимости сообщений
    function checkVisibleMessages() {
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
                    unreadMessages.delete(id);
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

        // Проверяем каждые 500ms
        checkUnreadInterval = setInterval(checkVisibleMessages, 500);

        // Также проверяем при прокрутке
        messagesContainer.addEventListener('scroll', debounce(checkVisibleMessages, 100));
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

    async function loadNotifications() {
        try {
            const response = await fetch('/api/notifications');
            const data = await response.json();

            if (data.success) {
                renderNotifications(data.notifications);
            }
        } catch (error) {
            console.error('Error:', error);
        }
    }

    function renderNotifications(notifications) {
        const container = document.getElementById('notificationsList');

        if (!notifications || notifications.length === 0) {
            container.innerHTML = '<div class="no-notifications">Нет уведомлений</div>';
            return;
        }

        container.innerHTML = notifications.map(notification => `
            <div class="notification-item ${notification.unread ? 'unread' : ''}">
                <div class="notification-icon-wrapper">${getNotificationIcon(notification.type)}</div>
                <div class="notification-content">
                    <p class="notification-title">${escapeHtml(notification.title)}</p>
                    <p class="notification-text">${escapeHtml(notification.message)}</p>
                    <p class="notification-time">${formatDateTime(notification.created_at)}</p>
                </div>
            </div>
        `).join('');
    }

    function getNotificationIcon(type) {
        const icons = {
            'deadline': '⚠️',
            'task_completed': '✅',
            'new_task': '📝',
            'system': '🔔'
        };
        return icons[type] || '🔔';
    }

    function formatDateTime(dateTimeStr) {
        if (!dateTimeStr) return '';

        const date = new Date(dateTimeStr);
        return date.toLocaleString('ru-RU', {
            hour: '2-digit',
            minute: '2-digit',
            day: '2-digit',
            month: '2-digit'
        });
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function showErrorMessage(message) {
        messagesContainer.innerHTML = `
            <div class="error-message">
                ${escapeHtml(message)}
            </div>
        `;
    }

    function updateUnreadCount(count) {
        unreadMessages.clear();
        // Здесь можно добавить логику для инициализации набора
        // на основе начального количества непрочитанных
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
});