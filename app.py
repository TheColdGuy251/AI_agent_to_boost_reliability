from flask import Flask, jsonify, render_template
from flask_login import LoginManager, current_user
from flask_migrate import Migrate
import os
import logging.config
from threading import Lock
from pathlib import Path

from torch.distributed.elastic.multiprocessing.redirects import redirect

from config import Config
from data.db_session import global_init, get_engine
from routes.auth import auth_bp, setup_user_loader
from routes.tasks import tasks_bp
from routes.chat import chat_bp
from utils.local_model import LlamaModel
from utils.error_handlers import register_error_handlers
from utils.notification_system import NotificationSystem
from utils.chat_service import ChatService
from utils.document_processor import DocumentProcessor

# Настройка логгера
os.makedirs(Config.BASE_DIR / 'logs', exist_ok=True)
logging.config.dictConfig(Config.LOGGING_CONFIG)
logger = logging.getLogger(__name__)

# Глобальные объекты с защитой от повторной инициализации
_models_initialized = False
_vector_db_initialized = False
_init_lock = Lock()
_llama_model = None
_document_processor = None
_chat_service = None
_notification_system = None

app = Flask(__name__)

app.config.from_object(Config)

# Создаем директории для документов и векторной базы
os.makedirs(app.config['DOCS_DIR'], exist_ok=True)
os.makedirs(app.config['CHROMA_DIR'], exist_ok=True)

# Инициализация расширений
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'  # Измените 'login_page' на 'auth.login'
login_manager.login_message = 'Пожалуйста, войдите для доступа к этой странице'
login_manager.login_message_category = 'info'

setup_user_loader(login_manager)

app.register_blueprint(auth_bp)
app.register_blueprint(tasks_bp)
app.register_blueprint(chat_bp)
global_init("db/database.db")
engine = get_engine()
migrate = Migrate(app, engine)

register_error_handlers(app)

def initialize_models_once():
    """Инициализация моделей только один раз"""
    global _models_initialized, _llama_model, _document_processor, _chat_service, _notification_system

    with _init_lock:
        if _models_initialized:
            logger.info("Модели уже инициализированы, пропускаем повторную инициализацию")
            return

        try:
            logger.info("Начало инициализации моделей...")

            # 1. Инициализируем модель
            _llama_model = LlamaModel(
                model_name=Config.MODEL_NAME,
                embedding_model=Config.EMBEDDING_MODEL
            )
            logger.info(
                f"Модель инициализирована: {Config.MODEL_NAME} (генерация), {Config.EMBEDDING_MODEL} (эмбеддинги)")

            # 2. Проверяем здоровье моделей
            model_status = _llama_model.check_model_health()
            logger.info(f"Статус моделей: {model_status}")

            # 3. Инициализируем DocumentProcessor
            _document_processor = DocumentProcessor(model=_llama_model)
            logger.info("DocumentProcessor инициализирован")

            # 4. Инициализируем ChatService
            _chat_service = ChatService(
                model=_llama_model,
                document_processor=_document_processor
            )
            logger.info("ChatService инициализирован")

            # 5. Инициализируем NotificationSystem
            _notification_system = NotificationSystem(model=_llama_model)
            logger.info("NotificationSystem инициализирован")

            # Сохраняем ссылки в app context для доступа из маршрутов
            app.llama_model = _llama_model
            app.document_processor = _document_processor
            app.chat_service = _chat_service
            app.notification_system = _notification_system

            _models_initialized = True
            logger.info("Модели успешно инициализированы")

        except Exception as e:
            logger.error(f"Ошибка при инициализации моделей: {e}")
            raise


