document.addEventListener('DOMContentLoaded', function() {
  // Элементы DOM
  const profileButton = document.getElementById('profileButton');
  const profileModal = document.getElementById('profileModal');
  const backButton = document.getElementById('backButton');
  const notificationsButton = document.getElementById('notificationsButton');
  const notificationsModal = document.getElementById('notificationsModal');
  const notificationsBackButton = document.getElementById('notificationsBackButton');
  const createTaskBtn = document.getElementById('createTaskBtn');
  const taskFormModal = document.getElementById('taskFormModal');
  const closeTaskForm = document.getElementById('closeTaskForm');
  const cancelTaskForm = document.getElementById('cancelTaskForm');
  const taskForm = document.getElementById('taskForm');
  const filterButtons = document.querySelectorAll('.filter-btn');
  const tasksList = document.getElementById('tasksList');
  const statsContainer = document.getElementById('statsContainer');
  const logoutButton = document.getElementById('logoutButton');
  const myTasksButton = document.getElementById('myTasksButton');
  const newTaskButton = document.getElementById('newTaskButton');

  // Текущий фильтр
  let currentFilter = 'all';

  // Инициализация
  initDateTimeInput();
  loadTasks();
  loadStats();

  // События модальных окон
  profileButton.addEventListener('click', () => {
    profileModal.classList.add('active');
  });

  backButton.addEventListener('click', () => {
    profileModal.classList.remove('active');
  });

  notificationsButton.addEventListener('click', () => {
    notificationsModal.classList.add('active');
  });

  notificationsBackButton.addEventListener('click', () => {
    notificationsModal.classList.remove('active');
  });

  // Создание задачи
  createTaskBtn.addEventListener('click', () => {
    taskFormModal.style.display = 'block';
  });

  closeTaskForm.addEventListener('click', () => {
    taskFormModal.style.display = 'none';
  });

  cancelTaskForm.addEventListener('click', () => {
    taskFormModal.style.display = 'none';
  });

  // Фильтрация задач
  filterButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      filterButtons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentFilter = btn.dataset.filter;
      loadTasks();
    });
  });
// Переменные для уведомлений
let unreadCheckInterval = null;
let previousUnreadCount = 0;
let notificationSound = null;

// Инициализация звука уведомления
function initNotificationSound() {
    notificationSound = new Audio('https://assets.mixkit.co/sfx/preview/mixkit-bell-notification-933.mp3');
    notificationSound.volume = 0.3;
}

// Функция для проверки непрочитанных сообщений
async function checkUnreadMessages() {
    try {
        const response = await fetch('/api/chat/unread-count');
        const data = await response.json();

        if (data.success) {
            updateUnreadBadge(data.total_unread);

            // Показываем уведомление, если появились новые непрочитанные
            if (data.total_unread > previousUnreadCount && previousUnreadCount > 0) {
                showNewMessageNotification(data);
            }

            previousUnreadCount = data.total_unread;

            // Если есть непрочитанные сообщения, показываем специальное уведомление
            if (data.total_unread > 0 && data.sessions_with_unread.length > 0) {
                showUnreadMessagesNotification(data.sessions_with_unread);
            }
        }
    } catch (error) {
        console.error('Error checking unread messages:', error);
    }
}

// Функция для обновления бейджа уведомлений
function updateUnreadBadge(count) {
    const notificationBadge = document.getElementById('notificationBadge');

    if (notificationBadge) {
        if (count > 0) {
            notificationBadge.textContent = count > 99 ? '99+' : count;
            notificationBadge.style.display = 'flex';

            // Анимация пульсации для бейджа
            notificationBadge.style.animation = 'none';
            setTimeout(() => {
                notificationBadge.style.animation = 'pulseBadge 2s infinite';
            }, 10);
        } else {
            notificationBadge.style.display = 'none';
        }
    }
}

// Функция для показа уведомления о новых сообщениях
function showNewMessageNotification(data) {
    if (data.sessions_with_unread.length === 0) return;

    // Воспроизводим звук уведомления
    if (notificationSound) {
        notificationSound.currentTime = 0;
        notificationSound.play().catch(e => console.log('Sound playback failed:', e));
    }

    // Берем последнюю сессию с непрочитанными
    const latestSession = data.sessions_with_unread.sort((a, b) => {
        return new Date(b.last_message_time || 0) - new Date(a.last_message_time || 0);
    })[0];

    const taskTitle = latestSession.task ? latestSession.task.title : 'Общий чат';
    const newMessagesCount = data.total_unread - previousUnreadCount;

    showToastNotification({
        title: 'Новые сообщения',
        message: `У вас ${newMessagesCount} нов${newMessagesCount === 1 ? 'ое' : 'ых'} сообщени${newMessagesCount === 1 ? 'е' : 'я'}`,
        task: taskTitle,
        type: 'new_message',
        sessionId: latestSession.session_id
    });
}

