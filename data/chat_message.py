from datetime import datetime, UTC
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from data.db_session import SqlAlchemyBase


class ChatMessage(SqlAlchemyBase):
    __tablename__ = 'chat_messages'

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey('chat_sessions.id'), nullable=False)
    role = Column(String(20), nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.now(UTC))
    is_read = Column(Boolean, default=True)  # Новое поле

    # Для сообщений пользователя сразу помечаем как прочитанные
    # Для сообщений бота - по умолчанию False
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

        # Если это сообщение от бота, помечаем как непрочитанное
        if 'role' in kwargs and kwargs['role'] == 'assistant':
            self.is_read = False

    def to_dict(self):
        return {
            'id': self.id,
            'session_id': self.session_id,
            'role': self.role,
            'content': self.content,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'is_read': self.is_read  # Добавляем в API ответ
        }