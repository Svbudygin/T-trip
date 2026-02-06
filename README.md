# Путешествия — поиск ж/д маршрутов

Веб-приложение для поиска маршрутов между двумя точками на карте.

> **Развёртывание на новом сервере:** см. [DEPLOYMENT.md](DEPLOYMENT.md) — пошаговая инструкция при получении дампа БД.
Пользователь вводит координаты «откуда» и «куда», система находит ближайшие станции РЖД
и показывает до 10 лучших найденных кандидатов по времени или стоимости.

---

## Архитектура

```
┌──────────────┐     ┌──────────────┐     ┌──────────────────┐
│   Streamlit  │────>│   FastAPI    │────>│  PostgreSQL +    │
│   (frontend) │<────│   (backend)  │<────│  PostGIS (db)    │
│   :8501      │     │   :8000      │     │  :5432           │
└──────────────┘     └──────────────┘     └──────────────────┘
                                                   ^
                                                   |
                                          ┌────────┴────────┐
                                          │  loader (разово) │
                                          │  загрузка данных │
                                          └─────────────────┘
```

Все сервисы запускаются через **Docker Compose**.

---

## Структура проекта

```
t_trip/
├── backend/                 # FastAPI-бэкенд
│   ├── main.py              # API: POST /search
│   ├── requirements.txt     # Зависимости Python
│   └── Dockerfile
├── frontend/                # Streamlit-интерфейс
│   └── app.py               # Веб-форма и вывод маршрутов
├── scripts/                 # Скрипты для работы с данными
│   ├── load_train_directions.py   # Загрузка станций и направлений в БД
│   ├── enrich_excel_with_coords.py # Обогащение Excel координатами
│   ├── init_train_directions.sql  # SQL-схема таблиц
│   └── restore-dump.sh           # Восстановление дампа PostGIS
├── data/                    # Исходные данные (не в git)
│   ├── trains_directions.xlsx     # Направления РЖД (время, цена)
│   ├── coordinates.csv            # Координаты станций по коду
│   ├── stations_full.csv          # Справочник станций РЖД
│   ├── cites_full.csv             # Справочник городов
│   ├── train_routes.csv           # Маршруты (CSV-версия)
│   └── ...
├── pgdata/                  # Данные PostgreSQL (не в git)
├── docker-compose.yml       # Все сервисы
├── .gitignore
└── README.md                # Этот файл
```

---

## Таблицы в БД (база `train`)

### Из дампа OSM (не трогаем)

| Таблица | Описание |
|---------|----------|
| `osm_stations` | Станции из OSM: `osm_id`, `name`, `railway`, `geom` |
| `planet_osm_nodes` | Все узлы OSM с тегами (hstore). Содержит `uic_ref` — код станции РЖД |
| `planet_osm_point` | Точки OSM (аэропорты, остановки и т.д.) |
| `planet_osm_line`, `planet_osm_polygon`, `planet_osm_roads` | Линии, полигоны, дороги |
| `city_areas` | Городские зоны |

### Создаются скриптом загрузки

| Таблица | Описание |
|---------|----------|
| `rzd_stations` | Станции РЖД: `uic_code` (PK), `node_id`, `name`, `lat`, `lon`. Заполняется из `planet_osm_nodes` по тегу `uic_ref` |
| `train_directions` | Направления: `from_code`, `to_code` (коды UIC), `duration_min`, `price_rub`. Заполняется из Excel |

---

## Как работает поиск

При старте бэкенд загружает **весь граф** поездных направлений в память (14 774 узла, 32 174 ребра после ETL).
Поиск маршрутов выполняется **алгоритмом Дейкстры** с ограничением на число пересадок.

1. Пользователь вводит координаты точки **А** (откуда) и точки **Б** (куда).
2. Бэкенд находит **10 ближайших станций РЖД** с маршрутами к каждой точке.
3. Для каждой стартовой станции запускается **Дейкстра** по графу `train_directions` (макс. 3 ж/д плеча = до 2 пересадок).
4. К каждому маршруту добавляются **пешие плечи** (от точки А до станции отправления и от станции прибытия до точки Б).
5. На каждую пересадку добавляется штраф **30 мин** ожидания.
6. Маршруты сортируются по времени или стоимости, возвращаются **до 10 лучших**.

Параметры алгоритма:
- Ближайших станций: **10** к каждой точке
- Макс. пересадок: **2** (до 3 ж/д плеч)
- Скорость пешком: **5 км/ч**
- Штраф пересадки: **30 мин**

---

## Запуск

### 1. Поднять все сервисы

```bash
cd /root/t_trip
docker compose up -d --build
```

> Для разработки с монтированием кода: `cp docker-compose.override.yml.example docker-compose.override.yml`

Это запустит:
- **db** — PostgreSQL + PostGIS (внутренний порт 5432, **закрыт** снаружи для безопасности)
- **backend** — FastAPI (порт 8000)
- **frontend** — Streamlit (порт 8501)

