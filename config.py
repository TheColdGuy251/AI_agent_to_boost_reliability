import os
from datetime import timedelta
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()


class Config:
    # Получаем корневую директорию проекта
    BASE_DIR = Path(__file__).parent
    SECRET_KEY = os.getenv('SECRET_KEY', 'your-secret-key-here')

    # Правильный путь к базе данных
    db_path = BASE_DIR / 'db' / 'database.db'
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{db_path}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Document processing settings
    DOCS_DIR = BASE_DIR / 'docs'
    CHROMA_DIR = BASE_DIR / 'chroma_db'

    MODEL_NAME = "dimweb/ilyagusev-saiga_llama3_8b:kto_v5_Q4_K"
    EMBEDDING_MODEL = "nomic-embed-text"

    # Chunking settings
    CHUNK_SIZE = 1000
    CHUNK_OVERLAP = 200

    # RAG settings
    RAG_N_RESULTS = 5
    RAG_SIMILARITY_THRESHOLD = 0.7
    NOTIFICATION_SCHEDULE = {
        'morning_check': '09:00',
        'evening_check': '17:00',
        'weekly_report_day': 'monday',
        'weekly_report_time': '10:00',
        'timezone': 'UTC'
    }

    LOGGING_CONFIG = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'standard': {
                'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
            },
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'formatter': 'standard',
                'level': 'INFO',
            },
            'file': {
                'class': 'logging.FileHandler',
                'filename': BASE_DIR / 'logs' / 'app.log',
                'formatter': 'standard',
                'level': 'DEBUG',
            },
        },
        'loggers': {
            '': {
                'handlers': ['console', 'file'],
                'level': 'INFO',
                'propagate': True
            },
        }
    }

    # =============== СИСТЕМНЫЕ ПРОМПТЫ ===============

    # Базовый системный промпт для всех моделей
    SYSTEM_PROMPT = """Ты — ассистент по управлению проектами и документами. 
    Ты помогаешь пользователям с задачами, документами, отслеживанием сроков и планированием.
    Всегда будь вежливым, профессиональным и конкретным в ответах. Используй только русский язык (исключениями могут быть только прямое наименование в документе)
    Если пользователь спрашивает о прогрессе или сроках, напомни ему о важности своевременного выполнения задач.

    Когда тебе предоставляют информацию из документов, используй её для формирования точных ответов.
    Если информации в документах недостаточно, честно скажи об этом."""

    # Промпты для уведомлений
    NOTIFICATION_PROMPTS = {
        'LEVEL_1': {
            'role': "ответственный ассистент по управлению проектами",
            'task': "напомнить сотруднику о приближающемся дедлайне",
            'instructions': [
                "Сгенерируйте вежливое напоминание сотруднику о приближающемся дедлайне",
                "Сообщение должно быть профессиональным и мотивирующим",
                "Формат: Напоминание о дедлайне"
            ],
            'template': """
{role_context}

{task_info}

Статус: До дедлайна осталось {days_before} дня
Задание: {instructions}
"""
        },
        'LEVEL_2': {
            'role': "ответственный ассистент по управлению проектами",
            'task': "напомнить сотруднику о срочном дедлайне",
            'instructions': [
                "Сгенерируйте срочное напоминание о том, что дедлайн близко",
                "Подчеркните важность оперативного завершения работы",
                "Формат: Срочное уведомление"
            ],
            'template': """
{role_context}

{task_info}

Статус: До дедлайна остался {days_before} день
Задание: {instructions}
"""
        },
        'LEVEL_3': {
            'role': "ассистент по управлению проектами",
            'task': "уведомить о просроченной задаче",
            'instructions': [
                "Сгенерируйте уведомление о просроченной задаче",
                "Запросите статус выполнения",
                "Сообщение должно быть официальным, но конструктивным",
                "Формат: Уведомление о просрочке"
            ],
            'template': """
{role_context}

{task_info}

Статус: Задача просрочена на {days_after} дня
Задание: {instructions}
"""
        }
    }

    # Промпты для RAG (Retrieval Augmented Generation)
    RAG_PROMPTS = {
        'SYSTEM_WITH_CONTEXT': """
{base_system_prompt}

Контекст из документов (используйте эту информацию для ответа):
{context}

Важные инструкции:
1. Отвечайте ТОЛЬКО на основе предоставленного контекста
2. Если в контексте нет информации для ответа, скажите "На основе предоставленных документов не могу ответить на этот вопрос"
3. Будьте точными и конкретными
4. Приводите факты из контекста
5. Сохраняйте профессиональный тон

Вопрос пользователя: {question}

Ответ (на основе документов):""",

        'SYSTEM_WITH_CONTEXT_REFERENCE': """
{base_system_prompt}

Контекст из документов (для справки):
{context}

Инструкции:
1. Используйте информацию из документов для ответа на вопрос
2. Будьте точны и конкретны
3. Если в документах нет нужной информации, скажите об этом
4. Сохраняйте профессиональный тон

Вопрос пользователя: {question}

Ответ (с учетом контекста документов):""",

        'SYSTEM_WITH_HISTORY': """
{base_system_prompt}

История диалога:
{history}

Текущий вопрос пользователя: {question}

Ответ (с учетом истории диалога):""",

        'SYSTEM_DIRECT': """
{base_system_prompt}

Вопрос пользователя: {question}

Ответ:"""
    }

    # Промпты для чат-сервиса
    CHAT_PROMPTS = {
        'WELCOME_MESSAGE': "Здравствуйте! Я ваш ИИ ассистент по задаче '{task_title}'. Чем могу помочь?",
        'TASK_SYSTEM_MESSAGE': "Задача: {task_title}\nСрок: {due_date}\nОписание: {description}",
        'GENERAL_WELCOME': "Здравствуйте! Я ваш ассистент по управлению проектами и документами. Чем могу помочь?",
        'TASK_CREATED': "Задача создана. Название: {task_title}\nСрок: {due_date}\nОписание: {description}"
    }

    # Промпты для еженедельных отчетов
    WEEKLY_REPORT_PROMPTS = {
        'TEMPLATE': """
ЕЖЕНЕДЕЛЬНЫЙ ОТЧЕТ ПО ЗАДАЧАМ
==============================
Дата генерации: {report_date}

ОБЩАЯ СТАТИСТИКА:
- Всего задач: {total_tasks}
- Выполнено: {completed_tasks}
- Активных: {active_tasks}
- Просрочено: {overdue_tasks}
- Процент выполнения: {completion_rate}%

ЗАДАЧИ ВЫСОКОГО ПРИОРИТЕТА (дедлайн в ближайшие 3 дня):
{high_priority_tasks}
"""
    }

    # Notification levels configuration
    NOTIFICATION_LEVELS = {
        1: {
            'days_before': 3,
            'prompt_key': 'LEVEL_1'
        },
        2: {
            'days_before': 1,
            'prompt_key': 'LEVEL_2'
        },
        3: {
            'days_after': 2,
            'prompt_key': 'LEVEL_3'
        }
    }