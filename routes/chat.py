# routes/chat.py
from flask import Blueprint, request, jsonify, stream_with_context, Response, current_app, render_template, redirect, url_for
from flask_login import login_required, current_user
from datetime import datetime
import uuid
import json
import logging
from contextlib import contextmanager
from typing import Optional, List, Dict
import time
from threading import Thread, Lock
import queue

from sqlalchemy import func, desc
from data.db_session import create_session
from data.chat_sessions import ChatSession
from data.chat_message import ChatMessage
from data.tasks import Task
from config import Config

logger = logging.getLogger(__name__)
chat_bp = Blueprint('chat', __name__, template_folder='templates')

# Глобальные структуры для фоновой генерации
_generation_tasks = {}  # map message_id -> { thread, queue, done, chat_session_id, started_at, last_seq }
_generation_tasks_lock = Lock()
_SSE_WAIT_TIMEOUT = 15.0  # секунд ожидания записи из очереди


@contextmanager
def session_scope():
    """Контекстный менеджер для сессии БД: гарантированное закрытие."""
    session = create_session()
    try:
        yield session
    finally:
        session.close()


def build_user_info(user):
    """Сформировать пользовательские поля (инициалы, имя, полное имя)."""
    initials = f"{user.surname[0]}{user.name[0]}"
    short_name = f"{user.name} {user.surname[0]}."
    full_name = f"{user.surname} {user.name} {user.patronymic or ''}".strip()
    return initials, short_name, full_name


def get_task_info_map(session, task_ids: List[int]) -> Dict[int, Dict]:
    """Загрузить задачи по списку id одним запросом и вернуть словарь."""
    if not task_ids:
        return {}
    tasks = session.query(Task).filter(Task.id.in_(task_ids)).all()
    return {
        t.id: {
            'id': t.id,
            'title': t.title,
            'due_date': t.due_date.isoformat() if t.due_date else None
        } for t in tasks
    }


# ----------------- Фоновый воркер и менеджер задач генерации -----------------
def _generation_worker(assistant_message_id: int,
                       chat_session_id: int,
                       user_message: str,
                       history: List[Dict],
                       use_rag: bool,
                       temperature: float,
                       out_queue: "queue.Queue",
                       done_flag: Dict[str, bool],
                       chat_service,
                       system_prompt: Optional[str] = None):   # <-- добавлено
    """
    Фоновый воркер, который берет стрим от chat_service.stream_response_with_rag,
    ...
    """
    db_sess = create_session()
    try:
        accumulated = []
        seq = 0
        try:
            # Обратите внимание: передаём system_prompt в stream_response_with_rag
            for chunk in chat_service.stream_response_with_rag(
                    user_message=user_message,
                    history=history,
                    use_rag=use_rag,
                    temperature=temperature,
                    system_prompt=system_prompt
            ):
                chunk_text = str(chunk or '')
                # Пропускаем пустые чанки
                if chunk_text == '':
                    continue

                seq += 1
                accumulated.append(chunk_text)

                # Сохраняем прогресс в БД (assistant_message.content)
                try:
                    msg = db_sess.query(ChatMessage).get(assistant_message_id)
                    if msg:
                        msg.content = ''.join(accumulated)
                        db_sess.add(msg)
                        db_sess.commit()
                except Exception:
                    logger.exception("Ошибка при сохранении промежуточного контента в DB (worker)")

                # Кладём в очередь для подписчиков вместе с seq
                try:
                    out_queue.put_nowait({'chunk': chunk_text, 'seq': seq})
                except queue.Full:
                    logger.warning("Очередь переполнена для message_id %s", assistant_message_id)

                # Обновляем last_seq в глобальной структуре
                try:
                    with _generation_tasks_lock:
                        task = _generation_tasks.get(assistant_message_id)
                        if task:
                            task['last_seq'] = seq

                        # --- проверка флага cancelled ---
                        if task and task.get('cancelled'):
                            logger.info("Worker noticed cancellation for message_id %s, stopping.",
                                        assistant_message_id)
                            # Пометим в БД, что генерация прервана
                            try:
                                msg = db_sess.query(ChatMessage).get(assistant_message_id)
                                if msg:
                                    msg.content = ''.join(accumulated) + "\n\n(Генерация прервана пользователем)"
                                    db_sess.add(msg)
                                    db_sess.commit()
                            except Exception:
                                logger.exception("Ошибка при пометке прерванного сообщения в DB (worker)")

                            # Положим final done в очередь (со знаком cancelled)
                            try:
                                out_queue.put_nowait({'done': True, 'final_seq': seq, 'cancelled': True})
                            except queue.Full:
                                try:
                                    out_queue.put({'done': True, 'final_seq': seq, 'cancelled': True}, timeout=1.0)
                                except Exception:
                                    pass

                            # пометим done_flag и выйдем из цикла
                            done_flag['done'] = True
                            return
                except Exception:
                    logger.exception("Ошибка при обновлении last_seq в task")

        except Exception:
            logger.exception("Ошибка в воркере потоковой генерации для message_id %s", assistant_message_id)

        # Финальное сохранение и отправка final_seq
        try:
            msg = db_sess.query(ChatMessage).get(assistant_message_id)
            if msg:
                msg.content = ''.join(accumulated)
                db_sess.add(msg)
                db_sess.commit()
        except Exception:
            logger.exception("Ошибка при финальном сохранении assistant_message (worker)")

        try:
            out_queue.put_nowait({'done': True, 'final_seq': seq})
        except queue.Full:
            try:
                out_queue.put({'done': True, 'final_seq': seq}, timeout=1.0)
            except Exception:
                pass

        # Обновляем last_seq ещё раз
        try:
            with _generation_tasks_lock:
                task = _generation_tasks.get(assistant_message_id)
                if task:
                    task['last_seq'] = seq
        except Exception:
            logger.exception("Ошибка при финальном обновлении last_seq")

    finally:
        done_flag['done'] = True
        try:
            db_sess.close()
        except Exception:
            logger.exception("Ошибка при закрытии db_session в воркере")

        # Небольшая задержка перед удалением задачи, чтобы клиенты успели прочитать done
        def _delayed_cleanup(mid):
            time.sleep(10.0)
            with _generation_tasks_lock:
                _generation_tasks.pop(mid, None)
        Thread(target=_delayed_cleanup, args=(assistant_message_id,), daemon=True).start()


