# __all_models.py
from data.users import User
from data.tasks import Task
from data.chat_sessions import ChatSession
from data.chat_message import ChatMessage

# Явно импортируем все модели для Alembic
__all__ = ['User', 'Task', 'ChatSession', 'ChatMessage']