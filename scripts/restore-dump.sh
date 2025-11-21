#!/bin/bash
# Восстановление БД из дампа. Не падает по OOM, виден прогресс.
#
# Использование:
#   ./scripts/restore-dump.sh /path/to/train1.dump
#
# Сохранить лог и смотреть прогресс в другом терминале:
#   ./scripts/restore-dump.sh /root/train1.dump 2>&1 | tee restore.log
#   tail -f restore.log
set -e
cd "$(dirname "$0")/.."
DUMP="${1:-./train.dmp}"
if [[ ! -f "$DUMP" ]]; then
  echo "Файл дампа не найден: $DUMP"
  echo "Укажите путь: $0 /path/to/train1.dump"
  exit 1
fi

echo "=============================================="
echo "Восстановление из: $DUMP"
echo "=============================================="

TABLE_COUNT=$(docker compose exec -T db psql -U postgres -d train -t -c \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';" 2>/dev/null | tr -d ' \n\r' || echo "0")

if [[ "$TABLE_COUNT" -gt 0 ]]; then
  echo ""
  echo "ВНИМАНИЕ: БД train уже содержит $TABLE_COUNT таблиц!"
  echo "Если продолжить, все данные будут УДАЛЕНЫ."
  read -p "Продолжить? (yes/no): " CONFIRM
  if [[ "$CONFIRM" != "yes" ]]; then
    echo "Отменено."
    exit 0
  fi
fi

echo ""
echo "Пересоздаю БД train..."
docker compose exec -T db psql -U postgres -d postgres -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='train' AND pid <> pg_backend_pid();" 2>/dev/null || true
docker compose exec -T db psql -U postgres -d postgres -c "DROP DATABASE IF EXISTS train;"
docker compose exec -T db psql -U postgres -d postgres -c "CREATE DATABASE train;"
docker compose exec -T db psql -U postgres -d train -c "CREATE EXTENSION IF NOT EXISTS postgis;"

if file "$DUMP" | grep -q "PostgreSQL custom"; then
  DUMP_NAME=$(basename "$DUMP")
  echo ""
  echo "Шаг 1/3: Копирую дамп в контейнер..."
  if docker compose cp "$DUMP" "db:/tmp/$DUMP_NAME" 2>/dev/null; then
    true
  else
    docker cp "$DUMP" trains_postgis:/tmp/"$DUMP_NAME"
  fi
  echo "Шаг 2/3: Запускаю pg_restore (это может занять 30–60+ минут для больших дампов)."
  echo "         Ниже будет прогресс по каждому объекту/таблице."
  echo ""
  START=$(date +%s)
  if docker compose exec -e PGPASSWORD=EYFXfc9KH7kb8pjo1sOV0ZZ3 db pg_restore -U postgres -d train --no-owner --no-acl --verbose "/tmp/$DUMP_NAME"; then
    RESTORE_OK=1
  else
    RESTORE_OK=0
  fi
  END=$(date +%s)
  docker compose exec db rm -f "/tmp/$DUMP_NAME" 2>/dev/null || true
  echo ""
  echo "Шаг 3/3: Готово. Время: $(( (END - START) / 60 )) мин."
  if [[ "$RESTORE_OK" -eq 0 ]]; then
    echo "pg_restore завершился с ошибками (часто из-за дубликатов — часть данных могла восстановиться)."
  fi
else
  echo "Использую psql (дамп как SQL)..."
  cat "$DUMP" | docker compose exec -T db psql -U postgres -d train
fi

echo ""
echo "Таблицы в БД train:"
docker compose exec db psql -U postgres -d train -c "\dt"
COUNT=$(docker compose exec -T db psql -U postgres -d train -t -c \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';" | tr -d ' ')
echo "Всего таблиц: $COUNT"
if [[ -n "$COUNT" ]] && [[ "$COUNT" -eq 0 ]]; then
  echo "БД пустая. Проверьте дамп и память контейнера (mem_limit в docker-compose)."
  exit 1
fi
