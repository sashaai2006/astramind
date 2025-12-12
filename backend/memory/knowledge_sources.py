from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from backend.utils.logging import get_logger

LOGGER = get_logger(__name__)

# Ленивый импорт vector_store
_vector_store = None

def _get_vector_store():
    global _vector_store
    if _vector_store is None:
        from backend.memory.vector_store import _get_client, _get_embedding_function
        _vector_store = (_get_client, _get_embedding_function)
    return _vector_store

@dataclass
class KnowledgeSource:
    id: str
    name: str
    source_type: str  # "documentation", "api_spec", "code_examples", "custom"
    description: str
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

class KnowledgeSourceRegistry:
    
    COLLECTION_NAME = "knowledge_sources"
    
    def __init__(self):
        self._sources: Dict[str, KnowledgeSource] = {}
        self._collection = None
    
    def _get_collection(self):
        if self._collection is not None:
            return self._collection
        
        get_client, get_embedding_fn = _get_vector_store()
        
        # Пробуем ChromaDB
        client = get_client()
        if client is not None:
            embedding_fn = get_embedding_fn()
            try:
                self._collection = client.get_or_create_collection(
                    name=self.COLLECTION_NAME,
                    embedding_function=embedding_fn,
                    metadata={"type": "knowledge"}
                )
                return self._collection
            except Exception as e:
                LOGGER.warning("Ошибка ChromaDB для знаний: %s. Используем SQLite fallback.", e)
        
        # Fallback на SQLite
        from backend.memory.vector_store import _get_fallback_collection
        self._collection = _get_fallback_collection(self.COLLECTION_NAME)
        return self._collection
    
    def register_source(self, source: KnowledgeSource) -> bool:
        self._sources[source.id] = source
        LOGGER.info("Зарегистрирован источник знаний: %s (%s)", source.name, source.source_type)
        return True
    
    def unregister_source(self, source_id: str) -> bool:
        if source_id in self._sources:
            del self._sources[source_id]
            LOGGER.info("Удален источник знаний: %s", source_id)
            return True
        return False
    
    def get_source(self, source_id: str) -> Optional[KnowledgeSource]:
        return self._sources.get(source_id)
    
    def list_sources(self) -> List[KnowledgeSource]:
        return list(self._sources.values())
    
    def add_knowledge(
        self,
        source_id: str,
        content: str,
        title: str = "",
        tags: Optional[List[str]] = None
    ) -> bool:
        collection = self._get_collection()
        if collection is None:
            return False
        
        try:
            doc_id = hashlib.sha256(f"{source_id}:{content[:100]}".encode()).hexdigest()[:16]
            
            metadata = {
                "source_id": source_id,
                "title": title,
                "tags": ",".join(tags or [])
            }
            
            collection.add(
                documents=[content],
                ids=[doc_id],
                metadatas=[metadata]
            )
            
            LOGGER.debug("Добавлено знание: source=%s, title=%s", source_id, title)
            return True
            
        except Exception as e:
            LOGGER.error("Ошибка добавления знания: %s", e)
            return False
    
    def search_knowledge(
        self,
        query: str,
        n_results: int = 5,
        source_ids: Optional[List[str]] = None,
        tags: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        collection = self._get_collection()
        if collection is None:
            return []
        
        try:
            where_filter = None
            if source_ids:
                where_filter = {"source_id": {"$in": source_ids}}
            
            results = collection.query(
                query_texts=[query],
                n_results=n_results,
                where=where_filter
            )
            
            output = []
            if results and results["documents"]:
                for i, doc in enumerate(results["documents"][0]):
                    meta = results["metadatas"][0][i] if results.get("metadatas") else {}
                    
                    # Фильтр по тегам (если указан)
                    if tags:
                        doc_tags = meta.get("tags", "").split(",")
                        if not any(t in doc_tags for t in tags):
                            continue
                    
                    output.append({
                        "content": doc,
                        "score": results["distances"][0][i] if results.get("distances") else 0,
                        "source_id": meta.get("source_id", ""),
                        "title": meta.get("title", ""),
                        "tags": meta.get("tags", "").split(",") if meta.get("tags") else []
                    })
            
            return output
            
        except Exception as e:
            LOGGER.error("Ошибка поиска знаний: %s", e)
            return []
    
    def get_context_for_task(
        self,
        task_description: str,
        tech_stack: Optional[str] = None,
        max_chars: int = 2000
    ) -> str:
        # Формируем расширенный запрос
        query = task_description
        if tech_stack:
            query = f"{tech_stack}: {query}"
        
        results = self.search_knowledge(query, n_results=5)
        
        if not results:
            return ""
        
        context_parts = []
        total_chars = 0
        
        for r in results:
            content = r["content"]
            title = r.get("title", "")
            source = r.get("source_id", "unknown")
            
            entry = f"[{source}] {title}\n{content}" if title else f"[{source}]\n{content}"
            
            if total_chars + len(entry) > max_chars:
                remaining = max_chars - total_chars
                if remaining > 100:
                    context_parts.append(entry[:remaining] + "...")
                break
            
            context_parts.append(entry)
            total_chars += len(entry)
        
        return "\n\n---\n\n".join(context_parts)

# Предустановленные источники знаний
def _create_default_sources() -> List[KnowledgeSource]:
    return [
        KnowledgeSource(
            id="best_practices",
            name="Software Engineering Best Practices",
            source_type="documentation",
            description="SOLID, DRY, KISS, clean code principles",
        ),
        KnowledgeSource(
            id="security",
            name="Security Guidelines",
            source_type="documentation",
            description="OWASP, secure coding, input validation",
        ),
        KnowledgeSource(
            id="python_style",
            name="Python Style Guide",
            source_type="documentation",
            description="PEP 8, type hints, pythonic idioms",
        ),
        KnowledgeSource(
            id="javascript_style",
            name="JavaScript/TypeScript Style",
            source_type="documentation",
            description="ESLint rules, modern JS, TypeScript best practices",
        ),
        KnowledgeSource(
            id="cpp_style",
            name="C++ Style Guide",
            source_type="documentation",
            description="Google C++ style, modern C++, RAII",
        ),
    ]

def _populate_default_knowledge(registry: KnowledgeSourceRegistry):
    
    # Best Practices
    registry.add_knowledge(
        "best_practices",
        content="""
SOLID Principles:
- Single Responsibility: A class should have only one reason to change
- Open/Closed: Open for extension, closed for modification
- Liskov Substitution: Objects should be replaceable with their subtypes
- Interface Segregation: Many specific interfaces > one general-purpose
- Dependency Inversion: Depend on abstractions, not concretions

DRY (Don't Repeat Yourself):
- Extract common logic into functions/classes
- Use constants for magic numbers
- Create utilities for repeated patterns

KISS (Keep It Simple, Stupid):
- Avoid over-engineering
- Prefer readability over cleverness
- Simple solutions are easier to maintain
        """,
        title="Core Engineering Principles",
        tags=["architecture", "design", "principles"]
    )
    
    # Security
    registry.add_knowledge(
        "security",
        content="""
Input Validation:
- NEVER trust user input
- Validate on both client and server
- Use parameterized queries (prevent SQL injection)
- Sanitize HTML output (prevent XSS)
- Validate file uploads (type, size, content)

Authentication:
- Use strong password hashing (bcrypt, argon2)
- Implement rate limiting for login attempts
- Use secure session management
- Consider MFA for sensitive operations

API Security:
- Use HTTPS everywhere
- Implement proper CORS
- Validate API tokens on every request
- Log security events
        """,
        title="Security Best Practices",
        tags=["security", "validation", "authentication"]
    )
    
    # Python
    registry.add_knowledge(
        "python_style",
        content="""
Python Style (PEP 8):
- Use 4 spaces for indentation
- Maximum line length: 79-88 characters
- Use snake_case for functions/variables
- Use PascalCase for classes
- Use UPPERCASE for constants

Type Hints:
def greet(name: str) -> str:
    return f"Hello, {name}"

def process(items: List[int]) -> Dict[str, int]:
    return {"sum": sum(items), "count": len(items)}

Pythonic Idioms:
- List comprehensions: [x*2 for x in range(10)]
- Context managers: with open(file) as f:
- Generators for large data: (x for x in huge_list)
- f-strings for formatting: f"Value: {value}"
        """,
        title="Python Coding Standards",
        tags=["python", "style", "pep8"]
    )
    
    # JavaScript
    registry.add_knowledge(
        "javascript_style",
        content="""
Modern JavaScript:
- Use const by default, let when needed, never var
- Arrow functions for callbacks: (x) => x * 2
- Destructuring: const { name, age } = person
- Spread operator: [...array, newItem]
- Optional chaining: user?.profile?.avatar
- Nullish coalescing: value ?? defaultValue

TypeScript:
- Always define types for function parameters
- Use interfaces for object shapes
- Use enums for fixed sets of values
- Prefer 'unknown' over 'any'

React Best Practices:
- Functional components with hooks
- useMemo/useCallback for optimization
- Custom hooks for reusable logic
- Props destructuring in function signature
        """,
        title="JavaScript/TypeScript Standards",
        tags=["javascript", "typescript", "react"]
    )
    
    # C++
    registry.add_knowledge(
        "cpp_style",
        content="""
Modern C++ (C++17/20):
- Use auto for complex types
- Prefer smart pointers (unique_ptr, shared_ptr)
- Use RAII for resource management
- Prefer range-based for loops
- Use constexpr for compile-time computation
- Use std::optional for nullable values
- Use std::string_view for non-owning strings

Memory Safety:
- Avoid raw new/delete
- Use containers (vector, map, unordered_map)
- Check bounds with .at() in debug builds
- Use references over pointers when possible

Project Structure:
- Separate headers (.h/.hpp) and implementation (.cpp)
- Use namespaces to avoid collisions
- Provide CMakeLists.txt or Makefile
- Include README with build instructions
        """,
        title="C++ Coding Standards",
        tags=["cpp", "modern", "memory"]
    )

# Глобальный реестр
_registry: Optional[KnowledgeSourceRegistry] = None

def get_knowledge_registry() -> KnowledgeSourceRegistry:
    global _registry
    if _registry is None:
        _registry = KnowledgeSourceRegistry()
        
        # Регистрируем базовые источники
        for source in _create_default_sources():
            _registry.register_source(source)
        
        # Заполняем базовыми знаниями
        _populate_default_knowledge(_registry)
    
    return _registry

