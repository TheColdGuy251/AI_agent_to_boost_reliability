from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from flask_login import login_required, current_user
from datetime import datetime, timezone, timedelta, UTC
import uuid
import logging

from data.db_session import create_session
from data.tasks import Task
from data.chat_sessions import ChatSession
from data.chat_message import ChatMessage
from utils.constants import ERROR_MESSAGES

logger = logging.getLogger(__name__)
tasks_bp = Blueprint('tasks', __name__, template_folder='templates')


@tasks_bp.route('/tasks')
@login_required
def tasks_page():
    """Страница с задачами пользователя"""
    user_initials = f"{current_user.surname[0]}{current_user.name[0]}"
    user_name = f"{current_user.name} {current_user.surname[0]}."
    user_full_name = f"{current_user.surname} {current_user.name} {current_user.patronymic or ''}".strip()

    return render_template('tasks.html',
                           user_initials=user_initials,
                           user_name=user_name,
                           user_full_name=user_full_name,
                           user_position=current_user.position)


@tasks_bp.route('/api/tasks', methods=['GET'])
@login_required
def get_tasks():
    """Получить задачи пользователя"""
    session = create_session()

    try:
        # Получаем параметры фильтрации
        filter_type = request.args.get('filter', 'all')

        # Базовый запрос
        query = session.query(Task).filter_by(user_id=current_user.id)

        # Применяем фильтры
        if filter_type == 'active':
            query = query.filter_by(completed=False)
        elif filter_type == 'completed':
            query = query.filter_by(completed=True)
        elif filter_type == 'overdue':
            now = datetime.now(timezone.utc)
            query = query.filter(
                Task.completed == False,
                Task.due_date < now
            )

        tasks = query.order_by(Task.due_date.asc()).all()

        return jsonify({
            'success': True,
            'tasks': [task.to_dict() for task in tasks]
        })

    except Exception as e:
        logger.error(f"Ошибка при получении задач: {e}")
        return jsonify({
            'success': False,
            'error': 'Не удалось загрузить задачи'
        }), 500

    finally:
        session.close()


