import schedule
import time
import logging
from datetime import datetime, timezone
from threading import Thread

logger = logging.getLogger(__name__)


class NotificationScheduler:
    def __init__(self, app):
        """
        Инициализация планировщика уведомлений

        Args:
            app: Flask приложение
        """
        self.app = app
        self.running = False
        self.scheduler_thread = None

    def job_process_notifications(self):
        """Задача по обработке уведомлений"""
        with self.app.app_context():
            try:
                current_time = datetime.now(timezone.utc)
                logger.info(f"Запуск обработки уведомлений в {current_time.strftime('%H:%M:%S UTC')}")

                if hasattr(self.app, 'notification_system'):
                    self.app.notification_system.process_notifications()

                    # Логируем статистику по задачам
                    from data.db_session import create_session
                    from data.tasks import Task

                    session = create_session()
                    try:
                        total_tasks = session.query(Task).filter(Task.completed == False).count()
                        overdue_tasks = session.query(Task).filter(
                            Task.completed == False,
                            Task.due_date < datetime.utcnow()
                        ).count()

                        logger.info(f"Статистика задач: всего активных - {total_tasks}, просроченных - {overdue_tasks}")
                    except Exception as e:
                        logger.error(f"Ошибка при получении статистики задач: {e}")
                    finally:
                        session.close()
                else:
                    logger.warning("NotificationSystem не инициализирован")

            except Exception as e:
                logger.error(f"Ошибка в задаче обработки уведомлений: {e}")

    def setup_schedule(self):
        """Настройка расписания задач"""
        try:
            # Очистка предыдущих задач
            schedule.clear()

            # Утренняя проверка в 9:00 (09:00)
            schedule.every().day.at("09:00").do(self.job_process_notifications).tag('daily', 'morning')
            logger.info("Запланирована утренняя проверка уведомлений в 09:00")

            # Вечерняя проверка в 17:00 (17:00)
            schedule.every().day.at("17:00").do(self.job_process_notifications).tag('daily', 'evening')
            logger.info("Запланирована вечерняя проверка уведомлений в 17:00")

            # Для тестирования: запуск каждые 10 минут (закомментируйте в продакшене)
            # schedule.every(10).minutes.do(self.job_process_notifications).tag('test', 'frequent')
            # logger.info("Запланирована тестовая проверка каждые 10 минут")

            # Еженедельный отчет в понедельник в 10:00
            schedule.every().monday.at("10:00").do(self.job_weekly_report).tag('weekly', 'report')
            logger.info("Запланирован еженедельный отчет в понедельник в 10:00")

        except Exception as e:
            logger.error(f"Ошибка при настройке расписания: {e}")
            raise

    def job_weekly_report(self):
        """Еженедельный отчет по задачам"""
        with self.app.app_context():
            try:
                logger.info("Генерация еженедельного отчета...")

                from data.db_session import create_session
                from data.tasks import Task
                from data.users import User

                session = create_session()
                try:
                    # Статистика по задачам
                    total_tasks = session.query(Task).count()
                    completed_tasks = session.query(Task).filter(Task.completed == True).count()
                    active_tasks = session.query(Task).filter(Task.completed == False).count()
                    overdue_tasks = session.query(Task).filter(
                        Task.completed == False,
                        Task.due_date < datetime.utcnow()
                    ).count()

                    # Процент выполнения
                    completion_rate = (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0

                    # Задачи с высоким приоритетом (ближайшие дедлайны)
                    high_priority_tasks = session.query(Task).filter(
                        Task.completed == False,
                        Task.due_date >= datetime.utcnow(),
                        Task.due_date <= datetime.utcnow() + timedelta(days=3)
                    ).all()

                    # Формируем список задач высокого приоритета
                    high_priority_list = []
                    for task in high_priority_tasks:
                        days_left = (task.due_date - datetime.utcnow()).days
                        high_priority_list.append(f"\n- {task.title} (ID: {task.id}), дедлайн через {days_left} дней")

                    high_priority_str = "".join(
                        high_priority_list) if high_priority_list else "Нет задач с высоким приоритетом"

                    # Генерация отчета с использованием конфигурационного промпта
                    report = Config.WEEKLY_REPORT_PROMPTS['TEMPLATE'].format(
                        report_date=datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M UTC'),
                        total_tasks=total_tasks,
                        completed_tasks=completed_tasks,
                        active_tasks=active_tasks,
                        overdue_tasks=overdue_tasks,
                        completion_rate=round(completion_rate, 1),
                        high_priority_tasks=high_priority_str
                    )

                    logger.info(report)

                except Exception as e:
                    logger.error(f"Ошибка при генерации отчета: {e}")
                finally:
                    session.close()

            except Exception as e:
                logger.error(f"Ошибка в задаче еженедельного отчета: {e}")

    def run_scheduler(self):
        """Запуск планировщика в бесконечном цикле"""
        self.running = True

        logger.info("Планировщик уведомлений запущен")

        while self.running:
            try:
                schedule.run_pending()
                time.sleep(60)  # Проверка каждую минуту

                # Логирование активности каждые 30 минут
                current_minute = datetime.now().minute
                if current_minute % 30 == 0:
                    logger.debug(f"Планировщик активен, следующие задачи: {schedule.get_jobs()}")

            except Exception as e:
                logger.error(f"Ошибка в планировщике: {e}")
                time.sleep(300)  # Пауза 5 минут при ошибке

    def start(self):
        """Запуск планировщика в отдельном потоке"""
        self.setup_schedule()

        # Запуск немедленной проверки при старте (опционально)
        self.job_process_notifications()

        # Запуск планировщика в отдельном потоке
        self.scheduler_thread = Thread(target=self.run_scheduler, daemon=True, name="NotificationScheduler")
        self.scheduler_thread.start()

        logger.info("Планировщик уведомлений запущен в отдельном потоке")

        return self.scheduler_thread

    def stop(self):
        """Остановка планировщика"""
        self.running = False
        schedule.clear()

        if self.scheduler_thread and self.scheduler_thread.is_alive():
            self.scheduler_thread.join(timeout=5)

        logger.info("Планировщик уведомлений остановлен")

    def get_schedule_info(self):
        """Получение информации о расписании"""
        jobs = schedule.get_jobs()

        info = {
            "running": self.running,
            "jobs": []
        }

        for job in jobs:
            job_info = {
                "tag": str(job.tags),
                "next_run": str(job.next_run) if job.next_run else None,
                "last_run": str(job.last_run) if job.last_run else None
            }
            info["jobs"].append(job_info)

        return info


def setup_scheduler(app):
    """
    Настройка и запуск планировщика уведомлений

    Args:
        app: Flask приложение

    Returns:
        Экземпляр NotificationScheduler
    """
    scheduler = NotificationScheduler(app)
    scheduler.start()

    # Добавляем scheduler в app context
    app.scheduler = scheduler

    return scheduler