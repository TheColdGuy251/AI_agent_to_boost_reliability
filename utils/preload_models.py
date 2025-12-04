import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.local_model import LlamaModel
from config import Config
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def preload_models():
    """Предварительная загрузка моделей"""
    logger.info("Предварительная загрузка моделей...")

    try:
        model = LlamaModel(
            model_name=Config.MODEL_NAME,
            embedding_model=Config.EMBEDDING_MODEL
        )

        logger.info("Модели успешно загружены")
        logger.info("Проверка работоспособности...")

        status = model.check_model_health()
        logger.info(f"Статус моделей: {status}")

        return True

    except Exception as e:
        logger.error(f"Ошибка при загрузке моделей: {e}")
        return False


if __name__ == "__main__":
    success = preload_models()
    sys.exit(0 if success else 1)