def start_generation_task(assistant_message_id: int,
                          chat_session_id: int,
                          user_message: str,
                          history: List[Dict],
                          use_rag: bool,
                          temperature: float,
                          chat_service,
                          system_prompt: Optional[str] = None):   # <-- добавлен
    """
    Запустить фоновую задачу для assistant_message_id.
    Возвращает структуру задачи из _generation_tasks.
    """
    with _generation_tasks_lock:
        if assistant_message_id in _generation_tasks:
            return _generation_tasks[assistant_message_id]

        q = queue.Queue(maxsize=1000)
        done_flag = {'done': False}
        t = Thread(target=_generation_worker,
                   args=(assistant_message_id, chat_session_id, user_message, history, use_rag, temperature, q, done_flag, chat_service, system_prompt),
                   daemon=True)
        _generation_tasks[assistant_message_id] = {
            'thread': t,
            'queue': q,
            'done': done_flag,
            'chat_session_id': chat_session_id,
            'started_at': datetime.utcnow(),
            'last_seq': 0,
            'cancelled': False
        }
        t.start()
        return _generation_tasks[assistant_message_id]


# ----------------- REST / UI endpoints (основные) -----------------

@chat_bp.route('/chat')
@login_required
def chat_page():
    """Главная страница чата"""
    session_id = request.args.get('session_id')
    user_initials, user_name, user_full_name = build_user_info(current_user)

    if session_id:
        with session_scope() as db_session:
            try:
                chat_session = db_session.query(ChatSession).filter_by(
                    session_id=session_id,
                    user_id=current_user.id
                ).first()

                if chat_session and chat_session.task_id:
                    return redirect(url_for('chat.chat_for_task', task_id=chat_session.task_id))

                if chat_session:
                    return render_template('chat.html',
                                           user_initials=user_initials,
                                           user_name=user_name,
                                           user_full_name=user_full_name,
                                           user_position=current_user.position,
                                           session_id=session_id)
            except Exception:
                logger.exception("Ошибка при обработке session_id")

    return render_template('chat.html',
                           user_initials=user_initials,
                           user_name=user_name,
                           user_full_name=user_full_name,
                           user_position=current_user.position)