// Функция для показа уведомления о непрочитанных сообщениях
function showUnreadMessagesNotification(sessions) {
    // Создаем или обновляем плавающее уведомление
    let floatingNotification = document.getElementById('floatingChatNotification');

    if (!floatingNotification) {
        floatingNotification = document.createElement('div');
        floatingNotification.id = 'floatingChatNotification';
        floatingNotification.className = 'floating-chat-notification';
        document.body.appendChild(floatingNotification);
    }

    // Формируем содержимое уведомления
    let notificationHTML = `
        <div class="chat-notification-header">
            <span class="chat-notification-icon">💬</span>
            <span class="chat-notification-title">Непрочитанные сообщения</span>
            <button class="chat-notification-close" onclick="closeChatNotification()">×</button>
        </div>
        <div class="chat-notification-content">
    `;

    sessions.forEach((session, index) => {
        if (index < 3) { // Показываем максимум 3 чата
            const taskInfo = session.task ?
                `<span class="chat-notification-task">${escapeHtml(session.task.title)}</span>` :
                '<span class="chat-notification-task">Общий чат</span>';

            // Добавляем data-атрибуты для корректной навигации
            notificationHTML += `
                <div class="chat-notification-item"
                     data-session-id="${session.session_id}"
                     onclick="goToChatSession('${session.session_id}')">
                    <div class="chat-notification-item-header">
                        ${taskInfo}
                        <span class="chat-notification-count">${session.unread_count}</span>
                    </div>
                    ${session.last_message_time ?
                        `<div class="chat-notification-time">
                            Последнее: ${formatTimeAgo(session.last_message_time)}
                        </div>` : ''
                    }
                </div>
            `;
        }
    });

    if (sessions.length > 3) {
        notificationHTML += `
            <div class="chat-notification-more">
                и ещё ${sessions.length - 3} чат${sessions.length - 3 === 1 ? '' : 'а'}...
            </div>
        `;
    }

    notificationHTML += `
        </div>
        <div class="chat-notification-footer">
            <button class="chat-notification-btn" onclick="markAllAsRead()">
                Отметить все как прочитанные
            </button>
            <button class="chat-notification-btn primary" onclick="goToAllChats()">
                Перейти ко всем чатам
            </button>
        </div>
    `;

    floatingNotification.innerHTML = notificationHTML;
    floatingNotification.classList.add('visible');
}

// Функция для показа toast-уведомления
function showToastNotification(options) {
    const toast = document.createElement('div');
    toast.className = `toast-notification toast-${options.type || 'info'}`;

    // Добавляем data-атрибуты для навигации
    if (options.sessionId) {
        toast.dataset.sessionId = options.sessionId;
    }

    toast.innerHTML = `
        <div class="toast-icon">💬</div>
        <div class="toast-content">
            <div class="toast-title">${escapeHtml(options.title)}</div>
            <div class="toast-message">${escapeHtml(options.message)}</div>
            ${options.task ? `<div class="toast-task">${escapeHtml(options.task)}</div>` : ''}
        </div>
        <button class="toast-close" onclick="this.parentElement.remove()">×</button>
    `;

    document.body.appendChild(toast);

    // Клик по уведомлению ведет в соответствующий чат
    toast.addEventListener('click', async function(e) {
        // Не реагируем на клик по кнопке закрытия
        if (e.target.classList.contains('toast-close')) return;

        const sessionId = this.dataset.sessionId;
        if (sessionId) {
            await goToChatSession(sessionId);
        } else if (options.taskId) {
            window.location.href = `/chat/session/${options.taskId}`;
        } else {
            window.location.href = '/chat';
        }
    });

    // Автоматическое удаление через 5 секунд
    setTimeout(() => {
        if (toast.parentElement) {
            toast.remove();
        }
    }, 5000);
}

