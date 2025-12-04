from datetime import datetime, UTC
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import relationship
from .db_session import SqlAlchemyBase
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

class User(SqlAlchemyBase, UserMixin):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(80), unique=True, nullable=False)
    email = Column(String(120), unique=True, nullable=False)
    surname = Column(String(120), nullable=False)
    name = Column(String(120), nullable=False)
    patronymic = Column(String(120), nullable=True)
    position = Column(String(120), nullable=False)
    password_hash = Column(String(256), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    is_active = Column(Boolean, default=True)

    # Исправленные relationships
    tasks = relationship('Task', back_populates='user', lazy=True, cascade='all, delete-orphan')
    chat_sessions = relationship('ChatSession', back_populates='user', lazy=True, cascade='all, delete-orphan')


    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        """Преобразование в словарь"""
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'surname': self.surname,
            'name': self.name,
            'patronymic': self.patronymic,
            'position': self.position,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'is_active': self.is_active
        }

    # Для совместимости с flask-login
    def get_id(self):
        return str(self.id)