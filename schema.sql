CREATE TABLE IF NOT EXISTS server_metrics (
    ts              BIGINT      PRIMARY KEY,
    cpu_used        REAL,
    ram_used        REAL,
    disk_used       REAL,
    cpu_temp        REAL,
    pwr_used        REAL,
    net_up          REAL,
    net_dn          REAL,
);