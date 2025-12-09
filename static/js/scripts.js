// Общие элементы DOM
const profileButton = document.getElementById('profileButton');
const profileModal = document.getElementById('profileModal');
const backButton = document.getElementById('backButton');
const logoutButton = document.getElementById('logoutButton');
const myTasksButton = document.getElementById('myTasksButton');
const newTaskButton = document.getElementById('newTaskButton');

// Инициализация после загрузки DOM
document.addEventListener('DOMContentLoaded', function() {
    // События модальных окон (если элементы существуют)
    if (profileButton && profileModal) {
        profileButton.addEventListener('click', () => {
            profileModal.classList.add('active');
        });
    }

    if (backButton && profileModal) {
        backButton.addEventListener('click', () => {
            profileModal.classList.remove('active');
        });
    }

    // Кнопки в меню профиля
    if (myTasksButton) {
        myTasksButton.addEventListener('click', () => {
            if (profileModal) profileModal.classList.remove('active');
            window.location.href = '/tasks';
        });
    }

    if (newTaskButton) {
        newTaskButton.addEventListener('click', () => {
            if (profileModal) profileModal.classList.remove('active');
            window.location.href = '/tasks';
            // Открытие формы задачи будет обработано в tasks.js
        });
    }

    // Выход из системы
    if (logoutButton) {
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
    }
});

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