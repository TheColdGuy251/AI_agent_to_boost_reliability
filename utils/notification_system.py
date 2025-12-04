import logging
from datetime import datetime, timedelta, UTC
from typing import Dict, List, Optional
from sqlalchemy.orm import Session

from config import Config
from utils.local_model import LlamaModel
from data.tasks import Task
from data.users import User
from data.db_session import create_session

logger = logging.getLogger(__name__)


class NotificationSystem:
    def __init__(self, model: LlamaModel):
        """
        Инициализация системы уведомлений

        Args:
            model: Модель для генерации уведомлений
        """
        self.model = model
        self.system_prompt = Config.SYSTEM_PROMPT

    def get_notification_prompt(self, task: Task, user: User, level: int) -> str:
        """
        Генерация промпта для уведомления в зависимости от уровня

        Args:
            task: Объект задачи
            user: Объект пользователя
            level: Уровень уведомления (1-3)

        Returns:
            Промпт для модели
        """
        # Формируем информацию о задаче
        task_info = f"""
        Информация о задаче:
        - Название: {task.title}
        - Описание: {task.description or 'Нет описания'}
        - Дедлайн: {task.due_date.strftime('%d.%m.%Y %H:%M')}
        - Исполнитель: {user.username} ({user.email})
        - Дата создания: {task.created_at.strftime('%d.%m.%Y %H:%M')}
        """

        # Получаем конфигурацию уровня уведомления
        level_config = Config.NOTIFICATION_LEVELS.get(level, {})
        prompt_config = Config.NOTIFICATION_PROMPTS.get(
            level_config.get('prompt_key', f'LEVEL_{level}'),
            Config.NOTIFICATION_PROMPTS['LEVEL_1']
        )

        # Формируем контекст роли
        role_context = f"Ты - {prompt_config['role']}. Твоя задача - {prompt_config['task']}."

        # Формируем инструкции
        instructions = "\n".join([f"{i + 1}. {instruction}"
                                  for i, instruction in enumerate(prompt_config['instructions'])])

        # Получаем параметры времени
        days_before = level_config.get('days_before', 3)
        days_after = level_config.get('days_after', 2)

        # Формируем полный промпт
        base_template = prompt_config['template']

        if level in [1, 2]:
            prompt = base_template.format(
                role_context=role_context,
                task_info=task_info,
                days_before=days_before,
                instructions=instructions
            )
        else:  # level == 3
            prompt = base_template.format(
                role_context=role_context,
                task_info=task_info,
                days_after=days_after,
                instructions=instructions
            )

        # Добавляем системный промпт в начало
        full_prompt = f"{self.system_prompt}\n\n{prompt}"

        return full_prompt.strip()

    def generate_notification(self, prompt: str) -> str:
        """
        Генерация текста уведомления с помощью модели

        Args:
            prompt: Промпт для модели

        Returns:
            Сгенерированный текст уведомления
        """
        try:
            messages = [
                {"role": "user", "content": prompt}
            ]

            response = self.model.chat_generate(
                messages=messages,
                system_prompt=self.system_prompt,
                temperature=0.7
            )

            if response.get('success', False):
                return response['response']
            else:
                logger.error(f"Ошибка генерации уведомления: {response.get('error')}")
                return "Ошибка генерации уведомления"

        except Exception as e:
            logger.error(f"Ошибка при генерации уведомления: {e}")
            return f"Ошибка: {str(e)}"

    def check_task_status(self, task: Task, current_time: datetime = None) -> Optional[int]:
        """
        Проверка статуса задачи и определение необходимости уведомления
        Использует логику из конфигурации

        Args:
            task: Объект задачи
            current_time: Время для проверки (по умолчанию текущее)

        Returns:
            Уровень уведомления (1-3) или None
        """
        if task.completed or not task.due_date:
            return None

        if current_time is None:
            current_time = datetime.now(UTC)

        # Убеждаемся, что даты в одном часовом поясе
        due_date = task.due_date
        if due_date.tzinfo is None:
            due_date = due_date.replace(tzinfo=UTC)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=UTC)

        # Рассчитываем разницу в днях
        time_diff = due_date - current_time
        days_diff = time_diff.days

        # Получаем конфигурацию уведомлений
        level1_config = Config.NOTIFICATION_LEVELS.get(1, {})
        level2_config = Config.NOTIFICATION_LEVELS.get(2, {})
        level3_config = Config.NOTIFICATION_LEVELS.get(3, {})

        # Проверяем условия для каждого уровня
        if level1_config:
            days_before = level1_config.get('days_before', 3)
            # За 3 дня до дедлайна (0 < days_diff <= 3)
            if 0 < days_diff <= days_before and task.notification_sent_level < 1:
                return 1

        if level2_config:
            days_before = level2_config.get('days_before', 1)
            # За 1 день до дедлайна
            if 0 < days_diff <= days_before and task.notification_sent_level < 2:
                return 2

        if level3_config:
            days_after = level3_config.get('days_after', 2)
            # Просрочено на 2 дня
            if days_diff < 0 and abs(days_diff) >= days_after and task.notification_sent_level < 3:
                return 3

        return None

    def process_notifications(self):
        """
        Основной метод обработки уведомлений
        Проверяет все задачи и отправляет уведомления при необходимости
        """
        logger.info(f"Начало обработки уведомлений в {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')}...")

        session: Session = create_session()
        try:
            # Получаем все незавершенные задачи
            tasks = session.query(Task).filter(
                Task.completed == False,
                Task.due_date.isnot(None)
            ).all()

            notifications_sent = 0
            current_time = datetime.now(UTC)

            for task in tasks:
                try:
                    # Проверяем, нужно ли отправлять уведомление
                    notification_level = self.check_task_status(task, current_time)

                    if notification_level:
                        # Получаем пользователя
                        user = session.query(User).filter(User.id == task.user_id).first()
                        if not user:
                            logger.error(f"Пользователь {task.user_id} не найден для задачи {task.id}")
                            continue

                        # Генерируем промпт
                        prompt = self.get_notification_prompt(task, user, notification_level)

                        # Генерируем уведомление
                        notification_text = self.generate_notification(prompt)

                        # Логируем уведомление
                        logger.info(f"""
                        {'=' * 50}
                        УВЕДОМЛЕНИЕ ОТПРАВЛЕНО
                        Уровень: {notification_level}
                        Задача: {task.title} (ID: {task.id})
                        Пользователь: {user.username} ({user.email})
                        Время проверки: {current_time.strftime('%d.%m.%Y %H:%M:%S')}
                        Срок задачи: {task.due_date.strftime('%d.%m.%Y %H:%M:%S')}
                        {'-' * 50}
                        {notification_text}
                        {'=' * 50}
                        """)

                        # Обновляем статус уведомления в задаче
                        task.notification_sent_level = max(task.notification_sent_level or 0, notification_level)
                        task.last_notification_sent = datetime.now(UTC)

                        notifications_sent += 1

                except Exception as e:
                    logger.error(f"Ошибка при обработке задачи {task.id}: {e}")
                    continue

            session.commit()
            logger.info(f"Обработка уведомлений завершена. Отправлено: {notifications_sent} уведомлений")

        except Exception as e:
            logger.error(f"Ошибка при обработке уведомлений: {e}")
            session.rollback()
        finally:
            session.close()

    def send_test_notification(self, task_id: int, level: int = 1) -> Dict:
        """
        Метод для тестирования уведомлений

        Args:
            task_id: ID задачи
            level: Уровень уведомления (1-3)

        Returns:
            Результат теста
        """
        session: Session = create_session()
        try:
            task = session.query(Task).filter(Task.id == task_id).first()
            if not task:
                return {"success": False, "error": "Задача не найдена"}

            user = session.query(User).filter(User.id == task.user_id).first()
            if not user:
                return {"success": False, "error": "Пользователь не найден"}

            # Генерируем промпт
            prompt = self.get_notification_prompt(task, user, level)

            # Генерируем уведомление
            notification_text = self.generate_notification(prompt)

            return {
                "success": True,
                "task": task.title,
                "user": user.username,
                "level": level,
                "prompt": prompt,
                "notification": notification_text
            }

        except Exception as e:
            logger.error(f"Ошибка при тестировании уведомления: {e}")
            return {"success": False, "error": str(e)}
        finally:
            session.close()