def initialize_vector_db_once():
    """Инициализация векторной базы один раз"""
    global _vector_db_initialized

    if _vector_db_initialized:
        logger.info("Векторная база уже инициализирована, пропускаем")
        return

    try:
        logger.info("Начало инициализации векторной базы...")

        # Проверяем, есть ли уже коллекция с данными
        collection_info = _document_processor.get_collection_info()

        if collection_info.get('total_chunks', 0) > 0:
            logger.info(
                f"Векторная база уже содержит {collection_info['total_chunks']} чанков. Проверяем обновления...")

            # Получаем список файлов в папке docs
            existing_files = set()
            if _document_processor.collection.count() > 0:
                # Получаем метаданные о существующих файлах
                all_docs = _document_processor.collection.get(limit=10000)
                if all_docs and 'metadatas' in all_docs:
                    for metadata in all_docs['metadatas']:
                        filepath = metadata.get('file_path', '')
                        if filepath:
                            existing_files.add(Path(filepath).name)

            # Находим новые файлы
            docs_dir = Path(Config.DOCS_DIR)
            new_files = []
            for file_path in docs_dir.glob("*.docx"):
                if file_path.name.startswith('~$'):
                    continue
                if file_path.name not in existing_files:
                    new_files.append(file_path)

            if new_files:
                logger.info(f"Найдено {len(new_files)} новых файлов для обработки")
                processed_docs = []
                for file_path in new_files:
                    doc_info = _document_processor.process_single_document(file_path)
                    if doc_info:
                        processed_docs.append(doc_info)

                if processed_docs:
                    _document_processor.add_documents_to_vector_db(processed_docs)
                    logger.info(f"Добавлено {len(processed_docs)} новых документов в векторную базу")
            else:
                logger.info("Новых файлов не найдено, пропускаем обработку")
        else:
            # Векторная база пуста, обрабатываем все документы
            logger.info("Векторная база пуста, обрабатываем все документы...")
            processed_docs = _document_processor.process_all_documents()

            if processed_docs:
                _document_processor.add_documents_to_vector_db(processed_docs)

                collection_info = _document_processor.get_collection_info()
                logger.info(f"Векторная база инициализирована: {collection_info}")
            else:
                logger.info("Векторная база пуста, добавьте документы в папку docs")

        _vector_db_initialized = True
        logger.info("Инициализация векторной базы завершена")

    except Exception as e:
        logger.error(f"Ошибка при инициализации векторной базы: {e}")
        raise


@app.before_request
def ensure_initialized():
    """Убеждаемся, что модели инициализированы перед обработкой запроса"""
    if not _models_initialized:
        initialize_models_once()
        initialize_vector_db_once()

@app.route('/')
def index():
    """Главная страница"""
    if current_user.is_authenticated:
        user_initials = f"{current_user.surname[0]}{current_user.name[0]}"
        user_name = f"{current_user.name} {current_user.surname[0]}."
        user_full_name = f"{current_user.surname} {current_user.name} {current_user.patronymic or ''}".strip()
        return render_template('tasks.html',
                               user_initials=user_initials,
                               user_name=user_name,
                               user_full_name=user_full_name,
                               user_position=current_user.position)
    return redirect("/auth/login")

if __name__ == '__main__':
    initialize_models_once()
    initialize_vector_db_once()
    from utils.scheduler import setup_scheduler

    scheduler = setup_scheduler(app)

    # Добавляем эндпоинт для проверки статуса планировщика
    @app.route('/api/scheduler/status', methods=['GET'])
    def get_scheduler_status():
        """Получение статуса планировщика"""
        if hasattr(app, 'scheduler'):
            return jsonify(app.scheduler.get_schedule_info())
        return jsonify({"error": "Scheduler not initialized"}), 500


    @app.route('/api/scheduler/run-now', methods=['POST'])
    def run_scheduler_now():
        """Немедленный запуск обработки уведомлений"""
        try:
            if hasattr(app, 'notification_system'):
                app.notification_system.process_notifications()
                return jsonify({"success": True, "message": "Уведомления обработаны"})
            else:
                return jsonify({"error": "NotificationSystem not initialized"}), 500
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    app.run(debug=True, use_reloader=False, port=5000)