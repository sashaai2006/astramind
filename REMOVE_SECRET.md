# УДАЛЕНИЕ СЕКРЕТА ИЗ GIT ИСТОРИИ

## Вариант 1: Удалить коммит через rebase (РЕКОМЕНДУЕТСЯ)

```bash
# 1. Начните интерактивный rebase с коммита ПЕРЕД проблемным
git rebase -i a34259c^

# 2. В открывшемся редакторе найдите строку с коммитом a34259c
# 3. Замените "pick" на "drop" или просто удалите эту строку
# 4. Сохраните и закройте (в vim: Esc, :wq, Enter)

# 5. Запушьте с force (ОСТОРОЖНО - это перепишет историю!)
git push --force origin main
```

## Вариант 2: Использовать filter-branch

```bash
# Удалить файл из всей истории
git filter-branch --force --index-filter \
  "git rm --cached --ignore-unmatch DEPLOY_STEPS.txt" \
  --prune-empty --tag-name-filter cat -- --all

# Очистка
git for-each-ref --format="delete %(refname)" refs/original | git update-ref --stdin
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# Запушьте
git push --force origin main
```

## Вариант 3: Использовать BFG Repo-Cleaner (самый быстрый)

```bash
# Установите BFG
brew install bfg  # на Mac

# Удалите файл
bfg --delete-files DEPLOY_STEPS.txt

# Очистка
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# Запушьте
git push --force origin main
```

## ВАЖНО!

1. **СМЕНИТЕ API КЛЮЧ В GROQ** - старый уже скомпрометирован!
2. После force push история изменится - если кто-то уже склонировал репозиторий, им нужно будет сделать `git pull --rebase`
3. Force push может быть опасен, если над проектом работают несколько человек

## Самый простой способ (если коммит последний):

```bash
# Отменить последний коммит, но оставить изменения
git reset --soft HEAD~1

# Удалить DEPLOY_STEPS.txt если он есть
git rm --cached DEPLOY_STEPS.txt 2>/dev/null || true

# Создать новый коммит без секрета
git commit -m "+docker"

# Запушить
git push --force origin main
```

