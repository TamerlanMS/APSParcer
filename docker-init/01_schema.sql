-- ─────────────────────────────────────────────────────────────────────────────
-- Schema bootstrap для APS Parser
-- Postgres автоматически выполняет любой *.sql из /docker-entrypoint-initdb.d/
-- при первом старте контейнера (когда volume postgres_data ещё пустой).
-- ─────────────────────────────────────────────────────────────────────────────

-- Товары: основная БД оборудования
CREATE TABLE IF NOT EXISTS products (
    id              SERIAL PRIMARY KEY,
    num             INTEGER,
    article         VARCHAR(200),
    name            TEXT,
    unit            VARCHAR(50),
    kaznisa         DOUBLE PRECISION,
    rrts            DOUBLE PRECISION,
    mrc             DOUBLE PRECISION,
    opt             DOUBLE PRECISION,
    partner         DOUBLE PRECISION,
    brand           VARCHAR(100),
    multiplicity    INTEGER,
    kaznisa_code    VARCHAR(100),
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_products_article ON products (article);
CREATE INDEX IF NOT EXISTS ix_products_brand   ON products (brand);

-- Константы по брендам
CREATE TABLE IF NOT EXISTS brand_constants (
    id              SERIAL PRIMARY KEY,
    brand           VARCHAR(100) UNIQUE,
    margin          DOUBLE PRECISION DEFAULT 1.2,
    logistics       DOUBLE PRECISION DEFAULT 1.03,
    rate            DOUBLE PRECISION DEFAULT 4.0,
    currency_rate   DOUBLE PRECISION DEFAULT 1.0,
    nds             DOUBLE PRECISION DEFAULT 1.16,
    gp              DOUBLE PRECISION DEFAULT 0.8,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_brand_constants_brand ON brand_constants (brand);

-- Курсы валют
CREATE TABLE IF NOT EXISTS currency_rates (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(50) UNIQUE,
    rate        DOUBLE PRECISION DEFAULT 1.0,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Лог импортов
CREATE TABLE IF NOT EXISTS import_logs (
    id              SERIAL PRIMARY KEY,
    filename        VARCHAR(300),
    rows_added      INTEGER DEFAULT 0,
    rows_updated    INTEGER DEFAULT 0,
    status          VARCHAR(50) DEFAULT 'success',
    message         TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Менеджеры (для dropdown в окне сохранения КП)
CREATE TABLE IF NOT EXISTS managers (
    id          SERIAL PRIMARY KEY,
    full_name   VARCHAR(200) UNIQUE,
    position    VARCHAR(200),
    email       VARCHAR(200),
    phone       VARCHAR(100),
    is_active   BOOLEAN DEFAULT TRUE,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_managers_full_name ON managers (full_name);
