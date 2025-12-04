# data/chat_sessions.py
from datetime import datetime, UTC
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from data.db_session import SqlAlchemyBase


class ChatSession(SqlAlchemyBase):
    __tablename__ = 'chat_sessions'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    task_id = Column(Integer, ForeignKey('tasks.id'), nullable=True)
    session_id = Column(String(36), unique=True, nullable=False)
    title = Column(String(200), nullable=True)  # Название сессии
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    last_activity = Column(DateTime, default=lambda: datetime.now(UTC))
    # Renamed from 'metadata' to avoid SQLAlchemy conflict
    session_metadata = Column(Text, nullable=True)  # Дополнительные метаданные в JSON формате
    # Relationships
    messages = relationship('ChatMessage', backref='chat_session', lazy='dynamic',
                            cascade='all, delete-orphan', order_by='ChatMessage.created_at')
    # Удалить строку с backref и заменить на:
    user = relationship('User', back_populates='chat_sessions')

    # Связь с задачей
    task = relationship('Task', backref='chat_sessions')

    def __init__(self, **kwargs):
        # Handle old 'metadata' key for backward compatibility
        if 'metadata' in kwargs:
            kwargs['session_metadata'] = kwargs.pop('metadata')
        for key, value in kwargs.items():
            setattr(self, key, value)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'task_id': self.task_id,
            'session_id': self.session_id,
            'title': self.title,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_activity': self.last_activity.isoformat() if self.last_activity else None,
            'message_count': self.messages.count() if self.messages else 0,
            'metadata': self.session_metadata  # Map to original name in output
        }