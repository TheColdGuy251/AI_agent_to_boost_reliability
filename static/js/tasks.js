document.addEventListener('DOMContentLoaded', function() {
    // Элементы DOM, специфичные для задач
    const createTaskBtn = document.getElementById('createTaskBtn');
    const taskFormModal = document.getElementById('taskFormModal');
    const closeTaskForm = document.getElementById('closeTaskForm');
    const cancelTaskForm = document.getElementById('cancelTaskForm');
    const taskForm = document.getElementById('taskForm');
    const filterButtons = document.querySelectorAll('.filter-btn');
    const tasksList = document.getElementById('tasksList');
    const statsContainer = document.getElementById('statsContainer');

    // Текущий фильтр
    let currentFilter = 'all';

    // Инициализация
    initDateTimeInput();
    loadTasks();
    loadStats();

    // Создание задачи
    if (createTaskBtn && taskFormModal) {
        createTaskBtn.addEventListener('click', () => {
            taskFormModal.style.display = 'block';
        });
    }

    if (closeTaskForm && taskFormModal) {
        closeTaskForm.addEventListener('click', () => {
            taskFormModal.style.display = 'none';
        });
    }

    if (cancelTaskForm && taskFormModal) {
        cancelTaskForm.addEventListener('click', () => {
            taskFormModal.style.display = 'none';
        });
    }

    // Фильтрация задач
    filterButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            filterButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentFilter = btn.dataset.filter;
            loadTasks();
        });
    });

    // Отправка формы задачи
    if (taskForm) {
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
    }

    // Функции
    function initDateTimeInput() {
        const taskDeadline = document.getElementById('taskDeadline');
        if (!taskDeadline) return;

        const now = new Date();
        const year = now.getFullYear();
        const month = String(now.getMonth() + 1).padStart(2, '0');
        const day = String(now.getDate()).padStart(2, '0');
        const hours = String(now.getHours()).padStart(2, '0');
        const minutes = String(now.getMinutes()).padStart(2, '0');

        const minDateTime = `${year}-${month}-${day}T${hours}:${minutes}`;
        taskDeadline.min = minDateTime;
    }

    async function loadTasks() {
        if (!tasksList) return;

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
        if (!statsContainer) return;

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
        if (!tasksList) return;

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

    function renderStats(stats) {
        if (!statsContainer) return;

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

    window.openChatForTask = function(taskId) {
        window.location.href = `/chat/session/${taskId}`;
    };
});