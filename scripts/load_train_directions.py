#!/usr/bin/env python3
"""
Загрузка направлений РЖД из Excel в БД.
1. Создаёт таблицы rzd_stations и train_directions (если нет).
2. Из planet_osm_nodes берёт uic_ref -> id (точный матч по коду РЖД).
3. Из trains_directions.xlsx берёт время и цену, записывает в train_directions.

Запуск через Docker:
  docker compose --profile load run --rm loader
"""
import os
import sys

import psycopg2
from psycopg2.extras import execute_values

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
EXCEL_PATH = os.path.join(ROOT, "data", "trains_directions.xlsx")
TRAIN_ROUTES_CSV = os.path.join(ROOT, "data", "train_routes.csv")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
DB_NAME = os.getenv("DB_NAME", "train")


def get_conn():
    return psycopg2.connect(host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD, dbname=DB_NAME)


def create_tables(conn):
    with conn.cursor() as cur:
        # Удаляем старые версии таблиц (со старой схемой from_osm_id и т.д.)
        cur.execute("DROP TABLE IF EXISTS train_directions CASCADE")
        cur.execute("DROP TABLE IF EXISTS rzd_stations CASCADE")
        cur.execute("DROP TABLE IF EXISTS rzd_to_osm CASCADE")
        cur.execute("""
            CREATE TABLE rzd_stations (
                uic_code VARCHAR(20) PRIMARY KEY,
                node_id  BIGINT NOT NULL,
                name     TEXT,
                lat      DOUBLE PRECISION,
                lon      DOUBLE PRECISION
            );
            CREATE INDEX idx_rzd_stations_latlon ON rzd_stations (lat, lon);
        """)
        cur.execute("""
            CREATE TABLE train_directions (
                from_code VARCHAR(20) NOT NULL,
                to_code   VARCHAR(20) NOT NULL,
                duration_min INTEGER NOT NULL,
                price_rub NUMERIC(12, 2) NOT NULL,
                PRIMARY KEY (from_code, to_code)
            );
            CREATE INDEX idx_train_directions_from ON train_directions (from_code);
            CREATE INDEX idx_train_directions_to ON train_directions (to_code);
        """)
    conn.commit()
    print("Таблицы rzd_stations и train_directions пересозданы (старые удалены).")


def load_rzd_stations(conn):
    """Заполняет rzd_stations из planet_osm_nodes по тегу uic_ref."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM rzd_stations")
        cur.execute("""
            INSERT INTO rzd_stations (uic_code, node_id, name, lat, lon)
            SELECT DISTINCT ON (tags -> 'uic_ref')
                tags -> 'uic_ref',
                id,
                tags -> 'name',
                lat::double precision / 10000000,
                lon::double precision / 10000000
            FROM planet_osm_nodes
            WHERE tags ? 'uic_ref'
              AND (tags -> 'uic_ref') LIKE '20%%'
            ORDER BY tags -> 'uic_ref', id
        """)
        count = cur.rowcount
    conn.commit()
    print(f"Загружено в rzd_stations: {count} станций (российские, uic_ref LIKE '20%%').")
    with conn.cursor() as cur:
        cur.execute("SELECT uic_code, name FROM rzd_stations LIMIT 5")
        for r in cur.fetchall():
            print(f"  Пример: {r[0]} — {r[1]}")
    return count


def load_directions_from_excel(conn):
    try:
        import pandas as pd
    except ImportError:
        print("Установите pandas и openpyxl: pip install pandas openpyxl")
        sys.exit(1)
    if not os.path.exists(EXCEL_PATH):
        print(f"Excel не найден: {EXCEL_PATH}")
        return 0
    df = pd.read_excel(EXCEL_PATH)
    print(f"Excel: {len(df)} строк, столбцы: {list(df.columns)}")
    # Определяем столбцы
    col_origin = col_dest = col_hours = col_price = None
    for c in df.columns:
        cl = str(c).lower().strip()
        if col_origin is None and "origin" in cl and ("code" in cl or "station" in cl):
            col_origin = c
        if col_dest is None and "destination" in cl and ("code" in cl or "station" in cl or "st" in cl):
            col_dest = c
        if col_hours is None and "duration" in cl and "hour" in cl:
            col_hours = c
        if col_price is None and cl == "price":
            col_price = c
        if col_price is None and "price" in cl:
            col_price = c
    # fallback
    if col_origin is None:
        col_origin = df.columns[0]
    if col_dest is None:
        col_dest = df.columns[1]
    if col_hours is None:
        for c in df.columns:
            if "hour" in str(c).lower() or "duration" in str(c).lower():
                col_hours = c
                break
    if col_price is None:
        for c in df.columns:
            if "price" in str(c).lower():
                col_price = c
                break
    print(f"  Используемые столбцы: origin={col_origin}, dest={col_dest}, hours={col_hours}, price={col_price}")
    # Получаем множество кодов, которые есть в rzd_stations
    with conn.cursor() as cur:
        cur.execute("SELECT uic_code FROM rzd_stations")
        known_codes = {r[0] for r in cur.fetchall()}
    print(f"  Известных кодов в rzd_stations: {len(known_codes)}")
    batch = []
    skipped = 0
    for _, row in df.iterrows():
        try:
            orig = str(int(float(row[col_origin]))) if pd.notna(row[col_origin]) else None
            dest = str(int(float(row[col_dest]))) if pd.notna(row[col_dest]) else None
        except (ValueError, TypeError):
            skipped += 1
            continue
        if not orig or not dest:
            skipped += 1
            continue
        if orig not in known_codes or dest not in known_codes:
            skipped += 1
            continue
        try:
            hours = float(row[col_hours])
            price_val = float(row[col_price])
        except (ValueError, TypeError):
            skipped += 1
            continue
        duration_min = max(1, int(round(hours * 60)))
        batch.append((orig, dest, duration_min, round(price_val, 2)))
    if batch:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM train_directions")
            execute_values(
                cur,
                """INSERT INTO train_directions (from_code, to_code, duration_min, price_rub)
                   VALUES %s
                   ON CONFLICT (from_code, to_code) DO UPDATE
                   SET duration_min = EXCLUDED.duration_min, price_rub = EXCLUDED.price_rub""",
                batch,
                page_size=2000,
            )
        conn.commit()
    print(f"Загружено в train_directions: {len(batch)} записей (пропущено: {skipped}).")
    return len(batch)


def main():
    print("Подключение к БД...")
    conn = get_conn()
    try:
        create_tables(conn)
        load_rzd_stations(conn)
        load_directions_from_excel(conn)
    finally:
        conn.close()
    print("Готово!")


if __name__ == "__main__":
    main()
