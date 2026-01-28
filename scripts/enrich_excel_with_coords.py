#!/usr/bin/env python3
"""
Берёт trains_directions.xlsx, добавляет координаты станций из БД (rzd_stations)
и сохраняет в trains_directions_with_coords.xlsx.

Новые столбцы:
  origin_lat, origin_lon   — широта/долгота станции отправления
  dest_lat, dest_lon       — широта/долгота станции назначения

Запуск через Docker:
  docker compose --profile load run --rm loader python scripts/enrich_excel_with_coords.py
"""
import os
import sys

import psycopg2

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
EXCEL_IN = os.path.join(ROOT, "data", "trains_directions.xlsx")
EXCEL_OUT = os.path.join(ROOT, "data", "trains_directions_with_coords.xlsx")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
DB_NAME = os.getenv("DB_NAME", "train")


def main():
    try:
        import pandas as pd
    except ImportError:
        print("pip install pandas openpyxl")
        sys.exit(1)

    if not os.path.exists(EXCEL_IN):
        print(f"Не найден: {EXCEL_IN}")
        sys.exit(1)

    # Читаем Excel
    df = pd.read_excel(EXCEL_IN)
    print(f"Прочитано {len(df)} строк из {EXCEL_IN}")
    print(f"Столбцы: {list(df.columns)}")

    # Определяем столбцы с кодами станций
    col_origin = col_dest = None
    for c in df.columns:
        cl = str(c).lower().strip()
        if col_origin is None and "origin" in cl and ("code" in cl or "station" in cl):
            col_origin = c
        if col_dest is None and "destination" in cl and ("code" in cl or "station" in cl or "st" in cl):
            col_dest = c
    if col_origin is None:
        col_origin = df.columns[0]
    if col_dest is None:
        col_dest = df.columns[1]
    print(f"Столбец origin: {col_origin}, dest: {col_dest}")

    # Получаем координаты из БД
    conn = psycopg2.connect(host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD, dbname=DB_NAME)
    with conn.cursor() as cur:
        cur.execute("SELECT uic_code, lat, lon FROM rzd_stations")
        coords = {str(r[0]): (r[1], r[2]) for r in cur.fetchall()}
    conn.close()
    print(f"Загружено {len(coords)} станций с координатами из rzd_stations")

    # Добавляем столбцы
    origin_lats = []
    origin_lons = []
    dest_lats = []
    dest_lons = []

    for _, row in df.iterrows():
        try:
            orig_code = str(int(float(row[col_origin]))) if pd.notna(row[col_origin]) else None
        except (ValueError, TypeError):
            orig_code = None
        try:
            dest_code = str(int(float(row[col_dest]))) if pd.notna(row[col_dest]) else None
        except (ValueError, TypeError):
            dest_code = None

        o = coords.get(orig_code) if orig_code else None
        d = coords.get(dest_code) if dest_code else None

        origin_lats.append(o[0] if o else None)
        origin_lons.append(o[1] if o else None)
        dest_lats.append(d[0] if d else None)
        dest_lons.append(d[1] if d else None)

    df["origin_latitude"] = origin_lats
    df["origin_longitude"] = origin_lons
    df["destination_latitude"] = dest_lats
    df["destination_longitude"] = dest_lons

    filled_origin = sum(1 for v in origin_lats if v is not None)
    filled_dest = sum(1 for v in dest_lats if v is not None)
    print(f"Координаты найдены: origin {filled_origin}/{len(df)}, destination {filled_dest}/{len(df)}")

    df.to_excel(EXCEL_OUT, index=False, engine="openpyxl")
    print(f"Сохранено: {EXCEL_OUT}")

    # Дополнительно CSV (откроется где угодно)
    csv_out = EXCEL_OUT.replace(".xlsx", ".csv")
    df.to_csv(csv_out, index=False, sep=";", encoding="utf-8-sig")
    print(f"Также сохранено CSV: {csv_out}")


if __name__ == "__main__":
    main()