@tasks_bp.route('/api/tasks', methods=['POST'])
@login_required
def create_task():
    """Создать новую задачу"""
    data = request.get_json()

    if not data or not data.get('title') or not data.get('due_date'):
        return jsonify({
            'success': False,
            'error': ERROR_MESSAGES.get('missing_fields', 'Не все обязательные поля заполнены')
        }), 400

    try:
        # Парсим дату и время
        due_date = datetime.fromisoformat(data['due_date'].replace('Z', '+00:00'))

        # Проверяем, что срок не в прошлом
        if due_date < datetime.now(timezone.utc):
            return jsonify({
                'success': False,
                'error': 'Срок выполнения не может быть в прошлом'
            }), 400

    except ValueError:
        return jsonify({
            'success': False,
            'error': ERROR_MESSAGES.get('invalid_format', 'Неверный формат даты')
        }), 400

    session = create_session()

    try:
        # Создаем задачу
        task = Task(
            user_id=current_user.id,
            title=data['title'],
            description=data.get('description', ''),
            due_date=due_date
        )

        session.add(task)
        session.commit()
        session.refresh(task)

        # Создаем чат-сессию для задачи
        chat_session = ChatSession(
            user_id=current_user.id,
            task_id=task.id,
            session_id=str(uuid.uuid4())
        )

        session.add(chat_session)
        session.commit()

        # Создаем системное сообщение
        system_message = ChatMessage(
            session_id=chat_session.id,
            role='system',
            content=f"Задача: {task.title}\nСрок: {task.due_date.strftime('%d.%m.%Y %H:%M')}\nОписание: {task.description}"
        )

        session.add(system_message)
        session.commit()

        logger.info(f"Создана задача {task.id} для пользователя {current_user.id}")

        return jsonify({
            'success': True,
            'message': 'Задача успешно создана',
            'task': task.to_dict(),
            'chat_session_id': chat_session.session_id,
            'redirect_url': f'/chat/session/{task.id}'
        }), 201

    except Exception as e:
        session.rollback()
        logger.error(f"Ошибка при создании задачи: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

    finally:
        session.close()


@tasks_bp.route('/api/tasks/<int:task_id>', methods=['PUT'])
@login_required
def update_task(task_id):
    """Обновить задачу"""
    data = request.get_json()

    session = create_session()

    try:
        task = session.query(Task).get(task_id)

        if not task or task.user_id != current_user.id:
            return jsonify({
                'success': False,
                'error': ERROR_MESSAGES.get('not_found', 'Задача не найдена')
            }), 404

        # Обновляем поля
        if 'title' in data:
            task.title = data['title']

        if 'description' in data:
            task.description = data['description']

        if 'due_date' in data:
            try:
                task.due_date = datetime.fromisoformat(data['due_date'].replace('Z', '+00:00'))
            except ValueError:
                return jsonify({
                    'success': False,
                    'error': ERROR_MESSAGES.get('invalid_format', 'Неверный формат даты')
                }), 400

        if 'completed' in data:
            task.completed = data['completed']

        task.updated_at = datetime.now(timezone.utc)

        session.commit()

        return jsonify({
            'success': True,
            'message': 'Задача успешно обновлена',
            'task': task.to_dict()
        })

    except Exception as e:
        session.rollback()
        logger.error(f"Ошибка при обновлении задачи: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

    finally:
        session.close()


@tasks_bp.route('/api/tasks/<int:task_id>', methods=['DELETE'])
@login_required
def delete_task(task_id):
    """Удалить задачу"""
    session = create_session()

    try:
        task = session.query(Task).get(task_id)

        if not task or task.user_id != current_user.id:
            return jsonify({
                'success': False,
                'error': ERROR_MESSAGES.get('not_found', 'Задача не найдена')
            }), 404

        # Удаляем связанную чат-сессию
        chat_session = session.query(ChatSession).filter_by(task_id=task_id).first()
        if chat_session:
            session.delete(chat_session)

        session.delete(task)
        session.commit()

        logger.info(f"Удалена задача {task_id} пользователя {current_user.id}")

        return jsonify({
            'success': True,
            'message': 'Задача успешно удалена'
        })

    except Exception as e:
        session.rollback()
        logger.error(f"Ошибка при удалении задачи: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

    finally:
        session.close()


@tasks_bp.route('/api/tasks/<int:task_id>/toggle', methods=['POST'])
@login_required
def toggle_task(task_id):
    """Переключить статус выполнения задачи"""
    session = create_session()

    try:
        task = session.query(Task).get(task_id)

        if not task or task.user_id != current_user.id:
            return jsonify({
                'success': False,
                'error': ERROR_MESSAGES.get('not_found', 'Задача не найдена')
            }), 404

        task.completed = not task.completed
        task.updated_at = datetime.now(timezone.utc)

        session.commit()

        return jsonify({
            'success': True,
            'message': 'Статус задачи обновлен',
            'task': task.to_dict()
        })

    except Exception as e:
        session.rollback()
        logger.error(f"Ошибка при переключении статуса задачи: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

    finally:
        session.close()


@tasks_bp.route('/stats', methods=['GET'])
@login_required
def get_stats():
    db_sess = create_session()

    try:
        # Получаем все задачи пользователя
        tasks = db_sess.query(Task).filter(Task.user_id == current_user.id).all()

        total = len(tasks)
        active = sum(1 for t in tasks if not t.completed)
        completed = sum(1 for t in tasks if t.completed)

        # Подсчет просроченных задач
        now = datetime.now(UTC)
        overdue = 0
        upcoming_tasks = []

        for task in tasks:
            if not task.completed and task.due_date:
                # Если задача активна и срок прошел
                due_date_utc = task.due_date
                if due_date_utc.tzinfo is None:
                    due_date_utc = due_date_utc.replace(tzinfo=UTC)

                if due_date_utc < now:
                    overdue += 1
                else:
                    # Проверяем, если до срока осталось менее 24 часов
                    time_left = due_date_utc - now
                    if time_left <= timedelta(hours=24):
                        hours_left = time_left.total_seconds() / 3600
                        upcoming_tasks.append({
                            'title': task.title,
                            'hours_left': round(hours_left, 1)
                        })

        # Процент выполнения
        completion_rate = (completed / total * 100) if total > 0 else 0

        stats = {
            'total': total,
            'active': active,
            'completed': completed,
            'overdue': overdue,
            'completion_rate': completion_rate,
            'upcoming_tasks': upcoming_tasks[:5]  # Ограничиваем 5 ближайшими задачами
        }

        return jsonify({
            'success': True,
            'stats': stats
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        db_sess.close()