@chat_bp.route('/chat/session/<int:task_id>')
@login_required
def chat_for_task(task_id):
    """Страница чата для конкретной задачи"""
    with session_scope() as session:
        try:
            task = session.query(Task).filter_by(id=task_id, user_id=current_user.id).first()
            if not task:
                return jsonify({'success': False, 'error': 'Задача не найдена'}), 404

            chat_session = session.query(ChatSession).filter_by(task_id=task_id, user_id=current_user.id).first()

            if not chat_session:
                # Создаём сессию и системные сообщения
                chat_session = ChatSession(
                    user_id=current_user.id,
                    task_id=task_id,
                    session_id=str(uuid.uuid4()),
                    title=f"Чат для задачи: {task.title}"
                )
                session.add(chat_session)
                session.flush()  # чтобы получить chat_session.id до добавления сообщений

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

                welcome_message = ChatMessage(
                    session_id=chat_session.id,
                    role='assistant',
                    content=Config.CHAT_PROMPTS['WELCOME_MESSAGE'].format(task_title=task.title),
                    is_read=False
                )
                session.add(welcome_message)

                session.commit()
                session.refresh(chat_session)

            user_initials, user_name, user_full_name = build_user_info(current_user)
            return render_template('chat.html',
                                   user_initials=user_initials,
                                   user_name=user_name,
                                   user_full_name=user_full_name,
                                   user_position=current_user.position,
                                   task=task,
                                   session_id=chat_session.session_id)

        except Exception:
            logger.exception("Ошибка при открытии чата")
            return jsonify({'success': False, 'error': 'Internal server error'}), 500


@chat_bp.route('/api/chat/sessions', methods=['GET'])
@login_required
def get_chat_sessions():
    """Получить все чат-сессии пользователя (API версия)"""
    with session_scope() as db_session:
        try:
            sessions = db_session.query(ChatSession).filter_by(user_id=current_user.id).order_by(
                ChatSession.last_activity.desc()).all()

            # Подготовим карту задач, чтобы не делать N запросов
            task_ids = [s.task_id for s in sessions if s.task_id]
            tasks_map = get_task_info_map(db_session, task_ids)

            sessions_list = []
            for s in sessions:
                sd = s.to_dict()
                if s.task_id and s.task_id in tasks_map:
                    sd['task'] = tasks_map[s.task_id]
                sessions_list.append(sd)

            return jsonify({'success': True, 'sessions': sessions_list})
        except Exception:
            logger.exception("Ошибка при получении сессий")
            return jsonify({'success': False, 'error': 'Internal server error'}), 500


@chat_bp.route('/api/chat/messages', methods=['GET'])
@login_required
def get_messages():
    """Получить сообщения чат-сессии"""
    session_id = request.args.get('session_id')
    mark_as_read = request.args.get('mark_as_read', 'false').lower() == 'true'

    if not session_id:
        return jsonify({'success': False, 'error': 'Не указан session_id'}), 400

    with session_scope() as db_session:
        try:
            chat_session = db_session.query(ChatSession).filter_by(session_id=session_id, user_id=current_user.id).first()
            if not chat_session:
                return jsonify({'success': False, 'error': 'Сессия не найдена'}), 404

            messages = db_session.query(ChatMessage).filter_by(session_id=chat_session.id).order_by(
                ChatMessage.created_at.asc()).all()

            if mark_as_read:
                # Массовое обновление
                update_q = db_session.query(ChatMessage).filter(
                    ChatMessage.session_id == chat_session.id,
                    ChatMessage.role == 'assistant',
                    ChatMessage.is_read == False
                )
                updated = update_q.update({'is_read': True}, synchronize_session=False)
                if updated:
                    db_session.commit()

            messages_list = [{
                'id': m.id,
                'role': m.role,
                'content': m.content,
                'created_at': m.created_at.isoformat() if m.created_at else None,
                'is_read': m.is_read
            } for m in messages]

            unread_count = sum(1 for m in messages if m.role == 'assistant' and not m.is_read)

            return jsonify({
                'success': True,
                'messages': messages_list,
                'session_title': chat_session.title,
                'unread_count': unread_count
            })

        except Exception:
            logger.exception("Ошибка при получении сообщений")
            return jsonify({'success': False, 'error': 'Internal server error'}), 500


@chat_bp.route('/api/chat/stream/active', methods=['GET'])
@login_required
def get_active_streams_for_session():
    """
    Вернуть активные фоновые генерации (message_id и last_seq и текущее содержимое) для session_id.
    Ответ: { success: True, active: [ { message_id, content, done, last_seq, started_at } ] }
    """
    session_id = request.args.get('session_id')
    if not session_id:
        return jsonify({'success': False, 'error': 'Не указан session_id'}), 400

    with session_scope() as db_sess:
        chat_session = db_sess.query(ChatSession).filter_by(session_id=session_id, user_id=current_user.id).first()
        if not chat_session:
            return jsonify({'success': False, 'error': 'Сессия не найдена'}), 404

        result = []
        with _generation_tasks_lock:
            for mid, task in _generation_tasks.items():
                if task.get('chat_session_id') == chat_session.id:
                    # подтянем текущее содержимое из DB
                    try:
                        msg = db_sess.query(ChatMessage).get(int(mid))
                        content = msg.content if msg else ''
                    except Exception:
                        content = ''
                    result.append({
                        'message_id': int(mid),
                        'content': content,
                        'done': bool(task['done'].get('done')),
                        'last_seq': int(task.get('last_seq') or 0),
                        'started_at': task.get('started_at').isoformat() if task.get('started_at') else None
                    })

        return jsonify({'success': True, 'active': result})


