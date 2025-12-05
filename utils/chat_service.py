import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from utils.local_model import LlamaModel
from utils.document_processor import DocumentProcessor
from config import Config
from data.chat_message import ChatMessage
from data.chat_sessions import ChatSession

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(self, model: LlamaModel, document_processor: DocumentProcessor):
        self.model = model
        self.document_processor = document_processor

    def _build_rag_prompt(self, user_message: str, context_documents: List[Dict]) -> str:
        """Построение промпта с RAG контекстом"""
        context_parts = []

        for doc in context_documents:
            context_parts.append(
                f"[Документ: {doc['metadata']['filename']}, часть {doc['metadata']['chunk_index'] + 1}]")
            context_parts.append(doc['document'])
            context_parts.append("---")

        context = "\n".join(context_parts)

        # Используем промпт из конфигурации
        prompt_template = Config.RAG_PROMPTS['SYSTEM_WITH_CONTEXT_REFERENCE']

        return prompt_template.format(
            base_system_prompt=Config.SYSTEM_PROMPT,
            context=context,
            question=user_message
        )

    def _build_chat_history_prompt(self, user_message: str, history: List[Dict]) -> str:
        """Построение промпта с историей диалога"""
        history_text = []

        for msg in history:
            if msg['role'] == 'user':
                history_text.append(f"Пользователь: {msg['content']}")
            elif msg['role'] == 'assistant':
                history_text.append(f"Ассистент: {msg['content']}")

        history_str = "\n".join(history_text)

        # Используем промпт из конфигурации
        prompt_template = Config.RAG_PROMPTS['SYSTEM_WITH_HISTORY']

        return prompt_template.format(
            base_system_prompt=Config.SYSTEM_PROMPT,
            history=history_str,
            question=user_message
        )

    def generate_response_with_rag(
            self,
            user_message: str,
            history: Optional[List[Dict]] = None,
            use_rag: bool = True,
            temperature: float = 0.7
    ) -> Dict[str, Any]:
        """
        Генерация ответа с использованием RAG и истории диалога

        Args:
            user_message: Сообщение пользователя
            history: История диалога (список сообщений)
            use_rag: Использовать ли RAG для поиска по документам
            temperature: Температура генерации

        Returns:
            Словарь с ответом и метаданными
        """
        try:
            # Шаг 1: Поиск по документам (RAG)
            context_documents = []
            if use_rag:
                context_documents = self.document_processor.search_documents(
                    query=user_message,
                    n_results=Config.RAG_N_RESULTS
                )

            # Шаг 2: Построение промпта
            if context_documents:
                system_prompt = self._build_rag_prompt(user_message, context_documents)
            elif history:
                system_prompt = self._build_chat_history_prompt(user_message, history)
            else:
                # Используем прямой промпт из конфигурации
                prompt_template = Config.RAG_PROMPTS['SYSTEM_DIRECT']
                system_prompt = prompt_template.format(
                    base_system_prompt=Config.SYSTEM_PROMPT,
                    question=user_message
                )

            # Шаг 3: Формирование сообщений для модели
            messages = []

            # Добавляем историю диалога
            if history:
                for msg in history:
                    if msg['role'] in ['user', 'assistant']:
                        messages.append({
                            "role": msg['role'],
                            "content": msg['content']
                        })

            # Добавляем текущее сообщение пользователя
            messages.append({
                "role": "user",
                "content": user_message
            })

            # Шаг 4: Генерация ответа
            response = self.model.chat_generate(
                messages=messages,
                system_prompt=system_prompt,
                temperature=temperature
            )

            if not response.get('success', False):
                raise Exception(f"Ошибка генерации: {response.get('error')}")

            # Шаг 5: Формирование результата
            result = {
                'response': response['response'],
                'model': response.get('model'),
                'tokens_used': response.get('tokens_used', 0),
                'context_documents': [
                    {
                        'filename': doc['metadata']['filename'],
                        'chunk_index': doc['metadata']['chunk_index'],
                        'content_preview': doc['document'][:200] + '...' if len(doc['document']) > 200 else doc[
                            'document'],
                        'similarity': 1 - doc['distance'] if doc.get('distance') else None
                    }
                    for doc in context_documents
                ] if context_documents else [],
                'has_context': len(context_documents) > 0
            }

            return result

        except Exception as e:
            logger.error(f"Ошибка в generate_response_with_rag: {e}")
            return {
                'error': str(e),
                'response': f"Извините, произошла ошибка при обработке вашего запроса: {str(e)}",
                'success': False
            }

    def generate_response_with_rag(
            self,
            user_message: str,
            history: Optional[List[Dict]] = None,
            use_rag: bool = True,
            temperature: float = 0.7,
            system_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Генерация ответа с использованием RAG и истории диалога, с поддержкой явного system_prompt.

        Args:
            user_message: Сообщение пользователя.
            history: История диалога (list of {'role':..., 'content':...}).
            use_rag: Использовать RAG (поиск по документам).
            temperature: Температура генерации.
            system_prompt: Явный системный промпт (например, информация о задаче); если передан, будет объединён с RAG/context или историей.

        Returns:
            Словарь с ключами: response, model, tokens_used, context_documents, has_context
            В случае ошибки возвращается dict с 'error' и 'success': False
        """
        try:
            # 1) Поиск по документам (RAG)
            context_documents: List[Dict] = []
            if use_rag and self.document_processor is not None:
                try:
                    context_documents = self.document_processor.search_documents(
                        query=user_message,
                        n_results=Config.RAG_N_RESULTS
                    )
                except Exception as e:
                    logger.exception("Ошибка при поиске документов для RAG: %s", e)
                    context_documents = []

            # 2) Построение финального системного промпта
            final_system_prompt = None

            if context_documents:
                # Если есть RAG-контекст, сформируем RAG-промпт.
                try:
                    rag_prompt = self._build_rag_prompt(user_message, context_documents)
                except Exception:
                    # Фоллбек: используем Config.SYSTEM_PROMPT + контекст документов вручную
                    try:
                        context_parts = []
                        for doc in context_documents:
                            context_parts.append(
                                f"[Документ: {doc['metadata'].get('filename')} часть {doc['metadata'].get('chunk_index') + 1}]")
                            context_parts.append(doc.get('document', ''))
                            context_parts.append('---')
                        context = "\n".join(context_parts)
                        rag_prompt = Config.RAG_PROMPTS['SYSTEM_WITH_CONTEXT_REFERENCE'].format(
                            base_system_prompt=Config.SYSTEM_PROMPT,
                            context=context,
                            question=user_message
                        )
                    except Exception:
                        rag_prompt = f"{Config.SYSTEM_PROMPT}\n\nКонтекст: (не удалось сформировать RAG-контекст)\n\nВопрос пользователя: {user_message}\n\nОтвет:"

                # Если явный system_prompt передан, комбинируем (system_prompt выше, затем RAG)
                if system_prompt:
                    final_system_prompt = f"{system_prompt}\n\nДополнительный контекст из документов:\n{rag_prompt}"
                else:
                    final_system_prompt = rag_prompt

            elif history:
                # Нет RAG-контекста, используем историю + (опционально) system_prompt
                try:
                    history_prompt = self._build_chat_history_prompt(user_message, history)
                except Exception:
                    # fallback if building history prompt fails
                    history_text = "\n".join(
                        [f"{('Пользователь' if m['role'] == 'user' else 'Ассистент')}: {m['content']}" for m in
                         (history or [])]
                    )
                    history_prompt = Config.RAG_PROMPTS['SYSTEM_WITH_HISTORY'].format(
                        base_system_prompt=Config.SYSTEM_PROMPT,
                        history=history_text,
                        question=user_message
                    )

                if system_prompt:
                    final_system_prompt = f"{system_prompt}\n\n{history_prompt}"
                else:
                    final_system_prompt = history_prompt

            else:
                # Нет RAG и нет истории — используем либо переданный system_prompt, либо прямой шаблон
                if system_prompt:
                    final_system_prompt = system_prompt
                else:
                    prompt_template = Config.RAG_PROMPTS.get('SYSTEM_DIRECT') or Config.RAG_PROMPTS.get(
                        'SYSTEM_WITH_CONTEXT')
                    final_system_prompt = prompt_template.format(
                        base_system_prompt=Config.SYSTEM_PROMPT,
                        question=user_message,
                        context=""
                    ) if '{question}' in prompt_template else f"{Config.SYSTEM_PROMPT}\n\nВопрос пользователя: {user_message}\n\nОтвет:"

            # 3) Формирование сообщений: переносим только user/assistant сообщения в тело (system handled separately)
            messages = []
            if history:
                for msg in history:
                    if msg.get('role') in ['user', 'assistant']:
                        messages.append({
                            "role": msg.get('role'),
                            "content": msg.get('content')
                        })

            # Добавляем текущий пользовательский message
            messages.append({"role": "user", "content": user_message})

            # 4) Вызов модели
            response = self.model.chat_generate(
                messages=messages,
                system_prompt=final_system_prompt,
                temperature=temperature
            )

            if not response.get('success', False):
                raise Exception(f"Ошибка генерации: {response.get('error')}")

            # 5) Формирование результата
            result = {
                'response': response.get('response', ''),
                'model': response.get('model'),
                'tokens_used': response.get('tokens_used', 0),
                'context_documents': [
                    {
                        'filename': doc['metadata'].get('filename'),
                        'chunk_index': doc['metadata'].get('chunk_index'),
                        'content_preview': (doc['document'][:200] + '...') if len(
                            doc.get('document', '')) > 200 else doc.get('document', ''),
                        'similarity': (1 - doc.get('distance')) if doc.get('distance') is not None else None
                    }
                    for doc in context_documents
                ] if context_documents else [],
                'has_context': len(context_documents) > 0
            }

            return result

        except Exception as e:
            logger.exception("Ошибка в generate_response_with_rag: %s", e)
            return {
                'error': str(e),
                'response': f"Извините, произошла ошибка при обработке вашего запроса: {str(e)}",
                'success': False
            }

    def stream_response_with_rag(
            self,
            user_message: str,
            history: Optional[List[Dict]] = None,
            use_rag: bool = True,
            temperature: float = 0.7,
            system_prompt: Optional[str] = None
    ):
        """
        Потоковая генерация ответа с RAG и поддержкой явного system_prompt.
        Возвращает генератор, который выдаёт куски текста (строки).

        Args:
            user_message: текст запроса пользователя
            history: история диалога (list of {'role':..., 'content':...})
            use_rag: использовать ли поиск по документам
            temperature: температура генерации
            system_prompt: явный системный промпт (например, контекст задачи)
        Yields:
            части ответа (строки). В случае ошибки будет yield-иться строка с префиксом "Ошибка: ..."
        """
        try:
            # 1) Поиск по документам (RAG) (мягко — если document_processor отсутствует, пропускаем)
            context_documents = []
            if use_rag and getattr(self, "document_processor", None) is not None:
                try:
                    context_documents = self.document_processor.search_documents(
                        query=user_message,
                        n_results=Config.RAG_N_RESULTS
                    )
                except Exception as e:
                    logger.exception("Ошибка при поиске документов для потокового RAG: %s", e)
                    context_documents = []

            # 2) Построение финального системного промпта (комбинируем явный system_prompt + RAG/историю)
            final_system_prompt = None

            if context_documents:
                try:
                    rag_prompt = self._build_rag_prompt(user_message, context_documents)
                except Exception:
                    # Фоллбек: простая конкатенация контекста
                    context_parts = []
                    for doc in context_documents:
                        fn = doc.get('metadata', {}).get('filename', 'unknown')
                        idx = doc.get('metadata', {}).get('chunk_index', 0)
                        context_parts.append(f"[Документ: {fn}, часть {idx + 1}]")
                        context_parts.append(doc.get('document', ''))
                        context_parts.append('---')
                    context = "\n".join(context_parts)
                    rag_prompt = Config.RAG_PROMPTS.get('SYSTEM_WITH_CONTEXT_REFERENCE',
                                                        Config.RAG_PROMPTS.get('SYSTEM_WITH_CONTEXT', '')).format(
                        base_system_prompt=Config.SYSTEM_PROMPT,
                        context=context,
                        question=user_message
                    )

                if system_prompt:
                    final_system_prompt = f"{system_prompt}\n\nКонтекст из документов:\n{rag_prompt}"
                else:
                    final_system_prompt = rag_prompt

            elif history:
                try:
                    history_prompt = self._build_chat_history_prompt(user_message, history)
                except Exception:
                    history_text = "\n".join(
                        [f"{('Пользователь' if m['role'] == 'user' else 'Ассистент')}: {m['content']}" for m in
                         (history or [])])
                    history_prompt = Config.RAG_PROMPTS.get('SYSTEM_WITH_HISTORY', "").format(
                        base_system_prompt=Config.SYSTEM_PROMPT,
                        history=history_text,
                        question=user_message
                    )

                if system_prompt:
                    final_system_prompt = f"{system_prompt}\n\n{history_prompt}"
                else:
                    final_system_prompt = history_prompt

            else:
                # Нет RAG и нет истории
                if system_prompt:
                    final_system_prompt = system_prompt
                else:
                    prompt_template = Config.RAG_PROMPTS.get('SYSTEM_DIRECT') or Config.RAG_PROMPTS.get(
                        'SYSTEM_WITH_CONTEXT', '')
                    if '{question}' in prompt_template:
                        final_system_prompt = prompt_template.format(
                            base_system_prompt=Config.SYSTEM_PROMPT,
                            question=user_message,
                            context=""
                        )
                    else:
                        final_system_prompt = f"{Config.SYSTEM_PROMPT}\n\nВопрос пользователя: {user_message}\n\nОтвет:"

            # 3) Формирование списка сообщений (history + текущий user message)
            messages = []
            if history:
                for msg in history:
                    if msg.get('role') in ['user', 'assistant']:
                        messages.append({"role": msg.get('role'), "content": msg.get('content')})
            messages.append({"role": "user", "content": user_message})

            # 4) Вызов stream_chat у модели — пробрасываем чанки
            # Ожидаем, что self.model.stream_chat возвращает итератор/генератор строк или кусков
            try:
                for chunk in self.model.stream_chat(messages=messages, system_prompt=final_system_prompt):
                    # chunk может быть строкой или объектом — приводим к строке
                    yield str(chunk or '')
            except Exception as e:
                logger.exception("Ошибка при вызове model.stream_chat в stream_response_with_rag: %s", e)
                yield f"Ошибка: {str(e)}"
                return

        except Exception as e:
            logger.exception("Ошибка в stream_response_with_rag: %s", e)
            yield f"Ошибка: {str(e)}"

