-- Пересоздание таблиц (удаляем старые версии)
DROP TABLE IF EXISTS train_directions CASCADE;
DROP TABLE IF EXISTS rzd_stations CASCADE;
DROP TABLE IF EXISTS rzd_to_osm CASCADE;

-- Таблица станций РЖД (из planet_osm_nodes по uic_ref)
CREATE TABLE rzd_stations (
    uic_code VARCHAR(20) PRIMARY KEY,
    node_id  BIGINT NOT NULL,
    name     TEXT,
    lat      DOUBLE PRECISION,
    lon      DOUBLE PRECISION
);
CREATE INDEX idx_rzd_stations_latlon ON rzd_stations (lat, lon);

-- Направления: время и цена из Excel
CREATE TABLE train_directions (
    from_code VARCHAR(20) NOT NULL,
    to_code   VARCHAR(20) NOT NULL,
    duration_min INTEGER NOT NULL,
    price_rub NUMERIC(12, 2) NOT NULL,
    PRIMARY KEY (from_code, to_code)
);
CREATE INDEX idx_train_directions_from ON train_directions (from_code);
CREATE INDEX idx_train_directions_to ON train_directions (to_code);
