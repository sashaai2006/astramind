#!/bin/bash
# Скрипт для удаления коммита с секретом

echo "Удаление коммита a34259c с секретом из истории..."

# Создаем backup ветки на всякий случай
git branch backup-before-fix

# Используем filter-branch для удаления файла из всей истории
git filter-branch --force --index-filter \
  "git rm --cached --ignore-unmatch DEPLOY_STEPS.txt" \
  --prune-empty --tag-name-filter cat -- --all

# Очистка
echo "Очистка..."
git for-each-ref --format="delete %(refname)" refs/original | git update-ref --stdin 2>/dev/null || true
git reflog expire --expire=now --all
git gc --prune=now --aggressive

echo ""
echo "✅ Готово! Теперь выполните:"
echo "   git push --force origin main"
echo ""
echo "⚠️  ВАЖНО: Смените API ключ в Groq - старый скомпрометирован!"