@chat_bp.route('/api/chat/mark-as-read', methods=['POST'])
@login_required
def mark_messages_as_read():
    """Отметить сообщения как прочитанные"""
    data = request.get_json(silent=True) or {}
    session_id = data.get('session_id')
    message_ids = data.get('message_ids')

    if not session_id:
        return jsonify({'success': False, 'error': 'Не указан session_id'}), 400

    with session_scope() as db_session:
        try:
            chat_session = db_session.query(ChatSession).filter_by(session_id=session_id, user_id=current_user.id).first()
            if not chat_session:
                return jsonify({'success': False, 'error': 'Сессия не найдена'}), 404

            query = db_session.query(ChatMessage).filter(
                ChatMessage.session_id == chat_session.id,
                ChatMessage.role == 'assistant',
                ChatMessage.is_read == False
            )
            if message_ids:
                query = query.filter(ChatMessage.id.in_(message_ids))

            marked = query.update({'is_read': True}, synchronize_session=False)
            db_session.commit()

            return jsonify({
                'success': True,
                'message': f'Отмечено {marked} сообщений как прочитанные',
                'marked_count': marked
            })

        except Exception:
            db_session.rollback()
            logger.exception("Ошибка при отметке сообщений как прочитанных")
            return jsonify({'success': False, 'error': 'Internal server error'}), 500


@chat_bp.route('/api/chat/send', methods=['POST'])
@login_required
def send_message():
    """Отправить сообщение в чат с восстановленной логикой ИИ (синхронный режим, без потока)"""
    data = request.get_json(silent=True) or {}
    session_id = data.get('session_id')
    user_message_content = data.get('message')
    use_rag = data.get('use_rag', True)
    temperature = data.get('temperature', 0.7)

    if not session_id or not user_message_content:
        return jsonify({'success': False, 'error': 'Не указаны session_id или message'}), 400

    with session_scope() as db_session:
        try:
            chat_session = db_session.query(ChatSession).filter_by(session_id=session_id, user_id=current_user.id).first()
            if not chat_session:
                return jsonify({'success': False, 'error': 'Сессия не найдена'}), 404

            # Получаем последние 10 сообщений истории
            history_messages = db_session.query(ChatMessage).filter_by(session_id=chat_session.id).order_by(
                ChatMessage.created_at.asc()).all()
            history = [{'role': m.role, 'content': m.content} for m in history_messages[-10:]]

            # Сохраняем сообщение пользователя до генерации
            user_message = ChatMessage(session_id=chat_session.id, role='user', content=user_message_content)
            db_session.add(user_message)
            chat_session.last_activity = datetime.utcnow()
            db_session.commit()
            system_prompt = None
            sys_msg = db_session.query(ChatMessage).filter_by(session_id=chat_session.id, role='system').order_by(
                ChatMessage.created_at.asc()).first()
            if sys_msg:
                system_prompt = sys_msg.content
            chat_service = current_app.chat_service
            response_data = chat_service.generate_response_with_rag(
                user_message=user_message_content,
                history=history,
                use_rag=use_rag,
                temperature=temperature,
                system_prompt=system_prompt  # <-- передаём сюда
            )

            if response_data.get('error'):
                return jsonify({'success': False, 'error': response_data['error']}), 500

            assistant_message = ChatMessage(
                session_id=chat_session.id,
                role='assistant',
                content=response_data['response'],
                is_read=False
            )
            db_session.add(assistant_message)
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

        except Exception:
            db_session.rollback()
            logger.exception("Ошибка при отправке сообщения")
            return jsonify({'success': False, 'error': 'Internal server error'}), 500


