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

    def stream_response_with_rag(
            self,
            user_message: str,
            history: Optional[List[Dict]] = None,
            use_rag: bool = True,
            temperature: float = 0.7
    ):
        """
        Потоковая генерация ответа с RAG

        Args:
            user_message: Сообщение пользователя
            history: История диалога
            use_rag: Использовать ли RAG
            temperature: Температура генерации

        Yields:
            Части сгенерированного ответа
        """
        try:
            # Шаг 1: Поиск по документам
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
                system_prompt = f"""{Config.SYSTEM_PROMPT}

                Вопрос пользователя: {user_message}

                Ответ:"""

            # Шаг 3: Формирование сообщений
            messages = []

            if history:
                for msg in history:
                    if msg['role'] in ['user', 'assistant']:
                        messages.append({
                            "role": msg['role'],
                            "content": msg['content']
                        })

            messages.append({
                "role": "user",
                "content": user_message
            })

            # Шаг 4: Потоковая генерация
            for chunk in self.model.stream_chat(
                    messages=messages,
                    system_prompt=system_prompt
            ):
                yield chunk

        except Exception as e:
            logger.error(f"Ошибка в stream_response_with_rag: {e}")
            yield f"Ошибка: {str(e)}"