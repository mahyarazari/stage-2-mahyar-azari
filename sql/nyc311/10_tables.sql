-- Tables of the nyc311 schema (stage 2).
-- Run by the load stage inside its transaction, with search_path set to the target
-- schema; names are therefore unqualified. Each load rebuilds cases and quarantine, so a
-- changed definition here always takes effect; CASCADE also drops dependent views, which
-- the after_load files recreate. load_runs is a log and is never dropped.

DROP TABLE IF EXISTS cases CASCADE;
CREATE TABLE cases (
    unique_key             bigint           PRIMARY KEY,   -- digits only (contract INVALID_KEY)
    created_at             timestamp        NOT NULL,      -- local New York time, no zone in the source
    closed_at              timestamp,                      -- NULL = still open at as_of (D24)
    is_open                boolean          NOT NULL,
    days_to_close          double precision,
    created_month          date             NOT NULL,      -- first day of the month of created_at (D16)
    agency                 text             NOT NULL,
    complaint_type         text             NOT NULL,
    descriptor             text,
    incident_address       text,
    incident_zip           text,
    borough                text,
    community_board        text,
    latitude               double precision,
    longitude              double precision,
    open_data_channel_type text,
    flag_zero_duration     boolean          NOT NULL,
    flag_created_midnight  boolean          NOT NULL,
    flag_status_conflict   boolean          NOT NULL,
    flag_coords_invalid    boolean          NOT NULL,
    duplicate_group_id     text             NOT NULL,
    is_duplicate           boolean          NOT NULL,
    join_zip               text,
    modzcta                text,
    population             integer,
    population_status      text             NOT NULL,
    borough_source         text,
    borough_check          text             NOT NULL,

    CONSTRAINT cases_open_has_no_close CHECK (
        (is_open AND closed_at IS NULL AND days_to_close IS NULL)
        OR (NOT is_open AND closed_at IS NOT NULL AND days_to_close IS NOT NULL)),
    CONSTRAINT cases_closed_after_created CHECK (closed_at >= created_at),
    CONSTRAINT cases_days_not_negative CHECK (days_to_close >= 0),
    CONSTRAINT cases_month_matches_created CHECK (created_month = date_trunc('month', created_at)::date),
    CONSTRAINT cases_borough_known CHECK (
        borough IN ('BRONX', 'BROOKLYN', 'MANHATTAN', 'QUEENS', 'STATEN ISLAND')),
    CONSTRAINT cases_zip_five_digits CHECK (incident_zip ~ '^[0-9]{5}$'),
    CONSTRAINT cases_coordinates_valid CHECK (latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180),
    CONSTRAINT cases_population_positive CHECK (population > 0),
    CONSTRAINT cases_population_status_known CHECK (
        population_status IN ('matched', 'zip_missing', 'zip_not_in_reference', 'no_population')),
    CONSTRAINT cases_borough_source_known CHECK (borough_source IN ('311', 'zip')),
    CONSTRAINT cases_borough_check_known CHECK (
        borough_check IN ('consistent', 'inconsistent', 'not_checkable'))
);

DROP TABLE IF EXISTS quarantine CASCADE;
CREATE TABLE quarantine (
    -- raw text exactly as received: a quarantined value may not fit any stricter type
    unique_key                     text,
    created_date                   text,
    closed_date                    text,
    status                         text,
    agency                         text,
    complaint_type                 text,
    descriptor                     text,
    incident_zip                   text,
    incident_address               text,
    borough                        text,
    community_board                text,
    latitude                       text,
    longitude                      text,
    open_data_channel_type         text,
    resolution_action_updated_date text,
    reason_codes                   text[] NOT NULL CHECK (cardinality(reason_codes) > 0)
);

CREATE TABLE IF NOT EXISTS load_runs (
    load_id        text        PRIMARY KEY,   -- run_id of the run manifest
    loaded_at_utc  timestamp   NOT NULL,
    snapshot       text        NOT NULL,
    config_sha256  text        NOT NULL CHECK (config_sha256 ~ '^[0-9a-f]{64}$'),
    git_commit     text        NOT NULL,
    files          jsonb       NOT NULL       -- per table: file, sha256, rows
);
