# routes/chat.py
from flask import Blueprint, request, jsonify, stream_with_context, Response, current_app, render_template, redirect, url_for
from flask_login import login_required, current_user
from datetime import datetime
import uuid
import json
import logging

from data.db_session import create_session
from data.chat_sessions import ChatSession
from data.chat_message import ChatMessage
from data.tasks import Task
from config import Config
from utils.constants import ERROR_MESSAGES

logger = logging.getLogger(__name__)
chat_bp = Blueprint('chat', __name__, template_folder='templates')


@chat_bp.route('/chat')
@login_required
def chat_page():
    """Главная страница чата"""
    session_id = request.args.get('session_id')
    user_initials = f"{current_user.surname[0]}{current_user.name[0]}"
    user_name = f"{current_user.name} {current_user.surname[0]}."
    user_full_name = f"{current_user.surname} {current_user.name} {current_user.patronymic or ''}".strip()

    # Если передан session_id, пытаемся найти чат
    if session_id:
        db_session = create_session()
        try:
            chat_session = db_session.query(ChatSession).filter_by(
                session_id=session_id,
                user_id=current_user.id
            ).first()

            if chat_session and chat_session.task_id:
                # Если есть задача, редиректим на чат задачи
                return redirect(url_for('chat.chat_for_task', task_id=chat_session.task_id))

            # Если сессия найдена, но без задачи, используем ее
            if chat_session:
                return render_template('chat.html',
                                       user_initials=user_initials,
                                       user_name=user_name,
                                       user_full_name=user_full_name,
                                       user_position=current_user.position,
                                       session_id=session_id)
        except Exception as e:
            logger.error(f"Ошибка при обработке session_id: {e}")
        finally:
            db_session.close()

    # Если session_id не передан или не найден, показываем общий чат
    return render_template('chat.html',
                           user_initials=user_initials,
                           user_name=user_name,
                           user_full_name=user_full_name,
                           user_position=current_user.position)