@chat_bp.route('/api/chat/stream', methods=['POST'])
@login_required
def stream_message():
    """
    SSE endpoint для потоковой генерации и подписки.
    Поддерживает два варианта входа:
    1) { session_id, message } — запускает новую генерацию и подписывает клиента на неё.
    2) { session_id, assistant_message_id, last_seq } — подписка на уже идущую задачу; last_seq — последний seq, который клиент уже имеет.
    """
    data = request.get_json(silent=True) or {}
    session_id = data.get('session_id')
    user_message_content = data.get('message')
    assistant_id = data.get('assistant_message_id')
    client_last_seq = int(data.get('last_seq', 0))
    use_rag = data.get('use_rag', True)
    temperature = data.get('temperature', 0.7)

    if not session_id:
        return jsonify({'success': False, 'error': 'Не указан session_id'}), 400

    db_session = create_session()
    try:
        chat_session = db_session.query(ChatSession).filter_by(session_id=session_id, user_id=current_user.id).first()
        if not chat_session:
            db_session.close()
            return jsonify({'success': False, 'error': 'Сессия не найдена'}), 404

        # Получаем историю
        history_messages = db_session.query(ChatMessage).filter_by(session_id=chat_session.id).order_by(
            ChatMessage.created_at.asc()).all()
        history = [{'role': m.role, 'content': m.content} for m in history_messages[-10:]]

        # Если клиент прислал assistant_message_id -> подписка
        if assistant_id:
            assistant_id = int(assistant_id)
            # Попытаемся найти таск в _generation_tasks
            with _generation_tasks_lock:
                task = _generation_tasks.get(assistant_id)

            # Получим текущее содержимое из БД (на всякий случай)
            current_content = ''
            try:
                msg = db_session.query(ChatMessage).get(assistant_id)
                if msg:
                    current_content = msg.content or ''
            except Exception:
                logger.exception("Ошибка чтения assistant_message из БД в stream")

            def gen_subscribe():
                try:
                    # Отправляем initial header с message_id и текущим server_last_seq
                    server_last_seq = 0
                    if task:
                        server_last_seq = int(task.get('last_seq', 0))
                    initial_payload = {
                        'message_id': assistant_id,
                        'initial': True,
                        'initial_chunk': current_content or '',
                        'last_seq': server_last_seq
                    }
                    yield f"data: {json.dumps(initial_payload)}\n\n"

                    # Если нет фоновой задачи — шлём done и завершаем (т.е. задача завершена)
                    if not task:
                        yield f"data: {json.dumps({'message_id': assistant_id, 'done': True, 'final_seq': server_last_seq})}\n\n"
                        return

                    q = task['queue']
                    done_flag = task['done']

                    # Читаем из очереди до тех пор, пока не получим done или внешний таймаут
                    # Фильтруем элементы с seq <= client_last_seq
                    while True:
                        try:
                            item = q.get(timeout=_SSE_WAIT_TIMEOUT)
                        except queue.Empty:
                            # Проверим флаг done; если done и очередь пуста — завершаем
                            if done_flag.get('done', False):
                                yield f"data: {json.dumps({'message_id': assistant_id, 'done': True, 'final_seq': int(task.get('last_seq', 0))})}\n\n"
                                break
                            # Иначе продолжаем ждать
                            continue

                        if 'seq' in item:
                            seq = int(item['seq'])
                            if seq <= client_last_seq:
                                # этот чанк клиент уже имеет — игнорируем
                                continue
                            payload = {'message_id': assistant_id, 'chunk': item['chunk'], 'seq': seq}
                            yield f"data: {json.dumps(payload)}\n\n"
                        elif 'done' in item:
                            final_seq = int(item.get('final_seq', 0))
                            yield f"data: {json.dumps({'message_id': assistant_id, 'done': True, 'final_seq': final_seq})}\n\n"
                            break

                except GeneratorExit:
                    logger.info("Клиент закрыл подписку на assistant_id %s", assistant_id)
                except Exception:
                    logger.exception("Ошибка в генераторе подписки stream")
                    try:
                        yield f"data: {json.dumps({'message_id': assistant_id, 'error': 'Internal stream error'})}\n\n"
                    except Exception:
                        pass
                finally:
                    # leave db session open until Response finished; will be closed by outer finally
                    pass

            return Response(
                stream_with_context(gen_subscribe()),
                mimetype='text/event-stream',
                headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
            )

        # Если пришёл новый message — создаём assistant_message и запускаем фон. таск
        if user_message_content:
            # Сохраняем сообщение пользователя
            user_message = ChatMessage(session_id=chat_session.id, role='user', content=user_message_content)
            db_session.add(user_message)
            chat_session.last_activity = datetime.utcnow()
            db_session.commit()

            # Создаём assistant_message-заготовку
            assistant_message = ChatMessage(session_id=chat_session.id, role='assistant', content='', is_read=False)
            db_session.add(assistant_message)
            db_session.commit()
            assistant_message_id = int(assistant_message.id)

            # Запускаем фоновую задачу (передаём chat_service)
            chat_service = current_app.chat_service
            system_prompt = None
            try:
                sys_msg = db_session.query(ChatMessage).filter_by(session_id=chat_session.id, role='system').order_by(
                    ChatMessage.created_at.asc()).first()
                if sys_msg:
                    system_prompt = sys_msg.content
            except Exception:
                logger.exception("Не удалось получить system message для session_id %s", session_id)

            start_generation_task(
                assistant_message_id=assistant_message_id,
                chat_session_id=chat_session.id,
                user_message=user_message_content,
                history=history,
                use_rag=use_rag,
                temperature=temperature,
                chat_service=chat_service,
                system_prompt=system_prompt
            )

            # Подписываемся на эту задачу (аналогично блоку выше)
            with _generation_tasks_lock:
                task = _generation_tasks.get(assistant_message_id)

            def gen_new():
                try:
                    # Отправляем initial header с message_id и server_last_seq (0)
                    initial_payload = {
                        'message_id': assistant_message_id,
                        'initial': True,
                        'initial_chunk': '' if not task else (
                                    db_session.query(ChatMessage).get(assistant_message_id).content or ''),
                        'last_seq': int(task.get('last_seq', 0)) if task else 0
                    }
                    yield f"data: {json.dumps(initial_payload)}\n\n"

                    if not task:
                        # нет задачи — завершаем
                        yield f"data: {json.dumps({'message_id': assistant_message_id, 'done': True, 'final_seq': 0})}\n\n"
                        return

                    q = task['queue']
                    done_flag = task['done']

                    while True:
                        try:
                            item = q.get(timeout=_SSE_WAIT_TIMEOUT)
                        except queue.Empty:
                            if done_flag.get('done', False):
                                yield f"data: {json.dumps({'message_id': assistant_message_id, 'done': True, 'final_seq': int(task.get('last_seq', 0))})}\n\n"
                                break
                            continue

                        if 'seq' in item:
                            payload = {'message_id': assistant_message_id, 'chunk': item['chunk'], 'seq': int(item['seq'])}
                            yield f"data: {json.dumps(payload)}\n\n"
                        elif 'done' in item:
                            final_seq = int(item.get('final_seq', 0))
                            yield f"data: {json.dumps({'message_id': assistant_message_id, 'done': True, 'final_seq': final_seq})}\n\n"
                            break

                except GeneratorExit:
                    logger.info("Клиент закрыл подписку на новую генерацию %s", assistant_message_id)
                except Exception:
                    logger.exception("Ошибка в генераторе новой stream")
                    try:
                        yield f"data: {json.dumps({'message_id': assistant_message_id, 'error': 'Internal stream error'})}\n\n"
                    except Exception:
                        pass

            return Response(
                stream_with_context(gen_new()),
                mimetype='text/event-stream',
                headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
            )

        # Если нет ни assistant_id ни message
        db_session.close()
        return jsonify({'success': False, 'error': 'Не указан message или assistant_message_id'}), 400

    except Exception:
        logger.exception("Ошибка при потоковой отправке сообщения")
        try:
            db_session.close()
        except Exception:
            pass
        return jsonify({'success': False, 'error': 'Internal server error'}), 500
    finally:
        # не закрываем db_session здесь — генератор/Response использует его, но после выхода закрываем
        pass