> **Безопасность:** порт 5432 закрыт наружу, чтобы предотвратить атаки ботов-вымогателей.
> Для подключения через DBeaver используйте **SSH-туннель** (localhost:5432 → сервер:5432).

### 2. Загрузить данные из Excel в БД (один раз)

```bash
docker compose --profile load run --rm loader
```

Скрипт:
- Создаёт таблицы `rzd_stations` и `train_directions`.
- Из `planet_osm_nodes` берёт российские станции по `uic_ref`.
- Из `data/trains_directions.xlsx` загружает время и цену.

### 3. Открыть приложение

Streamlit: **http://<IP-сервера>:8501**

FastAPI (Swagger): **http://<IP-сервера>:8000/docs**

---

## Управление контейнерами

### Статус всех сервисов

```bash
docker compose ps
```

### Логи

```bash
# Логи конкретного сервиса
docker compose logs backend
docker compose logs frontend
docker compose logs db

# Последние 50 строк
docker compose logs backend --tail 50

# В реальном времени (follow)
docker compose logs -f backend

# Все сервисы сразу
docker compose logs -f
```

### Перезапуск

```bash
# Перезапустить один сервис
docker compose restart backend
docker compose restart frontend

# Пересобрать и перезапустить (после изменения кода)
docker compose up -d --build backend

# Перезапустить всё
docker compose down && docker compose up -d
```

### Остановить

```bash
# Остановить всё (контейнеры сохраняются)
docker compose stop

# Остановить и удалить контейнеры (данные в pgdata сохраняются)
docker compose down
```

---

## Подключение к БД через DBeaver (SSH-туннель)

Порт 5432 закрыт снаружи — прямое подключение из интернета невозможно. Используйте SSH-туннель.

### Настройка в DBeaver

1. **Создайте новое подключение** → PostgreSQL
2. Вкладка **SSH**:
   - Включите `Use SSH Tunnel`
   - **Host**: IP-адрес вашего сервера
   - **Port**: 22
   - **User**: ваш SSH-пользователь (например, `root`)
   - **Authentication**: ключ (`Private Key`) или пароль
3. Вкладка **Main**:
   - **Host**: `localhost`
   - **Port**: `5432`
   - **Database**: `train`
   - **Username**: `postgres`
   - **Password**: см. `POSTGRES_PASSWORD` в `docker-compose.yml`

---

## Восстановление дампа БД

Если нужно заново залить дамп OSM/PostGIS:

```bash
chmod +x scripts/restore-dump.sh
./scripts/restore-dump.sh /path/to/train1.dump
```

Скрипт копирует дамп в контейнер и запускает `pg_restore` внутри.
После восстановления нужно заново запустить загрузку направлений:

```bash
docker compose --profile load run --rm loader
```

---

## Обогащение Excel координатами

Добавляет к каждой строке `trains_directions.xlsx` колонки `origin_latitude`, `origin_longitude`, `destination_latitude`, `destination_longitude`:

```bash
docker compose --profile load run --rm loader \
  sh -c "pip install -q pandas openpyxl psycopg2-binary && python scripts/enrich_excel_with_coords.py"
```

Результат: `data/trains_directions_with_coords.xlsx` и `.csv`.

---

## API

### POST /search

Поиск маршрутов по координатам.

**Запрос:**

```json
{
  "from_lat": 55.7558,
  "from_lon": 37.6173,
  "to_lat": 59.9343,
  "to_lon": 30.3351,
  "optimize_by": "time"
}
```

**Ответ:** содержит ближайшие станции и маршруты с детализацией по плечам (legs):

```json
{
  "from_point": {"lat": 55.7558, "lon": 37.6173},
  "to_point": {"lat": 59.9343, "lon": 30.3351},
  "nearest_from": [{"uic_code": "2006004", "name": "Москва-Пассажирская", "distance_m": 1500}],
  "nearest_to": [{"uic_code": "2004001", "name": "Санкт-Петербург-Главный", "distance_m": 800}],
  "optimize_by": "time",
  "routes": [
    {
      "id": 1,
      "total_duration_min": 405,
      "total_price_rub": 8500.00,
      "transfers": 0,
      "legs": [
        {"type": "walk", "from_name": "Точка А", "to_name": "Москва-Пассажирская", "duration_min": 45, "price_rub": 0, "distance_m": 3320},
        {"type": "train", "from_name": "Москва-Пассажирская", "to_name": "Санкт-Петербург-Главный", "duration_min": 360, "price_rub": 8500},
        {"type": "walk", "from_name": "Санкт-Петербург-Главный", "to_name": "Точка Б", "duration_min": 21, "price_rub": 0, "distance_m": 1741}
      ]
    }
  ]
}
```

---

## Технологии

| Компонент | Технология |
|-----------|-----------|
| БД | PostgreSQL 16 + PostGIS 3.4 |
| Бэкенд | Python 3.12, FastAPI, SQLAlchemy (async), asyncpg |
| Фронтенд | Streamlit |
| Контейнеризация | Docker Compose |
| Данные | OpenStreetMap (дамп), РЖД (Excel) |