@chat_bp.route('/chat/session/<int:task_id>')
@login_required
def chat_for_task(task_id):
    """Страница чата для конкретной задачи"""
    session = create_session()

    try:
        # Проверяем существование задачи
        task = session.query(Task).filter_by(
            id=task_id,
            user_id=current_user.id
        ).first()

        if not task:
            return jsonify({
                'success': False,
                'error': 'Задача не найдена'
            }), 404

        # Ищем существующую сессию чата для задачи
        chat_session = session.query(ChatSession).filter_by(
            task_id=task_id,
            user_id=current_user.id
        ).first()

        # Если сессии нет, создаем новую
        if not chat_session:
            chat_session = ChatSession(
                user_id=current_user.id,
                task_id=task_id,
                session_id=str(uuid.uuid4()),
                title=f"Чат для задачи: {task.title}"
            )
            session.add(chat_session)

            # Создаем системное сообщение с использованием конфигурационного промпта
            task_info = Config.CHAT_PROMPTS['TASK_SYSTEM_MESSAGE'].format(
                task_title=task.title,
                due_date=task.due_date.strftime('%d.%m.%Y %H:%M') if task.due_date else 'Не указан',
                description=task.description or 'Нет описания'
            )

            system_message = ChatMessage(
                session_id=chat_session.id,
                role='system',
                content=task_info
            )
            session.add(system_message)

            # Создаем приветственное сообщение от ассистента с использованием конфигурационного промпта
            welcome_message = ChatMessage(
                session_id=chat_session.id,
                role='assistant',
                content=Config.CHAT_PROMPTS['WELCOME_MESSAGE'].format(task_title=task.title)
            )
            session.add(welcome_message)

            session.commit()
            session.refresh(chat_session)

        user_initials = f"{current_user.surname[0]}{current_user.name[0]}"
        user_name = f"{current_user.name} {current_user.surname[0]}."
        user_full_name = f"{current_user.surname} {current_user.name} {current_user.patronymic or ''}".strip()

        return render_template('chat.html',
                               user_initials=user_initials,
                               user_name=user_name,
                               user_full_name=user_full_name,
                               user_position=current_user.position,
                               task=task,
                               session_id=chat_session.session_id)


    except Exception as e:
        logger.error(f"Ошибка при открытии чата: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        session.close()


@chat_bp.route('/api/chat/sessions', methods=['GET'])
@login_required
def get_chat_sessions():
    """Получить все чат-сессии пользователя (API версия)"""
    try:
        db_session = create_session()
        sessions = db_session.query(ChatSession).filter_by(
            user_id=current_user.id
        ).order_by(ChatSession.last_activity.desc()).all()

        sessions_list = []
        for session_obj in sessions:
            session_dict = session_obj.to_dict()

            # Добавляем информацию о задаче
            if session_obj.task_id:
                task = db_session.query(Task).get(session_obj.task_id)
                if task:
                    session_dict['task'] = {
                        'id': task.id,
                        'title': task.title,
                        'due_date': task.due_date.isoformat() if task.due_date else None
                    }

            sessions_list.append(session_dict)

        return jsonify({
            'success': True,
            'sessions': sessions_list
        })

    except Exception as e:
        logger.error(f"Ошибка при получении сессий: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        db_session.close()


@chat_bp.route('/api/chat/messages', methods=['GET'])
@login_required
def get_messages():
    """Получить сообщения чат-сессии"""
    session_id = request.args.get('session_id')

    # Добавим параметр для отметки прочитанных
    mark_as_read = request.args.get('mark_as_read', 'false').lower() == 'true'

    if not session_id:
        return jsonify({
            'success': False,
            'error': 'Не указан session_id'
        }), 400

    db_session = create_session()

    try:
        # Проверяем доступ к сессии
        chat_session = db_session.query(ChatSession).filter_by(
            session_id=session_id,
            user_id=current_user.id
        ).first()

        if not chat_session:
            return jsonify({
                'success': False,
                'error': 'Сессия не найдена'
            }), 404

        # Получаем сообщения
        messages = db_session.query(ChatMessage).filter_by(
            session_id=chat_session.id
        ).order_by(ChatMessage.created_at.asc()).all()

        # Если запрос на отметку прочитанных, обновляем статус
        if mark_as_read:
            for message in messages:
                if message.role == 'assistant' and not message.is_read:
                    message.is_read = True
            db_session.commit()

        # Преобразуем в словари
        messages_list = []
        for msg in messages:
            messages_list.append({
                'id': msg.id,
                'role': msg.role,
                'content': msg.content,
                'created_at': msg.created_at.isoformat() if msg.created_at else None,
                'is_read': msg.is_read  # Добавляем флаг прочитанности
            })

        return jsonify({
            'success': True,
            'messages': messages_list,
            'session_title': chat_session.title,
            'unread_count': len([m for m in messages if m.role == 'assistant' and not m.is_read])
        })

    except Exception as e:
        logger.error(f"Ошибка при получении сообщений: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        db_session.close()


@chat_bp.route('/api/chat/mark-as-read', methods=['POST'])
@login_required
def mark_messages_as_read():
    """Отметить сообщения как прочитанные"""
    data = request.get_json()

    session_id = data.get('session_id')
    message_ids = data.get('message_ids', [])  # Список ID для отметки

    if not session_id:
        return jsonify({
            'success': False,
            'error': 'Не указан session_id'
        }), 400

    db_session = create_session()

    try:
        # Проверяем доступ к сессии
        chat_session = db_session.query(ChatSession).filter_by(
            session_id=session_id,
            user_id=current_user.id
        ).first()

        if not chat_session:
            return jsonify({
                'success': False,
                'error': 'Сессия не найдена'
            }), 404

        # Отмечаем указанные сообщения как прочитанные
        query = db_session.query(ChatMessage).filter(
            ChatMessage.session_id == chat_session.id,
            ChatMessage.role == 'assistant'
        )

        if message_ids:
            query = query.filter(ChatMessage.id.in_(message_ids))

        unread_messages = query.filter(ChatMessage.is_read == False).all()

        for message in unread_messages:
            message.is_read = True

        db_session.commit()

        return jsonify({
            'success': True,
            'message': f'Отмечено {len(unread_messages)} сообщений как прочитанные',
            'marked_count': len(unread_messages)
        })

    except Exception as e:
        db_session.rollback()
        logger.error(f"Ошибка при отметке сообщений как прочитанных: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        db_session.close()

@chat_bp.route('/api/chat/send', methods=['POST'])
@login_required
def send_message():
    """Отправить сообщение в чат с восстановленной логикой ИИ"""
    data = request.get_json()

    session_id = data.get('session_id')
    user_message_content = data.get('message')
    use_rag = data.get('use_rag', True)
    temperature = data.get('temperature', 0.7)

    if not session_id or not user_message_content:
        return jsonify({
            'success': False,
            'error': 'Не указаны session_id или message'
        }), 400

    db_session = create_session()

    try:
        # Получаем сессию
        chat_session = db_session.query(ChatSession).filter_by(
            session_id=session_id,
            user_id=current_user.id
        ).first()

        if not chat_session:
            return jsonify({
                'success': False,
                'error': 'Сессия не найдена'
            }), 404

        # Получаем историю сообщений
        history_messages = db_session.query(ChatMessage).filter_by(
            session_id=chat_session.id
        ).order_by(ChatMessage.created_at.asc()).all()

        # Форматируем историю для модели (берём последние 10 сообщений)
        history = []
        for msg in history_messages[-10:]:
            history.append({
                'role': msg.role,
                'content': msg.content
            })

        # Получаем ChatService из app context
        chat_service = current_app.chat_service

        # Генерируем ответ с использованием RAG (восстановленная логика)
        response_data = chat_service.generate_response_with_rag(
            user_message=user_message_content,
            history=history,
            use_rag=use_rag,
            temperature=temperature
        )

        if response_data.get('error'):
            return jsonify({
                'success': False,
                'error': response_data['error']
            }), 500

        # Сохраняем сообщение пользователя
        user_message = ChatMessage(
            session_id=chat_session.id,
            role='user',
            content=user_message_content
        )
        db_session.add(user_message)

        # Сохраняем ответ ассистента
        assistant_message = ChatMessage(
            session_id=chat_session.id,
            role='assistant',
            content=response_data['response'],
            is_read=False  # Явно устанавливаем как непрочитанное
        )
        db_session.add(assistant_message)

        # Обновляем время последней активности
        chat_session.last_activity = datetime.utcnow()
        db_session.commit()

        return jsonify({
            'success': True,
            'user_message': user_message.to_dict(),
            'assistant_message': assistant_message.to_dict(),
            'response_metadata': {
                'model': response_data.get('model'),
                'tokens_used': response_data.get('tokens_used'),
                'context_documents': response_data.get('context_documents', []),
                'has_context': response_data.get('has_context', False)
            }
        })

    except Exception as e:
        db_session.rollback()
        logger.error(f"Ошибка при отправке сообщения: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        db_session.close()


@chat_bp.route('/api/chat/stream', methods=['POST'])
@login_required
def stream_message():
    """Потоковая отправка сообщения (восстановленная логика)"""
    data = request.get_json()

    session_id = data.get('session_id')
    user_message_content = data.get('message')
    use_rag = data.get('use_rag', True)
    temperature = data.get('temperature', 0.7)

    if not session_id or not user_message_content:
        return jsonify({
            'success': False,
            'error': 'Не указаны session_id или message'
        }), 400

    db_session = create_session()

    try:
        # Получаем сессию
        chat_session = db_session.query(ChatSession).filter_by(
            session_id=session_id,
            user_id=current_user.id
        ).first()

        if not chat_session:
            return jsonify({
                'success': False,
                'error': 'Сессия не найдена'
            }), 404

        # Получаем историю
        history_messages = db_session.query(ChatMessage).filter_by(
            session_id=chat_session.id
        ).order_by(ChatMessage.created_at.asc()).all()

        history = []
        for msg in history_messages[-10:]:
            history.append({
                'role': msg.role,
                'content': msg.content
            })

        # Сохраняем сообщение пользователя
        user_message = ChatMessage(
            session_id=chat_session.id,
            role='user',
            content=user_message_content
        )
        db_session.add(user_message)
        chat_session.last_activity = datetime.utcnow()
        db_session.commit()

        # Создаем функцию для потоковой генерации
        def generate():
            chat_service = current_app.chat_service
            full_response = []

            # Потоковая генерация
            for chunk in chat_service.stream_response_with_rag(
                    user_message=user_message_content,
                    history=history,
                    use_rag=use_rag,
                    temperature=temperature
            ):
                full_response.append(chunk)
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"

            # Сохраняем полный ответ
            assistant_message = ChatMessage(
                session_id=chat_session.id,
                role='assistant',
                content=''.join(full_response)
            )
            db_session.add(assistant_message)
            db_session.commit()

            yield f"data: {json.dumps({'done': True})}\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no'
            }
        )

    except Exception as e:
        db_session.rollback()
        logger.error(f"Ошибка при потоковой отправке сообщения: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        db_session.close()


@chat_bp.route('/api/chat/sessions/create', methods=['POST'])
@login_required
def create_chat_session():
    """Создать новую чат-сессию (восстановленная логика)"""
    data = request.get_json()

    db_session = create_session()
    try:
        # Создаем новую сессию
        chat_session = ChatSession(
            user_id=current_user.id,
            task_id=data.get('task_id'),
            session_id=data.get('session_id') or f"session_{datetime.utcnow().timestamp()}",
            title=data.get('title', 'Новая беседа')
        )

        db_session.add(chat_session)

        # Создаем приветственное сообщение от системы
        welcome_message = ChatMessage(
            session_id=chat_session.id,
            role='assistant',
            content="Здравствуйте! Я ваш ассистент по управлению проектами и документами. Чем могу помочь?"
        )

        db_session.add(welcome_message)
        db_session.commit()

        return jsonify({
            'success': True,
            'message': 'Чат-сессия создана успешно',
            'session': chat_session.to_dict(),
            'welcome_message': welcome_message.to_dict()
        })

    except Exception as e:
        db_session.rollback()
        logger.error(f"Ошибка при создании сессии: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        db_session.close()


@chat_bp.route('/api/chat/sessions/<string:session_id>', methods=['DELETE'])
@login_required
def delete_chat_session(session_id):
    """Удалить чат-сессию"""
    db_session = create_session()

    try:
        chat_session = db_session.query(ChatSession).filter_by(
            session_id=session_id,
            user_id=current_user.id
        ).first()

        if not chat_session:
            return jsonify({
                'success': False,
                'error': 'Сессия не найдена'
            }), 404

        # Удаляем все сообщения сессии
        db_session.query(ChatMessage).filter_by(session_id=chat_session.id).delete()
        db_session.delete(chat_session)
        db_session.commit()

        return jsonify({
            'success': True,
            'message': 'Чат-сессия удалена успешно'
        })

    except Exception as e:
        db_session.rollback()
        logger.error(f"Ошибка при удалении сессии: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        db_session.close()


@chat_bp.route('/api/chat/ask', methods=['POST'])
@login_required
def ask_question_direct():
    """Задать вопрос напрямую (без сохранения в историю, восстановленная логика)"""
    data = request.get_json()

    question = data.get('question')
    use_rag = data.get('use_rag', True)
    temperature = data.get('temperature', 0.7)

    if not question:
        return jsonify({
            'success': False,
            'error': 'Вопрос не может быть пустым'
        }), 400

    try:
        chat_service = current_app.chat_service

        # Генерируем ответ с использованием RAG
        response_data = chat_service.generate_response_with_rag(
            user_message=question,
            use_rag=use_rag,
            temperature=temperature
        )

        if response_data.get('error'):
            return jsonify({
                'success': False,
                'error': response_data['error']
            }), 500

        return jsonify({
            'success': True,
            'question': question,
            'answer': response_data['response'],
            'metadata': {
                'model': response_data.get('model'),
                'tokens_used': response_data.get('tokens_used'),
                'context_documents': response_data.get('context_documents', []),
                'has_context': response_data.get('has_context', False)
            }
        })

    except Exception as e:
        logger.error(f"Ошибка при прямом запросе: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@chat_bp.route('/api/chat/unread-count', methods=['GET'])
@login_required
def get_unread_messages_count():
    """Получить количество непрочитанных сообщений пользователя"""
    db_session = create_session()

    try:
        # Получаем все чат-сессии пользователя
        chat_sessions = db_session.query(ChatSession).filter_by(
            user_id=current_user.id
        ).all()

        total_unread = 0
        sessions_with_unread = []

        for session in chat_sessions:
            # Подсчитываем непрочитанные сообщения в сессии
            unread_count = db_session.query(ChatMessage).filter(
                ChatMessage.session_id == session.id,
                ChatMessage.role == 'assistant',
                ChatMessage.is_read == False
            ).count()

            if unread_count > 0:
                total_unread += unread_count

                # Получаем информацию о задаче, если есть
                task_info = None
                if session.task_id:
                    task = db_session.query(Task).get(session.task_id)
                    if task:
                        task_info = {
                            'id': task.id,
                            'title': task.title,
                            'due_date': task.due_date.isoformat() if task.due_date else None
                        }

                sessions_with_unread.append({
                    'session_id': session.session_id,
                    'title': session.title or f"Чат #{session.id}",
                    'task': task_info,
                    'unread_count': unread_count,
                    'last_message_time': None
                })

        # Получаем время последнего непрочитанного сообщения
        for session_info in sessions_with_unread:
            last_message = db_session.query(ChatMessage).filter(
                ChatMessage.session_id == session_info['session_id'],
                ChatMessage.role == 'assistant',
                ChatMessage.is_read == False
            ).order_by(ChatMessage.created_at.desc()).first()

            if last_message:
                session_info['last_message_time'] = last_message.created_at.isoformat()

        return jsonify({
            'success': True,
            'total_unread': total_unread,
            'sessions_with_unread': sessions_with_unread,
            'has_unread': total_unread > 0
        })

    except Exception as e:
        logger.error(f"Ошибка при получении непрочитанных сообщений: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        db_session.close()


@chat_bp.route('/api/chat/mark-all-as-read', methods=['POST'])
@login_required
def mark_all_as_read():
    """Отметить все сообщения пользователя как прочитанные"""
    db_session = create_session()

    try:
        # Получаем все чат-сессии пользователя
        chat_sessions = db_session.query(ChatSession).filter_by(
            user_id=current_user.id
        ).all()

        total_marked = 0

        for session in chat_sessions:
            # Находим все непрочитанные сообщения в сессии
            unread_messages = db_session.query(ChatMessage).filter(
                ChatMessage.session_id == session.id,
                ChatMessage.role == 'assistant',
                ChatMessage.is_read == False
            ).all()

            # Отмечаем как прочитанные
            for message in unread_messages:
                message.is_read = True
                total_marked += 1

        db_session.commit()

        return jsonify({
            'success': True,
            'message': f'Отмечено {total_marked} сообщений как прочитанные',
            'marked_count': total_marked
        })

    except Exception as e:
        db_session.rollback()
        logger.error(f"Ошибка при отметке всех сообщений как прочитанных: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        db_session.close()


@chat_bp.route('/api/chat/session/by-id/<string:session_id>', methods=['GET'])
@login_required
def get_chat_session_by_id(session_id):
    """Получить информацию о чат-сессии по session_id"""
    db_session = create_session()

    try:
        chat_session = db_session.query(ChatSession).filter_by(
            session_id=session_id,
            user_id=current_user.id
        ).first()

        if not chat_session:
            return jsonify({
                'success': False,
                'error': 'Сессия не найдена'
            }), 404

        # Получаем информацию о задаче, если есть
        task_info = None
        if chat_session.task_id:
            task = db_session.query(Task).get(chat_session.task_id)
            if task:
                task_info = {
                    'id': task.id,
                    'title': task.title
                }

        return jsonify({
            'success': True,
            'session': {
                'id': chat_session.id,
                'session_id': chat_session.session_id,
                'title': chat_session.title,
                'task_id': chat_session.task_id,
                'task': task_info,
                'created_at': chat_session.created_at.isoformat() if chat_session.created_at else None,
                'last_activity': chat_session.last_activity.isoformat() if chat_session.last_activity else None
            }
        })

    except Exception as e:
        logger.error(f"Ошибка при получении сессии: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        db_session.close()


@chat_bp.route('/api/chat/get-task-id/<string:session_id>', methods=['GET'])
@login_required
def get_task_id_by_session(session_id):
    """Получить task_id по session_id"""
    db_session = create_session()

    try:
        chat_session = db_session.query(ChatSession).filter_by(
            session_id=session_id,
            user_id=current_user.id
        ).first()

        if not chat_session:
            return jsonify({
                'success': False,
                'error': 'Сессия не найдена'
            }), 404

        return jsonify({
            'success': True,
            'session_id': session_id,
            'task_id': chat_session.task_id,
            'has_task': chat_session.task_id is not None
        })

    except Exception as e:
        logger.error(f"Ошибка при получении task_id: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        db_session.close()