@chat_bp.route('/api/chat/sessions/create', methods=['POST'])
@login_required
def create_chat_session():
    """Создать новую чат-сессию (восстановленная логика)"""
    data = request.get_json(silent=True) or {}
    with session_scope() as db_session:
        try:
            chat_session = ChatSession(
                user_id=current_user.id,
                task_id=data.get('task_id'),
                session_id=data.get('session_id') or f"session_{datetime.utcnow().timestamp()}",
                title=data.get('title', 'Новая беседа')
            )
            db_session.add(chat_session)
            db_session.flush()  # чтобы получить id

            welcome_message = ChatMessage(
                session_id=chat_session.id,
                role='assistant',
                content="Здравствуйте! Я ваш ассистент по управлению проектами и документами. Чем могу помочь?",
                is_read=False
            )
            db_session.add(welcome_message)
            db_session.commit()

            return jsonify({
                'success': True,
                'message': 'Чат-сессия создана успешно',
                'session': chat_session.to_dict(),
                'welcome_message': welcome_message.to_dict()
            })
        except Exception:
            db_session.rollback()
            logger.exception("Ошибка при создании сессии")
            return jsonify({'success': False, 'error': 'Internal server error'}), 500


@chat_bp.route('/api/chat/sessions/<string:session_id>', methods=['DELETE'])
@login_required
def delete_chat_session(session_id):
    """Удалить чат-сессию"""
    with session_scope() as db_session:
        try:
            chat_session = db_session.query(ChatSession).filter_by(session_id=session_id, user_id=current_user.id).first()
            if not chat_session:
                return jsonify({'success': False, 'error': 'Сессия не найдена'}), 404

            # Удаляем сообщения и сессию (если нет ON DELETE CASCADE)
            db_session.query(ChatMessage).filter_by(session_id=chat_session.id).delete()
            db_session.delete(chat_session)
            db_session.commit()

            return jsonify({'success': True, 'message': 'Чат-сессия удалена успешно'})
        except Exception:
            db_session.rollback()
            logger.exception("Ошибка при удалении сессии")
            return jsonify({'success': False, 'error': 'Internal server error'}), 500