// Вспомогательные функции
function formatTimeAgo(dateTimeStr) {
    const date = new Date(dateTimeStr);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'только что';
    if (diffMins < 60) return `${diffMins} мин назад`;
    if (diffHours < 24) return `${diffHours} час назад`;
    if (diffDays < 7) return `${diffDays} дн назад`;
    return date.toLocaleDateString('ru-RU');
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Глобальные функции для уведомлений
window.closeChatNotification = function() {
    const notification = document.getElementById('floatingChatNotification');
    if (notification) {
        notification.classList.remove('visible');
        setTimeout(() => {
            if (notification.parentElement) {
                notification.remove();
            }
        }, 300);
    }
};

window.goToChatSession = async function(sessionId) {
    try {
        // Получаем информацию о сессии
        const response = await fetch(`/api/chat/session/by-id/${sessionId}`);
        const data = await response.json();

        if (data.success) {
            if (data.session.task_id) {
                // Если есть привязанная задача, идем в чат задачи
                window.location.href = `/chat/session/${data.session.task_id}`;
            } else {
                // Если нет задачи, идем в общий чат с session_id
                window.location.href = `/chat?session_id=${sessionId}`;
            }
        } else {
            console.error('Ошибка получения информации о чате:', data.error);
            // Пробуем стандартный путь
            window.location.href = '/chat';
        }
    } catch (error) {
        console.error('Error getting chat session:', error);
        window.location.href = '/chat';
    }
};

window.goToAllChats = function() {
    window.location.href = '/chat';
};

window.markAllAsRead = async function() {
    try {
        const response = await fetch('/api/chat/mark-all-as-read', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            }
        });

        const data = await response.json();

        if (data.success) {
            // Обновляем UI
            updateUnreadBadge(0);
            previousUnreadCount = 0;
            closeChatNotification();

            // Показываем подтверждение
            showToastNotification({
                title: 'Все сообщения прочитаны',
                message: 'Все непрочитанные сообщения отмечены как прочитанные',
                type: 'success'
            });
        }
    } catch (error) {
        console.error('Error marking all as read:', error);
    }
};
  // Отправка формы задачи
  taskForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    const title = document.getElementById('taskTitle').value;
    const description = document.getElementById('taskDescription').value;
    const due_date = document.getElementById('taskDeadline').value;

    if (!title || !due_date) {
      alert('Пожалуйста, заполните обязательные поля');
      return;
    }

    try {
      const response = await fetch('/api/tasks', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          title,
          description,
          due_date: due_date + 'Z' // Добавляем Z для UTC
        })
      });

      const data = await response.json();

      if (data.success) {
        alert('Задача успешно создана!');
        taskFormModal.style.display = 'none';
        taskForm.reset();

        // Перенаправляем на страницу чата для новой задачи
        if (data.redirect_url) {
          window.location.href = data.redirect_url;
        } else {
          loadTasks();
          loadStats();
        }
      } else {
        alert('Ошибка: ' + (data.error || 'Неизвестная ошибка'));
      }
    } catch (error) {
      console.error('Error:', error);
      alert('Ошибка при создании задачи');
    }
  });

  // Выход из системы
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
        showNotification('Вы успешно вышли из системы', 'success');

        // Перенаправляем на страницу входа через 1 секунду
        setTimeout(() => {
          window.location.href = '/auth/login';
        }, 1000);
      } else {
        showNotification('Ошибка при выходе: ' + data.error, 'error');
      }
    } catch (error) {
      console.error('Error:', error);
      showNotification('Ошибка соединения', 'error');
    }
  });

  // Если функция showNotification не определена, добавьте ее:
  function showNotification(message, type = 'info') {
    // Создаем элемент уведомления
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.textContent = message;

    // Добавляем в тело документа
    document.body.appendChild(notification);

    // Удаляем через 3 секунды
    setTimeout(() => {
      notification.remove();
    }, 3000);
  }

  // Кнопки в меню профиля
  myTasksButton.addEventListener('click', () => {
    profileModal.classList.remove('active');
    // Уже на странице задач
  });

  newTaskButton.addEventListener('click', () => {
    profileModal.classList.remove('active');
    taskFormModal.style.display = 'block';
  });

  // Функции
  function initDateTimeInput() {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const day = String(now.getDate()).padStart(2, '0');
    const hours = String(now.getHours()).padStart(2, '0');
    const minutes = String(now.getMinutes()).padStart(2, '0');

    const minDateTime = `${year}-${month}-${day}T${hours}:${minutes}`;
    document.getElementById('taskDeadline').min = minDateTime;
  }

  async function loadTasks() {
    try {
      const response = await fetch(`/api/tasks?filter=${currentFilter}`);
      const data = await response.json();

      if (data.success) {
        renderTasks(data.tasks);
      } else {
        tasksList.innerHTML = '<div class="error-message">Ошибка загрузки задач</div>';
      }
    } catch (error) {
      console.error('Error:', error);
      tasksList.innerHTML = '<div class="error-message">Ошибка подключения</div>';
    }
  }

  async function loadStats() {
    try {
      const response = await fetch('/stats');
      const data = await response.json();

      if (data.success) {
        renderStats(data.stats);
      }
    } catch (error) {
      console.error('Error:', error);
    }
  }

  function renderTasks(tasks) {
    if (tasks.length === 0) {
      tasksList.innerHTML = '<div class="no-tasks">Нет задач</div>';
      return;
    }

    tasksList.innerHTML = tasks.map(task => `
      <div class="task-item" data-task-id="${task.id}" onclick="openChatForTask(${task.id})">
        <div class="task-item-header">
          <div class="task-item-title">${escapeHtml(task.title)}</div>
          <div class="task-item-status ${task.completed ? 'completed' : 'active'}">
            ${task.completed ? 'Завершена' : 'Активна'}
          </div>
        </div>
        ${task.description ? `<div class="task-item-description">${escapeHtml(task.description)}</div>` : ''}
        <div class="task-item-deadline">
          Срок: ${formatDateTime(task.due_date)}
          ${isOverdue(task.due_date, task.completed) ? '<span class="overdue-badge">ПРОСРОЧЕНО</span>' : ''}
        </div>
        <div class="task-item-actions">
          <button class="action-btn toggle-btn" onclick="toggleTask(${task.id}); event.stopPropagation()">
            ${task.completed ? 'Вернуть в работу' : 'Завершить'}
          </button>
          <button class="action-btn edit-btn" onclick="editTask(${task.id}); event.stopPropagation()">Редактировать</button>
          <button class="action-btn delete-btn" onclick="deleteTask(${task.id}); event.stopPropagation()">Удалить</button>
        </div>
      </div>
    `).join('');
  }

  // Добавьте глобальную функцию для открытия чата
  window.openChatForTask = function(taskId) {
    window.location.href = `/chat/session/${taskId}`;
  };

  function renderStats(stats) {
    statsContainer.innerHTML = `
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-value">${stats.total}</div>
          <div class="stat-label">Всего задач</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">${stats.active}</div>
          <div class="stat-label">Активных</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">${stats.completed}</div>
          <div class="stat-label">Завершено</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">${stats.overdue}</div>
          <div class="stat-label">Просрочено</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">${Math.round(stats.completion_rate)}%</div>
          <div class="stat-label">Выполнено</div>
        </div>
      </div>
      ${stats.upcoming_tasks.length > 0 ? `
        <div class="upcoming-tasks">
          <h3>Ближайшие задачи:</h3>
          <div class="upcoming-list">
            ${stats.upcoming_tasks.map(task => `
              <div class="upcoming-task">
                <div class="upcoming-title">${escapeHtml(task.title)}</div>
                <div class="upcoming-time">Осталось: ${task.hours_left} часов</div>
              </div>
            `).join('')}
          </div>
        </div>
      ` : ''}
    `;
  }

  function formatDateTime(dateTimeStr) {
    const date = new Date(dateTimeStr);
    return date.toLocaleString('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  }

  function isOverdue(dueDate, completed) {
    if (completed) return false;
    const now = new Date();
    const due = new Date(dueDate);
    return now > due;
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  // Глобальные функции для кнопок действий
  window.toggleTask = async function(taskId) {
    try {
      const response = await fetch(`/api/tasks/${taskId}/toggle`, {
        method: 'POST'
      });

      const data = await response.json();
      if (data.success) {
        loadTasks();
        loadStats();
      } else {
        alert('Ошибка: ' + data.error);
      }
    } catch (error) {
      console.error('Error:', error);
      alert('Ошибка при изменении статуса задачи');
    }
  };

  window.editTask = async function(taskId) {
    // Реализация редактирования задачи
    alert('Редактирование задачи ' + taskId);
  };

  window.deleteTask = async function(taskId) {
    if (!confirm('Вы уверены, что хотите удалить эту задачу?')) return;

    try {
      const response = await fetch(`/api/tasks/${taskId}`, {
        method: 'DELETE'
      });

      const data = await response.json();
      if (data.success) {
        loadTasks();
        loadStats();
      } else {
        alert('Ошибка: ' + data.error);
      }
    } catch (error) {
      console.error('Error:', error);
      alert('Ошибка при удалении задачи');
    }
  };
    // Запускаем проверку непрочитанных сообщений
  function startUnreadMessagesCheck() {
    // Инициализируем звук уведомления
    initNotificationSound();

    // Первая проверка сразу
    checkUnreadMessages();

    // Затем проверяем каждые 30 секунд
    unreadCheckInterval = setInterval(checkUnreadMessages, 30000);

    // Также проверяем при возвращении на вкладку
    document.addEventListener('visibilitychange', function() {
        if (!document.hidden) {
            checkUnreadMessages();
        }
    });
  }

  // Запускаем проверку после загрузки страницы
  setTimeout(startUnreadMessagesCheck, 2000);
});
