# tasks.py - fix the user relationship
from datetime import timezone, datetime, timedelta, UTC
from typing import Optional
from sqlalchemy.orm import relationship
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from data.db_session import SqlAlchemyBase


class Task(SqlAlchemyBase):
    __tablename__ = 'tasks'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    due_date = Column(DateTime, nullable=False)
    completed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC)
    )

    # Notification tracking
    user = relationship('User', back_populates='tasks')  # FIXED: Changed from 'chat_sessions' to 'tasks'
    notification_sent_level = Column(Integer, default=0)
    last_notification_sent = Column(DateTime)

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'title': self.title,
            'description': self.description,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'completed': self.completed,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'notification_sent_level': self.notification_sent_level,
            'last_notification_sent': self.last_notification_sent.isoformat() if self.last_notification_sent else None
        }

    def check_notification_status(self) -> Optional[int]:
        now = datetime.now(timezone.utc)

        if self.completed or not self.due_date:
            return None

        # Ensure both datetimes are timezone-aware for comparison
        # If due_date is naive (has no timezone), assume UTC
        due_date = self.due_date
        if due_date.tzinfo is None:
            due_date = due_date.replace(tzinfo=timezone.utc)
        time_diff = due_date - now

        # Level 1: 3 days before due date
        if timedelta(seconds=0) <= time_diff <= timedelta(
                days=3) and self.notification_sent_level < 1:
            return 1

        # Level 2: 1 day before due date
        if timedelta(seconds=0) <= time_diff <= timedelta(
                days=1) and self.notification_sent_level < 2:
            return 2

        # Level 3: Due date has passed by 2 days
        # Calculate how many days overdue
        if now > due_date:
            days_overdue = (now - due_date).days
            if days_overdue >= 2 and self.notification_sent_level < 3:
                return 3

        return None

    def mark_notification_sent(self, level: int):
        current_time = datetime.now(UTC)
        current_level = self.notification_sent_level if self.notification_sent_level is not None else 0
        self.notification_sent_level = max(current_level, level)
        self.last_notification_sent = current_time