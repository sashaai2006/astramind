"""
Векторное хранилище для долгосрочной памяти агентов.

Поддерживает два режима:
1. ChromaDB (если установлен) - полноценный векторный поиск
2. SQLite fallback - простой текстовый поиск (BM25-like)

Позволяет:
- Сохранять контекст проекта (файлы, события, решения)
- Искать похожий контекст для улучшения качества генерации
- Семантический кэш запросов
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from collections import Counter
import math

from backend.utils.logging import get_logger

LOGGER = get_logger(__name__)

# Флаг использования ChromaDB
_USE_CHROMADB = False
_client = None
_embedding_function = None


def _get_client():
    """Ленивая инициализация ChromaDB клиента."""
    global _client, _USE_CHROMADB
    if _client is None:
        try:
            import chromadb
            from chromadb.config import Settings
            
            # Хранилище в папке data/chroma
            persist_dir = Path(__file__).parent.parent / "data" / "chroma"
            persist_dir.mkdir(parents=True, exist_ok=True)
            
            _client = chromadb.PersistentClient(
                path=str(persist_dir),
                settings=Settings(
                    anonymized_telemetry=False,
                    allow_reset=True
                )
            )
            _USE_CHROMADB = True
            LOGGER.info("ChromaDB инициализирован: %s", persist_dir)
        except ImportError:
            LOGGER.info("ChromaDB не установлен. Используем SQLite fallback.")
            _USE_CHROMADB = False
            return None
        except Exception as e:
            LOGGER.warning("Ошибка инициализации ChromaDB: %s. Используем SQLite fallback.", e)
            _USE_CHROMADB = False
            return None
    return _client


def _get_embedding_function():
    """Ленивая инициализация функции эмбеддингов."""
    global _embedding_function
    if _embedding_function is None and _USE_CHROMADB:
        try:
            from chromadb.utils import embedding_functions
            
            # Используем all-MiniLM-L6-v2 - быстрая и качественная модель
            _embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2"
            )
            LOGGER.info("Embedding функция инициализирована: all-MiniLM-L6-v2")
        except ImportError:
            LOGGER.info("sentence-transformers не установлен. Используем fallback.")
            return None
        except Exception as e:
            LOGGER.warning("Ошибка инициализации embedding функции: %s", e)
            return None
    return _embedding_function


# ============ SQLite Fallback Implementation ============

def _get_sqlite_db_path() -> Path:
    """Путь к SQLite базе для fallback."""
    db_path = Path(__file__).parent.parent / "data" / "vector_memory.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


def _init_sqlite_db():
    """Инициализация SQLite таблиц."""
    db_path = _get_sqlite_db_path()
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # Таблица для хранения документов
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            collection TEXT NOT NULL,
            content TEXT NOT NULL,
            metadata TEXT,
            tokens TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Индекс для быстрого поиска по коллекции
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_collection ON documents(collection)")
    
    conn.commit()
    conn.close()


def _tokenize(text: str) -> List[str]:
    """Простая токенизация текста."""
    # Приводим к нижнему регистру и разбиваем на слова
    text = text.lower()
    # Удаляем специальные символы, оставляем буквы и цифры
    tokens = re.findall(r'\b[a-zа-яё0-9_]+\b', text)
    # Фильтруем стоп-слова (базовый список)
    stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 
                  'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
                  'would', 'could', 'should', 'may', 'might', 'must', 'shall',
                  'can', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by',
                  'from', 'or', 'and', 'not', 'this', 'that', 'it', 'as',
                  'и', 'в', 'на', 'с', 'по', 'из', 'за', 'к', 'для', 'от'}
    return [t for t in tokens if t not in stop_words and len(t) > 2]


def _calculate_bm25_score(query_tokens: List[str], doc_tokens: List[str], 
                          doc_freq: Dict[str, int], total_docs: int,
                          avg_doc_len: float, k1: float = 1.5, b: float = 0.75) -> float:
    """Расчёт BM25 score для документа."""
    score = 0.0
    doc_len = len(doc_tokens)
    doc_token_counts = Counter(doc_tokens)
    
    for token in query_tokens:
        if token not in doc_token_counts:
            continue
        
        tf = doc_token_counts[token]
        df = doc_freq.get(token, 0)
        
        if df == 0:
            continue
        
        # IDF
        idf = math.log((total_docs - df + 0.5) / (df + 0.5) + 1)
        
        # TF normalization
        tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * doc_len / avg_doc_len))
        
        score += idf * tf_norm
    
    return score


class SQLiteFallbackStore:
    """Fallback хранилище на SQLite с BM25 поиском."""
    
    def __init__(self, collection_name: str):
        self.collection_name = collection_name
        _init_sqlite_db()
    
    def add(self, documents: List[str], ids: List[str], metadatas: List[Dict]) -> None:
        """Добавить документы."""
        db_path = _get_sqlite_db_path()
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        for doc, doc_id, meta in zip(documents, ids, metadatas):
            tokens = _tokenize(doc)
            cursor.execute("""
                INSERT OR REPLACE INTO documents (id, collection, content, metadata, tokens)
                VALUES (?, ?, ?, ?, ?)
            """, (doc_id, self.collection_name, doc, json.dumps(meta), json.dumps(tokens)))
        
        conn.commit()
        conn.close()
    
    def upsert(self, documents: List[str], ids: List[str], metadatas: List[Dict]) -> None:
        """Добавить или обновить документы."""
        self.add(documents, ids, metadatas)
    
    def query(self, query_texts: List[str], n_results: int = 5, 
              where: Optional[Dict] = None, include: Optional[List[str]] = None) -> Dict:
        """Поиск документов с использованием BM25."""
        db_path = _get_sqlite_db_path()
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # Получаем все документы из коллекции
        cursor.execute("""
            SELECT id, content, metadata, tokens FROM documents WHERE collection = ?
        """, (self.collection_name,))
        
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return {"documents": [[]], "metadatas": [[]], "distances": [[]]}
        
        query_tokens = _tokenize(query_texts[0])
        
        # Расчёт статистик для BM25
        all_tokens = []
        doc_data = []
        for row in rows:
            doc_id, content, meta_json, tokens_json = row
            tokens = json.loads(tokens_json) if tokens_json else _tokenize(content)
            all_tokens.extend(tokens)
            doc_data.append({
                "id": doc_id,
                "content": content,
                "metadata": json.loads(meta_json) if meta_json else {},
                "tokens": tokens
            })
        
        total_docs = len(doc_data)
        avg_doc_len = len(all_tokens) / total_docs if total_docs > 0 else 1
        
        # Document frequency
        doc_freq = Counter()
        for d in doc_data:
            doc_freq.update(set(d["tokens"]))
        
        # Расчёт scores
        scored = []
        for d in doc_data:
            # Применяем фильтр where (если есть)
            if where:
                match = True
                for key, val in where.items():
                    if d["metadata"].get(key) != val:
                        match = False
                        break
                if not match:
                    continue
            
            score = _calculate_bm25_score(query_tokens, d["tokens"], doc_freq, 
                                          total_docs, avg_doc_len)
            scored.append((score, d))
        
        # Сортируем по score (убывание)
        scored.sort(key=lambda x: x[0], reverse=True)
        
        # Берём top-N
        top_n = scored[:n_results]
        
        documents = [[d["content"] for _, d in top_n]]
        metadatas = [[d["metadata"] for _, d in top_n]]
        # Конвертируем score в "distance" (меньше = лучше)
        distances = [[1 / (1 + s) for s, _ in top_n]]
        
        return {"documents": documents, "metadatas": metadatas, "distances": distances}


def _get_fallback_collection(name: str):
    """Получить fallback коллекцию."""
    return SQLiteFallbackStore(name)


class ProjectMemory:
    """
    Долгосрочная память для одного проекта.
    
    Хранит:
    - Контекст проекта (описание, цели, решения)
    - Сгенерированные файлы (для поиска похожего кода)
    - События и ошибки (для обучения на ошибках)
    """
    
    def __init__(self, project_id: str):
        self.project_id = project_id
        self._collection = None
    
    def _get_collection(self):
        """Получить или создать коллекцию для проекта."""
        if self._collection is not None:
            return self._collection
        
        # Имя коллекции: project_<id>
        collection_name = f"project_{self.project_id[:8]}"
        
        # Пробуем ChromaDB
        client = _get_client()
        if client is not None:
            embedding_fn = _get_embedding_function()
            try:
                self._collection = client.get_or_create_collection(
                    name=collection_name,
                    embedding_function=embedding_fn,
                    metadata={"project_id": self.project_id}
                )
                return self._collection
            except Exception as e:
                LOGGER.warning("Ошибка ChromaDB коллекции: %s. Используем SQLite fallback.", e)
        
        # Fallback на SQLite
        self._collection = _get_fallback_collection(collection_name)
        return self._collection
    
    def add_context(
        self,
        content: str,
        context_type: str = "general",
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Добавить контекст в память проекта.
        
        Args:
            content: Текст для сохранения
            context_type: Тип контекста (file, event, decision, error)
            metadata: Дополнительные метаданные
        """
        collection = self._get_collection()
        if collection is None:
            return False
        
        try:
            # Генерируем уникальный ID на основе контента
            doc_id = hashlib.sha256(f"{self.project_id}:{content[:100]}".encode()).hexdigest()[:16]
            
            meta = {
                "project_id": self.project_id,
                "type": context_type,
                **(metadata or {})
            }
            
            collection.add(
                documents=[content],
                ids=[doc_id],
                metadatas=[meta]
            )
            
            LOGGER.debug("Добавлен контекст в память: type=%s, len=%d", context_type, len(content))
            return True
            
        except Exception as e:
            LOGGER.error("Ошибка добавления контекста: %s", e)
            return False
    
    def search(
        self,
        query: str,
        n_results: int = 5,
        context_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Поиск похожего контекста.
        
        Args:
            query: Запрос для поиска
            n_results: Количество результатов
            context_type: Фильтр по типу контекста
        
        Returns:
            Список результатов с полями: content, score, metadata
        """
        collection = self._get_collection()
        if collection is None:
            return []
        
        try:
            where_filter = None
            if context_type:
                where_filter = {"type": context_type}
            
            results = collection.query(
                query_texts=[query],
                n_results=n_results,
                where=where_filter
            )
            
            output = []
            if results and results["documents"]:
                for i, doc in enumerate(results["documents"][0]):
                    output.append({
                        "content": doc,
                        "score": results["distances"][0][i] if results.get("distances") else 0,
                        "metadata": results["metadatas"][0][i] if results.get("metadatas") else {}
                    })
            
            LOGGER.debug("Найдено %d результатов для запроса: %s...", len(output), query[:50])
            return output
            
        except Exception as e:
            LOGGER.error("Ошибка поиска: %s", e)
            return []
    
    def add_file(self, path: str, content: str) -> bool:
        """Добавить файл в память."""
        return self.add_context(
            content=f"FILE: {path}\n\n{content[:5000]}",  # Ограничиваем размер
            context_type="file",
            metadata={"path": path}
        )
    
    def add_event(self, event: str, level: str = "info") -> bool:
        """Добавить событие в память."""
        return self.add_context(
            content=event,
            context_type="event",
            metadata={"level": level}
        )
    
    def add_decision(self, decision: str, reasoning: str = "") -> bool:
        """Добавить решение агента в память."""
        return self.add_context(
            content=f"DECISION: {decision}\nREASONING: {reasoning}",
            context_type="decision"
        )
    
    def get_relevant_context(self, task_description: str, max_chars: int = 3000) -> str:
        """
        Получить релевантный контекст для задачи.
        
        Используется агентами для улучшения качества генерации.
        """
        results = self.search(task_description, n_results=3)
        
        if not results:
            return ""
        
        context_parts = []
        total_chars = 0
        
        for r in results:
            content = r["content"]
            if total_chars + len(content) > max_chars:
                # Обрезаем если превышаем лимит
                remaining = max_chars - total_chars
                if remaining > 100:
                    context_parts.append(content[:remaining] + "...")
                break
            context_parts.append(content)
            total_chars += len(content)
        
        return "\n\n---\n\n".join(context_parts)


class SemanticCache:
    """
    Семантический кэш для LLM запросов.
    
    Вместо точного совпадения промпта ищет похожие запросы
    и возвращает закэшированный ответ если найден достаточно похожий.
    """
    
    def __init__(self, similarity_threshold: float = 0.85):
        """
        Args:
            similarity_threshold: Порог схожести (0-1). 
                                  0.85 = очень похожие запросы
        """
        self.similarity_threshold = similarity_threshold
        self._collection = None
    
    def _get_collection(self):
        """Получить или создать коллекцию для кэша."""
        if self._collection is not None:
            return self._collection
        
        # Пробуем ChromaDB
        client = _get_client()
        if client is not None:
            embedding_fn = _get_embedding_function()
            try:
                self._collection = client.get_or_create_collection(
                    name="semantic_cache",
                    embedding_function=embedding_fn,
                    metadata={"type": "cache"}
                )
                return self._collection
            except Exception as e:
                LOGGER.warning("Ошибка ChromaDB кэша: %s. Используем SQLite fallback.", e)
        
        # Fallback на SQLite
        self._collection = _get_fallback_collection("semantic_cache")
        return self._collection
    
    def get(self, prompt: str, filter_metadata: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """
        Поиск похожего запроса в кэше.
        
        Args:
            prompt: Текст запроса
            filter_metadata: Фильтр по метаданным (например, {"tech_stack": "cpp"})
            
        Returns:
            Закэшированный ответ или None
        """
        collection = self._get_collection()
        if collection is None:
            return None
        
        try:
            results = collection.query(
                query_texts=[prompt],
                n_results=1,
                where=filter_metadata,
                include=["documents", "metadatas", "distances"]
            )
            
            if not results or not results["documents"] or not results["documents"][0]:
                return None
            
            # ChromaDB возвращает L2 distance, конвертируем в similarity
            # Меньше distance = больше similarity
            distance = results["distances"][0][0]
            
            # Эвристика: L2 distance < 0.5 = similarity > 0.75
            # Для all-MiniLM-L6-v2 это работает хорошо
            if distance < (1 - self.similarity_threshold) * 2:
                cached_response = results["metadatas"][0][0].get("response")
                if cached_response:
                    LOGGER.info("Semantic Cache HIT (distance=%.3f)", distance)
                    return cached_response
            
            return None
            
        except Exception as e:
            LOGGER.error("Ошибка поиска в кэше: %s", e)
            return None
    
    def set(self, prompt: str, response: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        Сохранить запрос и ответ в кэш.
        """
        collection = self._get_collection()
        if collection is None:
            return False
        
        try:
            # ID на основе хэша промпта
            doc_id = hashlib.sha256(prompt.encode()).hexdigest()[:16]
            
            # Формируем метаданные: ответ + доп. поля (stack, etc.)
            meta = {"response": response[:50000]}  # Ограничиваем ответ
            if metadata:
                meta.update(metadata)

            # Сохраняем промпт как документ, ответ в метаданных
            # (ChromaDB ищет по документам, не по метаданным)
            collection.upsert(
                documents=[prompt[:10000]],  # Ограничиваем размер
                ids=[doc_id],
                metadatas=[meta]
            )
            
            LOGGER.debug("Semantic Cache SET: %s...", prompt[:50])
            return True
            
        except Exception as e:
            LOGGER.error("Ошибка сохранения в кэш: %s", e)
            return False
    
    def clear(self) -> bool:
        """Очистить кэш."""
        # Пробуем ChromaDB
        client = _get_client()
        if client is not None:
            try:
                client.delete_collection("semantic_cache")
                self._collection = None
                LOGGER.info("Semantic Cache очищен (ChromaDB)")
                return True
            except Exception as e:
                LOGGER.warning("Ошибка очистки ChromaDB кэша: %s", e)
        
        # Fallback: очистка SQLite
        try:
            db_path = _get_sqlite_db_path()
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute("DELETE FROM documents WHERE collection = ?", ("semantic_cache",))
            conn.commit()
            conn.close()
            self._collection = None
            LOGGER.info("Semantic Cache очищен (SQLite)")
            return True
        except Exception as e:
            LOGGER.error("Ошибка очистки кэша: %s", e)
            return False


# Глобальный экземпляр семантического кэша
_semantic_cache: Optional[SemanticCache] = None


def get_semantic_cache() -> SemanticCache:
    """Получить глобальный экземпляр семантического кэша."""
    global _semantic_cache
    if _semantic_cache is None:
        _semantic_cache = SemanticCache()
    return _semantic_cache


def get_project_memory(project_id: str) -> ProjectMemory:
    """Получить память для проекта."""
    return ProjectMemory(project_id)


