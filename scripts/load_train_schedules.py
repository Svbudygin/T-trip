#!/usr/bin/env python3
"""
Загрузка расписания поездов из CSV в таблицу train_schedules.
Не трогает существующую train_directions — создаёт отдельную таблицу.

CSV: data/24421993_13#table-01.csv
Поля: origin_station_id, destination_station_id, train_no,
      departure_dttm, arrival_tm, ride_min,
      regularity_type_code, regularity_desc, avg_price

Запуск через Docker:
  docker compose --profile load-schedules run --rm schedule-loader
Или вручную:
  python scripts/load_train_schedules.py
"""
import os
import csv

import psycopg2
from psycopg2.extras import execute_values

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
CSV_PATH = os.path.join(ROOT, "data", "24421993_13#table-01.csv")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
DB_NAME = os.getenv("DB_NAME", "train")


def get_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT,
        user=DB_USER, password=DB_PASSWORD, dbname=DB_NAME,
    )


def create_table(conn):
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS train_schedules CASCADE")
        cur.execute("""
            CREATE TABLE train_schedules (
                id                SERIAL PRIMARY KEY,
                from_code         VARCHAR(20) NOT NULL,
                to_code           VARCHAR(20) NOT NULL,
                train_no          VARCHAR(20) NOT NULL,
                departure_time    TIME NOT NULL,
                arrival_time      TIME NOT NULL,
                ride_min          INTEGER NOT NULL,
                regularity_type   VARCHAR(20) NOT NULL,
                regularity_desc   TEXT,
                avg_price         NUMERIC(12, 2) NOT NULL,
                UNIQUE (from_code, to_code, train_no)
            );
            CREATE INDEX idx_schedules_from ON train_schedules (from_code);
            CREATE INDEX idx_schedules_to   ON train_schedules (to_code);
        """)
    conn.commit()
    print("Таблица train_schedules создана.")


def load_known_stations(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT uic_code FROM rzd_stations")
        return {r[0] for r in cur.fetchall()}


def parse_time(val: str) -> str | None:
    """'20:38:00' -> '20:38:00', best-effort."""
    val = val.strip()
    if not val:
        return None
    parts = val.split(":")
    if len(parts) < 2:
        return None
    return val


def load_csv(conn):
    if not os.path.exists(CSV_PATH):
        print(f"CSV не найден: {CSV_PATH}")
        return 0

    known = load_known_stations(conn)
    print(f"Известных станций в rzd_stations: {len(known)}")

    batch = []
    skipped = 0
    skipped_station = 0
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            from_code = row["origin_station_id"].strip()
            to_code = row["destination_station_id"].strip()

            if from_code not in known or to_code not in known:
                skipped_station += 1
                continue

            dep_time = parse_time(row["departure_dttm"])
            arr_time = parse_time(row["arrival_tm"])
            if not dep_time or not arr_time:
                skipped += 1
                continue

            try:
                ride_min = int(row["ride_min"])
                price = round(float(row["avg_price"]), 2)
            except (ValueError, TypeError):
                skipped += 1
                continue

            train_no = row["train_no"].strip()
            reg_type = row["regularity_type_code"].strip()
            reg_desc = row["regularity_desc"].strip()

            batch.append((
                from_code, to_code, train_no,
                dep_time, arr_time, ride_min,
                reg_type, reg_desc, price,
            ))

    if batch:
        with conn.cursor() as cur:
            execute_values(
                cur,
                """INSERT INTO train_schedules
                       (from_code, to_code, train_no,
                        departure_time, arrival_time, ride_min,
                        regularity_type, regularity_desc, avg_price)
                   VALUES %s
                   ON CONFLICT (from_code, to_code, train_no) DO UPDATE SET
                       departure_time  = EXCLUDED.departure_time,
                       arrival_time    = EXCLUDED.arrival_time,
                       ride_min        = EXCLUDED.ride_min,
                       regularity_type = EXCLUDED.regularity_type,
                       regularity_desc = EXCLUDED.regularity_desc,
                       avg_price       = EXCLUDED.avg_price
                """,
                batch,
                page_size=2000,
            )
        conn.commit()

    print(f"Загружено: {len(batch)} рейсов")
    print(f"Пропущено (станция не в БД): {skipped_station}")
    print(f"Пропущено (прочие ошибки): {skipped}")
    return len(batch)


def main():
    print("Подключение к БД...")
    conn = get_conn()
    try:
        create_table(conn)
        load_csv(conn)
    finally:
        conn.close()
    print("Готово!")


if __name__ == "__main__":
    main()
