# Развёртывание на новом сервере

Инструкция по подъёму системы на другом сервере, когда вы получаете готовый дамп БД.

---

## Что нужно от отправителя

1. **Репозиторий проекта** (код: backend, frontend, scripts, docker-compose.yml)
2. **Дамп БД** — файл `train.dump` (pg_dump custom format, ~21 GB в сжатом виде)
3. **Excel с направлениями** — `data/trains_directions.xlsx` (если дамп создан до запуска loader)

Либо **готовые Docker-образы** backend и frontend (см. раздел «Сборка образов» ниже).

---

## Требования к серверу

- **Docker** и **Docker Compose**
- **RAM:** минимум 4 GB (рекомендуется 8 GB для restore)
- **Диск:** ~25 GB свободного места (дамп + pgdata)

---

## Сборка Docker-образов

Backend и frontend собираются из Dockerfile. Образ БД — готовый `postgis/postgis:16-3.4`.

```bash
cd t_trip

# Собрать все образы
docker compose build

# Или по отдельности
docker compose build backend
docker compose build frontend
```

Получаются образы:
- `t_trip-backend:latest`
- `t_trip-frontend:latest`

### Публикация в registry (опционально)

```bash
# Тегировать для своего registry
docker tag t_trip-backend:latest your-registry/t_trip-backend:latest
docker tag t_trip-frontend:latest your-registry/t_trip-frontend:latest

# Запушить
docker push your-registry/t_trip-backend:latest
docker push your-registry/t_trip-frontend:latest
```

На целевом сервере в `docker-compose.yml` замените `build:` на `image: your-registry/t_trip-backend:latest` (и аналогично для frontend), если хотите использовать готовые образы вместо сборки.

---

## Шаг 1. Подготовка

```bash
# Клонируйте или скопируйте проект
git clone <repo_url> t_trip
cd t_trip

# Соберите образы (если не используете готовые)
docker compose build

# Убедитесь, что Docker запущен
docker --version
docker compose version
```

---

## Шаг 2. Пароль БД (опционально)

По умолчанию в `docker-compose.yml` задан пароль PostgreSQL. Для продакшена лучше сменить:

1. Сгенерируйте новый пароль (например: `openssl rand -base64 24`)
2. Замените `POSTGRES_PASSWORD` в `docker-compose.yml` во всех сервисах (db, backend, loader)
3. Если используете `restore-dump.sh` — в нём тоже замените пароль в команде `pg_restore` (или передавайте через `PGPASSWORD`)

---

## Шаг 3. Скопировать дамп на сервер

```bash
# Пример: дамп в /root/train.dump
scp train.dump user@your-server:/root/t_trip/
```

---

## Шаг 4. Запустить только БД

```bash
cd /root/t_trip
docker compose up -d db
```

Дождитесь, пока БД станет healthy (обычно 10–30 секунд):

```bash
docker compose ps
# db должен быть "healthy"
```

---

## Шаг 5. Восстановить дамп

```bash
chmod +x scripts/restore-dump.sh
./scripts/restore-dump.sh /root/t_trip/train.dump
```

> **Важно:** Восстановление большого дампа может занять 30–60+ минут. Рекомендуется сохранить лог:
> ```bash
> ./scripts/restore-dump.sh /root/t_trip/train.dump 2>&1 | tee restore.log
> tail -f restore.log   # в другом терминале
> ```

Скрипт:
- Пересоздаёт БД `train`
- Включает PostGIS
- Копирует дамп в контейнер и запускает `pg_restore`
- Показывает список таблиц по завершении

---

## Шаг 6. Загрузка направлений (если нужно)

Если дамп был создан **до** запуска loader (таблицы `rzd_stations` и `train_directions` пустые или отсутствуют), выполните:

```bash
# Убедитесь, что data/trains_directions.xlsx на месте
docker compose --profile load run --rm loader
```

Если дамп уже содержал заполненные `rzd_stations` и `train_directions`, этот шаг можно пропустить.

---

## Шаг 7. Запустить все сервисы

```bash
# Собрать образы (если ещё не собраны) и запустить
docker compose up -d --build
```

Проверка:

```bash
docker compose ps
# db, backend, frontend — все running
```

---

## Шаг 8. Проверка

- **Streamlit (UI):** http://\<IP-сервера\>:8501
- **FastAPI (Swagger):** http://\<IP-сервера\>:8000/docs
- **Тест поиска:** POST `/search` с координатами Москва → Санкт-Петербург

---

## Порты

| Сервис   | Порт | Доступ                    |
|----------|------|---------------------------|
| frontend | 8501 | Внешний                   |
| backend  | 8000 | Внешний                   |
| db       | 5432 | Только localhost (безопасность) |

Для подключения к БД извне используйте **SSH-туннель** (см. основной README).

---

## Возможные проблемы

### OOM при restore

Если контейнер `db` падает по памяти, в `docker-compose.yml` уже задано `mem_limit: 3g`. Увеличьте до 4–6 GB при необходимости.

### Пароль в restore-dump.sh

Скрипт использует пароль из `docker-compose.yml`. Если вы сменили пароль, отредактируйте строку с `PGPASSWORD` в `scripts/restore-dump.sh` (или передайте `PGPASSWORD=xxx ./scripts/restore-dump.sh ...`).

### Backend возвращает 503

Граф не загружен. Убедитесь, что:
1. БД восстановлена
2. Таблицы `rzd_stations` и `train_directions` заполнены (запустите loader при необходимости)
3. Перезапустите backend: `docker compose restart backend`
