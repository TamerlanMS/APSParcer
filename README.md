# APS Parser — Система обработки спецификаций

## Архитектура

```
┌─────────────────┐        HTTPS          ┌──────────────────────────┐
│  APSParser.exe  │ ──────────────────▶  │  FastAPI + Docker        │
│  (PyQt6 клиент) │  X-API-Key header    │  ┌────────────────────┐  │
│                 │ ◀────────────────── │  │    PostgreSQL       │  │
│  • Загрузка PDF │     JSON ответ       │  │  - products        │  │
│  • Предпросмотр │                      │  │  - brand_constants │  │
│  • БД менеджмент│                      │  │  - currency_rates  │  │
└─────────────────┘                      │  └────────────────────┘  │
                                         └──────────────────────────┘
```

## Структура проекта

```
aps_project/
├── docker-compose.yml
├── server/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py
│       ├── api/          — роутеры (pdf, database, auth)
│       ├── core/         — config, database, security
│       ├── models/       — SQLAlchemy модели
│       └── services/     — pdf_parser, matcher, db_importer
└── client/
    ├── main.py
    ├── requirements.txt
    ├── aps_parser.spec   — сборка .exe
    ├── assets/style.qss
    ├── services/         — api_service, config, excel_generator
    └── ui/
        ├── main_window.py
        ├── pages/        — upload, preview, database
        └── dialogs/      — auth_dialog
```

---

## Сервер — запуск

### 1. Настройка пароля администратора

```bash
python3 -c "import bcrypt; print(bcrypt.hashpw(b'ВАШ_ПАРОЛЬ', bcrypt.gensalt()).decode())"
```

Скопируйте хэш в `docker-compose.yml` → `ADMIN_PASSWORD_HASH`.

### 2. Запуск Docker

```bash
cd aps_project
docker-compose up -d --build
```

Сервер доступен на `http://SERVER_IP:8000`  
Документация API: `http://SERVER_IP:8000/docs` (только в DEBUG режиме)

### 3. Первичная загрузка БД

После запуска загрузите базу данных через клиент (вкладка «База данных»)  
или через curl:

```bash
curl -X POST "http://SERVER_IP:8000/api/v1/database/import/products?password=ВАШ_ПАРОЛЬ" \
  -H "X-API-Key: APS-K1-X7mN2pQrL9vW4bYcJ6sT8uE3fH5kZ" \
  -F "file=@database.xlsx"
```

---

## Клиент — сборка .exe

```bash
cd aps_project/client
pip install -r requirements.txt
pyinstaller aps_parser.spec
# Результат: dist/APSParser.exe
```

### Первый запуск

При первом запуске появится окно авторизации:
- **Адрес сервера:** `http://SERVER_IP:8000`
- **API ключ:** один из 10 ключей ниже

---

## API ключи (10 штук)

Выдавайте каждому сотруднику отдельный ключ:

| № | Ключ                                     |
|---|------------------------------------------|
| 1 | `APS-K1-X7mN2pQrL9vW4bYcJ6sT8uE3fH5kZ` 1 |
| 2 | `APS-K2-R4nD8wA1mK7vP3xB9yU6tF2hG5jQ0` 1 |
| 3 | `APS-K3-V9cL5eN2rM8wT4zK1pX7yB3sF6dH0` 1 |
| 4 | `APS-K4-Q2jH8mR5tW7nL4cX1bY9vP6kD3sE0` 1 |
| 5 | `APS-K5-B6wF1pK9eL3rN8mH5xQ2yV7tJ4cU0` 1 |
| 6 | `APS-K6-T3sY7vM2kB8nR5wL1eH9xP4jQ6fD0` 1 |
| 7 | `APS-K7-N5eP2bL8wK4rH7mQ1xT9yJ3vF6cS0`   |
| 8 | `APS-K8-H8kQ3mN6tB1rL9eW5xV2yP4jD7sF0`   |
| 9 | `APS-K9-L1xB7eW4mK2rN9pH6tQ8yV3jF5cD0`   |
| 10 | `APS-K10-P4yN9vL7bK3wH2mR8xQ5eT1jF6sD0`  |

Чтобы отозвать ключ — удалите его из `settings.API_KEYS` в `config.py` и перезапустите сервер.

---

## Цвета в предпросмотре

| Цвет | Значение |
|------|----------|
| 🟢 Зелёный | Точное совпадение в БД |
| 🟡 Жёлтый | Несколько вариантов или нечёткое совпадение — требует подтверждения |
| 🔴 Красный | Позиция не найдена в БД |
| 🔵 Синий | Ячейка отредактирована вручную |

При двойном клике на жёлтой строке откроется список вариантов для выбора.

---

## Обновление БД без перезапуска

Просто загрузите новый Excel через вкладку «База данных» в клиенте.  
Существующие артикулы обновятся, новые — добавятся.

---

## CRUD API (для интеграций)

```
GET    /api/v1/database/products          — список товаров
PATCH  /api/v1/database/products/{id}    — обновить товар
DELETE /api/v1/database/products/{id}    — деактивировать товар
GET    /api/v1/database/constants        — константы брендов
PATCH  /api/v1/database/constants/{brand} — обновить константы
POST   /api/v1/database/import/products  — импорт из Excel
POST   /api/v1/database/import/constants — импорт констант
GET    /api/v1/database/logs             — история импортов
POST   /api/v1/pdf/parse                 — обработать PDF
```

Все запросы требуют заголовок `X-API-Key: <ключ>`.
