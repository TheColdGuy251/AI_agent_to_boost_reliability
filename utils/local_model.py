import ollama
from typing import Optional, List, Dict, Any
import logging
import threading
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Глобальный кэш для проверенных моделей с TTL
_verified_models = {}
_model_cache_ttl = timedelta(hours=1)  # Кэшируем на 1 час
_model_lock = threading.Lock()


class LlamaModel:
    def __init__(self,
                 model_name: str = "dimweb/ilyagusev-saiga_llama3_8b:kto_v5_Q4_K",
                 embedding_model: str = "nomic-embed-text"):
        """
        Инициализация моделей через Ollama с кэшированием
        """
        self.model_name = model_name
        self.embedding_model = embedding_model
        self._models_verified = False

        # Проверяем кэш перед инициализацией
        current_time = datetime.now()
        cache_key = f"{model_name}_{embedding_model}"

        with _model_lock:
            if cache_key in _verified_models:
                cache_data = _verified_models[cache_key]
                if current_time - cache_data['timestamp'] < _model_cache_ttl:
                    logger.info(f"Используем кэшированные модели: {model_name}, {embedding_model}")
                    self._models_verified = True
                    return

        # Если кэша нет или он устарел, инициализируем
        self._setup_all_models()

        # Сохраняем в кэш
        with _model_lock:
            _verified_models[cache_key] = {
                'timestamp': current_time,
                'model_name': model_name,
                'embedding_model': embedding_model
            }

        logger.info(f"Модели инициализированы: {model_name} (генерация), {embedding_model} (эмбеддинги)")

    def _setup_all_models(self):
        """Проверка всех моделей за один раз"""
        if self._models_verified:
            return

        with _model_lock:
            try:
                # Получаем список всех доступных моделей за один запрос
                models_response = ollama.list()
                available_models = []

                for model in models_response.get('models', []):
                    model_name_in_list = model.get('name') or model.get('model')
                    if model_name_in_list:
                        available_models.append(model_name_in_list)

                logger.debug(f"Доступные модели: {available_models}")

                # Проверяем и загружаем модели если нужно
                for model_name, model_type in [
                    (self.model_name, "основная модель"),
                    (self.embedding_model, "модель для эмбеддингов")
                ]:
                    self._setup_single_model(model_name, model_type, available_models)

                self._models_verified = True

            except Exception as e:
                logger.error(f"Ошибка при инициализации моделей: {e}")
                raise

    def _setup_single_model(self, model_name: str, model_type: str, available_models: list):
        """
        Проверка и установка одной модели с использованием предварительно полученного списка
        """
        try:
            # Проверяем, установлена ли модель (учитываем возможные теги)
            model_exists = False
            for available_model in available_models:
                # Проверяем точное совпадение или совпадение без тега
                if (available_model == model_name or
                        available_model.startswith(f"{model_name}:")):
                    model_exists = True
                    break

            if not model_exists:
                logger.info(f"{model_type} {model_name} не найдена. Скачиваем...")
                ollama.pull(model_name, stream=False)  # Не потоковый для быстрого завершения
                logger.info(f"{model_type} {model_name} успешно скачана")
            else:
                logger.info(f"{model_type} {model_name} готова к использованию")

        except Exception as e:
            logger.error(f"Ошибка при инициализации {model_type} {model_name}: {e}")
            raise

    def simple_generate(self,
                        prompt: str,
                        max_tokens: int = 1000,
                        temperature: float = 0.7,
                        top_p: float = 0.9) -> str:
        """
        Простая генерация текста

        Args:
            prompt: Входной текст
            max_tokens: Максимальное количество токенов в ответе
            temperature: Температура генерации (0.0-1.0)
            top_p: Top-p sampling (0.0-1.0)

        Returns:
            Сгенерированный текст
        """
        try:
            response = ollama.generate(
                model=self.model_name,
                prompt=prompt,
                options={
                    "num_predict": max_tokens,
                    "temperature": temperature,
                    "top_p": top_p,
                }
            )
            return response['response']

        except Exception as e:
            logger.error(f"Ошибка генерации: {str(e)}")
            return f"Ошибка генерации: {str(e)}"

    def chat_generate(self,
                      messages: List[Dict[str, str]],
                      system_prompt: Optional[str] = None,
                      temperature: float = 0.7,
                      top_p: float = 0.9) -> Dict[str, Any]:
        """
        Генерация в формате чата

        Args:
            messages: Список сообщений в формате [{"role": "user", "content": "текст"}]
            system_prompt: Системный промпт (необязательно)
            temperature: Температура генерации (0.0-1.0)
            top_p: Top-p sampling (0.0-1.0)

        Returns:
            Ответ модели в формате dict
        """
        try:
            # Подготовка сообщений
            chat_messages = []

            if system_prompt:
                chat_messages.append({"role": "system", "content": system_prompt})

            chat_messages.extend(messages)

            # Отправка запроса
            response = ollama.chat(
                model=self.model_name,
                messages=chat_messages,
                options={
                    "temperature": temperature,
                    "top_p": top_p,
                }
            )

            return {
                "response": response['message']['content'],
                "model": self.model_name,
                "tokens_used": response.get('eval_count', 0),
                "success": True
            }

        except Exception as e:
            logger.error(f"Ошибка в chat_generate: {str(e)}")
            return {
                "error": str(e),
                "success": False,
                "model": self.model_name
            }

    def get_embeddings(self, text: str) -> List[float]:
        """
        Получение эмбеддингов для текста с использованием специализированной модели

        Args:
            text: Текст для векторизации

        Returns:
            Список эмбеддингов (вектор)
        """
        try:
            response = ollama.embeddings(
                model=self.embedding_model,
                prompt=text
            )
            return response['embedding']
        except Exception as e:
            logger.error(f"Ошибка получения эмбеддингов: {e}")
            return []

    def get_batch_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        Получение эмбеддингов для нескольких текстов

        Args:
            texts: Список текстов для векторизации

        Returns:
            Список эмбеддингов для каждого текста
        """
        embeddings = []
        for text in texts:
            embedding = self.get_embeddings(text)
            if embedding:
                embeddings.append(embedding)
        return embeddings

    def stream_chat(self,
                    messages: List[Dict[str, str]],
                    system_prompt: Optional[str] = None):
        """
        Потоковая генерация чата

        Args:
            messages: Список сообщений
            system_prompt: Системный промпт

        Yields:
            Части сгенерированного текста
        """
        try:
            chat_messages = []
            if system_prompt:
                chat_messages.append({"role": "system", "content": system_prompt})
            chat_messages.extend(messages)

            stream = ollama.chat(
                model=self.model_name,
                messages=chat_messages,
                stream=True
            )

            for chunk in stream:
                if 'message' in chunk and 'content' in chunk['message']:
                    yield chunk['message']['content']

        except Exception as e:
            logger.error(f"Ошибка в потоковой генерации: {str(e)}")
            yield f"Ошибка: {str(e)}"

    def check_model_health(self) -> Dict[str, Any]:
        """
        Проверка работоспособности моделей

        Returns:
            Статус моделей
        """
        try:
            # Проверяем основную модель
            test_response = self.simple_generate("Привет", max_tokens=10)
            main_model_ok = "Ошибка" not in test_response

            # Проверяем модель эмбеддингов
            test_embedding = self.get_embeddings("тестовый текст")
            embedding_model_ok = len(test_embedding) > 0

            return {
                "main_model": {
                    "name": self.model_name,
                    "status": "active" if main_model_ok else "error",
                    "test_passed": main_model_ok
                },
                "embedding_model": {
                    "name": self.embedding_model,
                    "status": "active" if embedding_model_ok else "error",
                    "test_passed": embedding_model_ok
                },
                "timestamp": __import__('datetime').datetime.now().isoformat()
            }

        except Exception as e:
            return {
                "error": str(e),
                "main_model": {"name": self.model_name, "status": "error"},
                "embedding_model": {"name": self.embedding_model, "status": "error"}
            }