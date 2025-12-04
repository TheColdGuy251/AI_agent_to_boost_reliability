# routes/documents.py
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from pathlib import Path
from datetime import datetime
import logging

from config import Config
from data.db_session import create_session
from data.users import User

documents_bp = Blueprint('documents', __name__)
logger = logging.getLogger(__name__)


def get_document_processor():
    """
    Ленивая инициализация DocumentProcessor
    """
    from utils.document_processor import DocumentProcessor
    from utils.local_model import LlamaModel

    # Создаем модель
    llama_model = LlamaModel(
        model_name=Config.MODEL_NAME,
        embedding_model=Config.EMBEDDING_MODEL
    )

    # Создаем процессор документов
    return DocumentProcessor(model=llama_model)


@documents_bp.route('/documents/health', methods=['GET'])
def check_health():
    """
    Проверка здоровья системы документов
    """
    try:
        # Ленивая инициализация
        document_processor = get_document_processor()

        # Проверяем модели
        model_status = document_processor.model.check_model_health()

        # Проверяем коллекцию
        collection_info = document_processor.get_collection_info()

        # Проверяем папку с документами
        docs_dir = Path(Config.DOCS_DIR)
        docs_exist = docs_dir.exists()
        doc_files = []

        if docs_exist:
            doc_files = [f.name for f in docs_dir.glob("*.docx") if not f.name.startswith('~$')]

        return jsonify({
            'models': model_status,
            'collection': collection_info,
            'docs_directory': {
                'exists': docs_exist,
                'path': str(docs_dir),
                'files': doc_files,
                'file_count': len(doc_files)
            },
            'status': 'healthy' if model_status['main_model']['status'] == 'active' else 'degraded'
        }), 200

    except Exception as e:
        logger.error(f"Ошибка при проверке здоровья: {e}")
        return jsonify({'error': str(e), 'status': 'unhealthy'}), 500


@documents_bp.route('/documents/process', methods=['POST'])
@jwt_required()
def process_documents():
    """
    Обработать все документы в папке docs
    """
    try:
        # Проверяем права пользователя
        current_user_id = get_jwt_identity()
        session = create_session()
        user = session.query(User).get(current_user_id)

        if not user:
            return jsonify({'error': 'Пользователь не найден'}), 404

        # Ленивая инициализация
        document_processor = get_document_processor()

        # Обрабатываем документы
        processed_docs = document_processor.process_all_documents()

        if not processed_docs:
            return jsonify({
                'message': 'Нет документов для обработки',
                'processed': 0,
                'total_chunks': 0
            }), 200

        # Добавляем в векторную базу
        document_processor.add_documents_to_vector_db(processed_docs)

        # Получаем информацию о коллекции
        collection_info = document_processor.get_collection_info()

        # Статистика обработки
        total_chars = sum(doc['total_chars'] for doc in processed_docs)
        total_words = sum(doc['word_count'] for doc in processed_docs)

        return jsonify({
            'message': 'Документы успешно обработаны',
            'processed': len(processed_docs),
            'total_chunks': collection_info.get('total_chunks', 0),
            'total_chars': total_chars,
            'total_words': total_words,
            'unique_files': collection_info.get('unique_files', 0),
            'collection_info': collection_info
        }), 200

    except Exception as e:
        logger.error(f"Ошибка при обработке документов: {e}")
        return jsonify({'error': str(e)}), 500


@documents_bp.route('/documents/search', methods=['POST'])
@jwt_required()
def search_documents():
    """
    Поиск по документам
    """
    try:
        data = request.get_json()
        query = data.get('query')

        if not query:
            return jsonify({'error': 'Запрос не может быть пустым'}), 400

        # Ленивая инициализация
        document_processor = get_document_processor()

        n_results = data.get('n_results', Config.RAG_N_RESULTS)

        # Ищем релевантные документы
        results = document_processor.search_documents(
            query,
            n_results=n_results
        )

        # Форматируем ответ
        formatted_results = []
        for result in results:
            formatted_results.append({
                'content': result['document'],
                'source': {
                    'filename': result['metadata']['filename'],
                    'chunk': result['metadata']['chunk_index'] + 1,
                    'total_chunks': result['metadata']['total_chunks'],
                    'similarity': 1 - result['distance'] if result['distance'] else None
                },
                'metadata': result['metadata']
            })

        return jsonify({
            'query': query,
            'results': formatted_results,
            'count': len(results),
            'model': document_processor.model.embedding_model
        }), 200

    except Exception as e:
        logger.error(f"Ошибка при поиске документов: {e}")
        return jsonify({'error': str(e)}), 500