@chat_bp.route('/api/chat/ask', methods=['POST'])
@login_required
def ask_question_direct():
    """Задать вопрос напрямую (без сохранения в историю, восстановленная логика)"""
    data = request.get_json(silent=True) or {}
    question = data.get('question')
    use_rag = data.get('use_rag', True)
    temperature = data.get('temperature', 0.7)

    if not question:
        return jsonify({'success': False, 'error': 'Вопрос не может быть пустым'}), 400

    try:
        chat_service = current_app.chat_service
        response_data = chat_service.generate_response_with_rag(
            user_message=question,
            use_rag=use_rag,
            temperature=temperature
        )
        if response_data.get('error'):
            return jsonify({'success': False, 'error': response_data['error']}), 500

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
    except Exception:
        logger.exception("Ошибка при прямом запросе")
        return jsonify({'success': False, 'error': 'Internal server error'}), 500


@chat_bp.route('/api/chat/unread-count', methods=['GET'])
@login_required
def get_unread_messages_count():
    """Получить количество непрочитанных сообщений пользователя"""
    with session_scope() as db_session:
        try:
            # Считаем количество непрочитанных сообщений по session_id (агрегатный запрос)
            counts = db_session.query(
                ChatMessage.session_id,
                func.count(ChatMessage.id).label('unread_count'),
                func.max(ChatMessage.created_at).label('last_message_time')
            ).join(ChatSession, ChatMessage.session_id == ChatSession.id).filter(
                ChatSession.user_id == current_user.id,
                ChatMessage.role == 'assistant',
                ChatMessage.is_read == False
            ).group_by(ChatMessage.session_id).all()

            total_unread = sum(c.unread_count for c in counts)
            sessions_with_unread = []

            # Получим mapping от session.id -> session.session_id и task_id и title
            session_ids = [c.session_id for c in counts]
            sessions = db_session.query(ChatSession).filter(ChatSession.id.in_(session_ids)).all()
            sessions_map = {s.id: s for s in sessions}

            # Соберём task ids и загрузим задачи
            task_ids = [s.task_id for s in sessions if s.task_id]
            tasks_map = get_task_info_map(db_session, task_ids)

            for c in counts:
                s = sessions_map.get(c.session_id)
                task_info = tasks_map.get(s.task_id) if s and s.task_id else None
                sessions_with_unread.append({
                    'session_id': s.session_id if s else None,
                    'title': s.title or f"Чат #{s.id}" if s else None,
                    'task': task_info,
                    'unread_count': c.unread_count,
                    'last_message_time': c.last_message_time.isoformat() if c.last_message_time else None
                })

            return jsonify({
                'success': True,
                'total_unread': total_unread,
                'sessions_with_unread': sessions_with_unread,
                'has_unread': total_unread > 0
            })
        except Exception:
            logger.exception("Ошибка при получении непрочитанных сообщений")
            return jsonify({'success': False, 'error': 'Internal server error'}), 500


@chat_bp.route('/api/chat/mark-all-as-read', methods=['POST'])
@login_required
def mark_all_as_read():
    """Отметить все сообщения пользователя как прочитанные"""
    with session_scope() as db_session:
        try:
            # Массово обновляем все assistant messages для сессий пользователя
            subq = db_session.query(ChatSession.id).filter(ChatSession.user_id == current_user.id).subquery()
            update_q = db_session.query(ChatMessage).filter(
                ChatMessage.session_id.in_(subq),
                ChatMessage.role == 'assistant',
                ChatMessage.is_read == False
            )
            total_marked = update_q.update({'is_read': True}, synchronize_session=False)
            db_session.commit()

            return jsonify({
                'success': True,
                'message': f'Отмечено {total_marked} сообщений как прочитанные',
                'marked_count': total_marked
            })
        except Exception:
            db_session.rollback()
            logger.exception("Ошибка при отметке всех сообщений как прочитанных")
            return jsonify({'success': False, 'error': 'Internal server error'}), 500


