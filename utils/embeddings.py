# utils/embeddings.py
from typing import List, Optional
import logging
from utils.local_model import LlamaModel

logger = logging.getLogger(__name__)


class CustomEmbeddingFunction:
    """Кастомная функция эмбеддингов для ChromaDB"""

    def __init__(self, model: Optional[LlamaModel] = None):
        """
        Инициализация функции эмбеддингов

        Args:
            model: Экземпляр LlamaModel
        """
        self.model = model or LlamaModel(
            model_name="llama3.2:3b",
            embedding_model="nomic-embed-text"
        )
        logger.info(f"EmbeddingFunction инициализирован с моделью: {self.model.embedding_model}")

    def __call__(self, texts: List[str]) -> List[List[float]]:
        """
        Вычисление эмбеддингов для списка текстов

        Args:
            texts: Список текстов

        Returns:
            Список векторов эмбеддингов
        """
        try:
            embeddings = []
            for text in texts:
                if not text or not text.strip():
                    # Возвращаем нулевой вектор для пустого текста
                    embeddings.append([0.0] * 768)
                    continue

                embedding = self.model.get_embeddings(text)
                if embedding:
                    embeddings.append(embedding)
                else:
                    # Возвращаем нулевой вектор в случае ошибки
                    logger.warning(f"Не удалось получить эмбеддинг для текста: {text[:50]}...")
                    embeddings.append([0.0] * 768)

            logger.debug(f"Вычислено {len(embeddings)} эмбеддингов")
            return embeddings

        except Exception as e:
            logger.error(f"Ошибка при вычислении эмбеддингов: {e}")
            # Возвращаем нулевые векторы в случае ошибки
            return [[0.0] * 768 for _ in texts]