@documents_bp.route('/documents/ask', methods=['POST'])
@jwt_required()
def ask_question():
    """
    Задать вопрос на основе документов (RAG)
    """
    try:
        data = request.get_json()
        question = data.get('question')

        if not question:
            return jsonify({'error': 'Вопрос не может быть пустым'}), 400

        # Ленивая инициализация
        document_processor = get_document_processor()

        # 1. Ищем релевантные документы
        n_results = data.get('n_results', Config.RAG_N_RESULTS)
        search_results = document_processor.search_documents(
            question,
            n_results=n_results
        )

        if not search_results:
            return jsonify({
                'answer': 'В документах не найдено информации по вашему вопросу.',
                'sources': [],
                'model': document_processor.model.model_name
            }), 200

        # 2. Формируем контекст из найденных документов
        context_parts = []
        sources = []

        for result in search_results:
            context_parts.append(result['document'])
            sources.append({
                'filename': result['metadata']['filename'],
                'chunk_index': result['metadata']['chunk_index'],
                'similarity': 1 - result['distance'] if result['distance'] else None,
                'content_preview': result['document'][:200] + '...' if len(result['document']) > 200 else result[
                    'document']
            })

        context = "\n\n---\n\n".join(context_parts)

        # 3. Формируем промпт для модели из конфигурации
        system_prompt = Config.RAG_PROMPTS['SYSTEM_WITH_CONTEXT'].format(
            base_system_prompt=Config.SYSTEM_PROMPT,
            context=context,
            question=question
        )

        # 4. Генерируем ответ
        messages = [
            {"role": "user", "content": question}
        ]

        response = document_processor.model.chat_generate(
            messages=messages,
            system_prompt=system_prompt,
            temperature=0.3
        )

        if not response.get('success', False):
            return jsonify({'error': response.get('error', 'Неизвестная ошибка')}), 500

        return jsonify({
            'answer': response['response'],
            'sources': sources,
            'model': response.get('model'),
            'tokens_used': response.get('tokens_used'),
            'context_used': len(context_parts)
        }), 200

    except Exception as e:
        logger.error(f"Ошибка при обработке вопроса: {e}")
        return jsonify({'error': str(e)}), 500


@documents_bp.route('/documents/info', methods=['GET'])
@jwt_required()
def get_documents_info():
    """
    Получить информацию о документах и векторной базе
    """
    try:
        # Ленивая инициализация
        document_processor = get_document_processor()

        collection_info = document_processor.get_collection_info()

        # Получаем список файлов в папке docs
        docs_dir = Path(Config.DOCS_DIR)
        files = []

        if docs_dir.exists():
            for file_path in docs_dir.glob("*.docx"):
                if not file_path.name.startswith('~$'):
                    files.append({
                        'name': file_path.name,
                        'size': file_path.stat().st_size,
                        'modified': datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
                        'path': str(file_path.relative_to(docs_dir))
                    })

        # Информация о моделях
        model_info = {
            'generation_model': document_processor.model.model_name,
            'embedding_model': document_processor.model.embedding_model
        }

        return jsonify({
            'collection_info': collection_info,
            'files': files,
            'model_info': model_info,
            'config': {
                'docs_dir': str(docs_dir),
                'chroma_dir': str(Path(Config.CHROMA_DIR)),
                'chunk_size': Config.CHUNK_SIZE,
                'chunk_overlap': Config.CHUNK_OVERLAP,
                'rag_n_results': Config.RAG_N_RESULTS
            }
        }), 200

    except Exception as e:
        logger.error(f"Ошибка при получении информации: {e}")
        return jsonify({'error': str(e)}), 500


@documents_bp.route('/documents/clear', methods=['POST'])
@jwt_required()
def clear_documents():
    """
    Очистить векторную базу (требуются права администратора)
    """
    try:
        # Проверяем права пользователя
        current_user_id = get_jwt_identity()
        session = create_session()
        user = session.query(User).get(current_user_id)

        if not user:
            return jsonify({'error': 'Пользователь не найден'}), 404

        # Здесь можно добавить проверку на администратора
        # if not user.is_admin:
        #     return jsonify({'error': 'Недостаточно прав'}), 403

        # Ленивая инициализация
        document_processor = get_document_processor()

        # Получаем информацию перед очисткой
        old_info = document_processor.get_collection_info()

        # Очищаем коллекцию
        document_processor.clear_collection()

        return jsonify({
            'message': 'Векторная база очищена',
            'old_collection': old_info,
            'new_collection': document_processor.get_collection_info()
        }), 200

    except Exception as e:
        logger.error(f"Ошибка при очистке базы: {e}")
        return jsonify({'error': str(e)}), 500


@documents_bp.route('/documents/upload', methods=['POST'])
@jwt_required()
def upload_document():
    """
    Загрузить новый документ
    """
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'Файл не предоставлен'}), 400

        file = request.files['file']

        if file.filename == '':
            return jsonify({'error': 'Имя файла пустое'}), 400

        if not file.filename.endswith('.docx'):
            return jsonify({'error': 'Поддерживаются только файлы .docx'}), 400

        # Ленивая инициализация
        document_processor = get_document_processor()

        # Сохраняем файл
        docs_dir = Path(Config.DOCS_DIR)
        file_path = docs_dir / file.filename

        # Проверяем, не существует ли уже файл
        if file_path.exists():
            return jsonify({'error': f'Файл {file.filename} уже существует'}), 400

        file.save(file_path)

        # Обрабатываем файл
        doc_info = document_processor.process_single_document(file_path)

        if not doc_info:
            return jsonify({'error': 'Не удалось обработать документ'}), 500

        # Добавляем в векторную базу
        document_processor.add_documents_to_vector_db([doc_info])

        return jsonify({
            'message': 'Документ успешно загружен и обработан',
            'file': {
                'name': file.filename,
                'size': file_path.stat().st_size,
                'chunks': doc_info['chunk_count'],
                'words': doc_info['word_count']
            }
        }), 201

    except Exception as e:
        logger.error(f"Ошибка при загрузке документа: {e}")
        return jsonify({'error': str(e)}), 500