@chat_bp.route('/api/chat/session/by-id/<string:session_id>', methods=['GET'])
@login_required
def get_chat_session_by_id(session_id):
    """Получить информацию о чат-сессии по session_id"""
    with session_scope() as db_session:
        try:
            chat_session = db_session.query(ChatSession).filter_by(session_id=session_id, user_id=current_user.id).first()
            if not chat_session:
                return jsonify({'success': False, 'error': 'Сессия не найдена'}), 404

            task_info = None
            if chat_session.task_id:
                task = db_session.query(Task).get(chat_session.task_id)
                if task:
                    task_info = {'id': task.id, 'title': task.title}

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
        except Exception:
            logger.exception("Ошибка при получении сессии")
            return jsonify({'success': False, 'error': 'Internal server error'}), 500
@chat_bp.route('/api/chat/stream/abort', methods=['POST'])
@login_required
def abort_stream_generation():
    """
    Отменить (прервать) фоновой процесс генерации по assistant_message_id.
    Тело: { session_id, assistant_message_id (опционально) }
    Если assistant_message_id не передан — пытаемся найти самую свежую активную задачу для session_id.
    """
    data = request.get_json(silent=True) or {}
    session_id = data.get('session_id')
    assistant_id = data.get('assistant_message_id') or data.get('message_id')

    if not session_id:
        return jsonify({'success': False, 'error': 'Не указан session_id'}), 400

    with session_scope() as db_sess:
        chat_session = db_sess.query(ChatSession).filter_by(session_id=session_id, user_id=current_user.id).first()
        if not chat_session:
            return jsonify({'success': False, 'error': 'Сессия не найдена'}), 404

        target_mid = None
        with _generation_tasks_lock:
            if assistant_id:
                try:
                    target_mid = int(assistant_id)
                except Exception:
                    return jsonify({'success': False, 'error': 'Неверный assistant_message_id'}), 400
                task = _generation_tasks.get(target_mid)
                # ensure the task belongs to this chat_session
                if not task or task.get('chat_session_id') != chat_session.id:
                    return jsonify({'success': False, 'error': 'Задача не найдена или не принадлежит сессии'}), 404
            else:
                # найдем последнюю активную задачу для этой сессии
                candidates = [(mid, t) for mid, t in _generation_tasks.items() if t.get('chat_session_id') == chat_session.id and not t.get('done', {}).get('done', False)]
                if not candidates:
                    return jsonify({'success': False, 'error': 'Активных задач не найдено'}), 404
                # выберем последнюю по started_at
                candidates.sort(key=lambda x: x[1].get('started_at') or datetime.min, reverse=True)
                target_mid, task = candidates[0]

            # пометим cancelled
            task['cancelled'] = True
            # попытаемся положить сигнал done в очередь, чтобы подписчики получили final
            try:
                q = task.get('queue')
                last_seq = int(task.get('last_seq', 0))
                if q:
                    try:
                        q.put_nowait({'done': True, 'final_seq': last_seq, 'cancelled': True})
                    except queue.Full:
                        try:
                            q.put({'done': True, 'final_seq': last_seq, 'cancelled': True}, timeout=1.0)
                        except Exception:
                            pass
            except Exception:
                logger.exception("Ошибка при попытке поместить done-сообщение в очередь при отмене")

    return jsonify({'success': True, 'message': 'Генерация помечена как прерванная', 'assistant_message_id': int(target_mid)})


@chat_bp.route('/api/chat/get-task-id/<string:session_id>', methods=['GET'])
@login_required
def get_task_id_by_session(session_id):
    """Получить task_id по session_id"""
    with session_scope() as db_session:
        try:
            chat_session = db_session.query(ChatSession).filter_by(session_id=session_id, user_id=current_user.id).first()
            if not chat_session:
                return jsonify({'success': False, 'error': 'Сессия не найдена'}), 404

            return jsonify({
                'success': True,
                'session_id': session_id,
                'task_id': chat_session.task_id,
                'has_task': chat_session.task_id is not None
            })
        except Exception:
            logger.exception("Ошибка при получении task_id")
            return jsonify({'success': False, 'error': 'Internal server error'}), 500
