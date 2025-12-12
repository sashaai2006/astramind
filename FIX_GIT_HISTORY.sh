#!/bin/bash
# Скрипт для удаления секрета из git истории

echo "Удаление DEPLOY_STEPS.txt из всей git истории..."

# Вариант 1: Использовать git filter-branch (если git filter-repo не установлен)
git filter-branch --force --index-filter \
  "git rm --cached --ignore-unmatch DEPLOY_STEPS.txt" \
  --prune-empty --tag-name-filter cat -- --all

# Очистка
git for-each-ref --format="delete %(refname)" refs/original | git update-ref --stdin
git reflog expire --expire=now --all
git gc --prune=now --aggressive

echo "Готово! Теперь можно запушить: git push --force"

