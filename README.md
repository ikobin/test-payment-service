# Test Payment Service

Асинхронный сервис процессинга платежей: принимает запросы на оплату, обрабатывает
их через эмуляцию внешнего платёжного шлюза и уведомляет клиента о результате
через webhook.

Реализован на **FastAPI** + **SQLAlchemy 2.0 (async)** + **FastStream (RabbitMQ)**.
Обеспечивает гарантированную доставку событий через **Outbox pattern**,
**идемпотентность** создания платежа и **Dead Letter Queue** для сообщений,
не обработанных после retry.

---

## Содержание

- [Архитектура](#архитектура)
- [Стек](#стек)
- [Структура проекта](#структура-проекта)
- [Быстрый старт](#быстрый-старт)
- [Переменные окружения](#переменные-окружения)
- [API](#api)
- [Как это работает](#как-это-работает)

---

## Архитектура

```
┌──────────┐   POST /payments   ┌──────────────┐
│  Client  │ ─────────────────► │   FastAPI    │
│          │ ◄───────────────── │   (api)      │
└──────────┘   202 + payment_id └──────┬───────┘
     ▲                                 │
     │                                 │ 1 транзакция:
     │                                 │   INSERT payment
     │                                 │   INSERT outbox
     │                                 ▼
     │                          ┌──────────────┐
     │                          │  PostgreSQL  │
     │                          └──────┬───────┘
     │                                 │
     │                                 │ 2. outbox-publisher
     │                                 │    читает outbox
     │                                 ▼
     │                          ┌──────────────┐
     │                          │  RabbitMQ    │
     │                          │  payments.new│
     │                          └──────┬───────┘
     │                                 │ 3. consumer
     │                                 ▼
     │                          ┌──────────────┐
     │                          │  Consumer    │
     │                          │  - 2-5 сек   │
     │                          │  - 90% ok    │
     │                          │  - 3 retry   │
     │                          └──────┬───────┘
     │                                 │
     │     4. webhook (POST)           │
     └─────────────────────────────────┘
                                       │ 5. если webhook не доставлен
                                       ▼
                                ┌──────────────┐
                                │ payments.dlq │
                                └──────────────┘
```

**Компоненты:**

| Компонент | Роль |
|---|---|
| `api` | HTTP-приём платежей, отдача статуса. Запускает outbox-publisher в фоне через `lifespan`. |
| `consumer` | FastStream-воркер: читает `payments.new`, эмулирует обработку, обновляет статус, шлёт webhook, ретраит, роутит в DLQ. |
| `db` | PostgreSQL 15. Таблицы `payments`, `outbox`. |
| `rabbitmq` | Очереди `payments.new`, `payments.dlq`; exchange `payments.dlx`. |

---

## Стек

- **Python** 3.11
- **FastAPI** — HTTP-фреймворк
- **Pydantic v2** — валидация схем
- **SQLAlchemy 2.0** (async) + **asyncpg** — ORM
- **Alembic** — миграции
- **FastStream** — обёртка над RabbitMQ
- **PostgreSQL** 15
- **RabbitMQ** 3
- **Docker** + **docker compose**
- **httpx** — отправка webhook'ов

---

## Структура проекта

```
.
├── alembic/
│   ├── versions/
│   │   └── 52c27c825df8_initial_tables_creation.py
│   ├── env.py
│   ├── script.py.mako
│   └── README
├── alembic.ini
├── app/
│   ├── __init__.py
│   ├── main.py                # FastAPI + lifespan (outbox publisher)
│   ├── config.py              # Settings (pydantic-settings)
│   ├── database.py            # engine, AsyncSessionLocal, get_db
│   ├── models.py              # Payment, Outbox, enums
│   ├── schemas.py             # Pydantic-схемы
│   ├── service.py             # PaymentService
│   ├── auth.py                # verify_api_key
│   ├── consumer.py            # FastStream app
│   ├── outbox.py              # run_outbox_publisher()
│   └── api/
│       ├── __init__.py
│       └── v1/
│           ├── __init__.py
│           └── payments.py    # роутер
├── .dockerignore
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

---

## Быстрый старт

### Требования

- Docker Desktop (или Docker + Docker Compose v2)
- Свободные порты: `8000`, `5432`

### Запуск

```bash
git clone <repo-url>
cd test-payment-service
docker compose up --build
```

Первый запуск занимает 1–3 минуты (сборка образов + миграции). Дальше — секунды.

Проверь, что всё поднялось:

```bash
docker compose ps
```

Ожидаемо 4 сервиса:

```
NAME                                STATUS
test-payment-service-api-1          Up
test-payment-service-consumer-1     Up
test-payment-service-db-1           Up (healthy)
test-payment-service-rabbitmq-1     Up (healthy)
```

### Доступные сервисы

| Что | URL |
|---|---|
| Swagger UI | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |
| PostgreSQL | `localhost:5432` (`postgres` / `postgres_password`) |

### Остановка

```bash
docker compose down          # остановить, данные сохранить
docker compose down -v       # остановить И удалить БД + очереди
```

---

## Переменные окружения

Все переменные имеют дефолты в `app/config.py`. Переопределяются через env
(в compose уже прокинуты):

| Переменная | Дефолт | Описание |
|---|---|---|
| `POSTGRES_USER` | `postgres` | Пользователь БД |
| `POSTGRES_PASSWORD` | `postgres_password` | Пароль БД |
| `POSTGRES_DB` | `payments_db` | Имя БД |
| `POSTGRES_HOST` | `db` | Хост БД |
| `POSTGRES_PORT` | `5432` | Порт БД |
| `RABBITMQ_HOST` | `rabbitmq` | Хост RabbitMQ |
| `RABBITMQ_PORT` | `5672` | Порт AMQP |
| `RABBITMQ_USER` | `guest` | Пользователь RabbitMQ |
| `RABBITMQ_PASSWORD` | `guest` | Пароль RabbitMQ |
| `API_KEY` | `secret-static-api-key-12345` | Ключ для заголовка `X-API-Key` |

---

## API

Все эндпоинты требуют заголовок `X-API-Key`.

### Создание платежа

```http
POST /api/v1/payments
```

**Headers:**

```
X-API-Key: secret-static-api-key-12345
Idempotency-Key: <уникальный ключ>
Content-Type: application/json
```

**Body:**

```json
{
  "amount": 100.50,
  "currency": "USD",
  "description": "Test payment",
  "metadata": {"order_id": "42", "user": "alice"},
  "webhook_url": "https://webhook.site/your-unique-id"
}
```

| Поле | Тип | Ограничения |
|---|---|---|
| `amount` | decimal | > 0, до 10 знаков, 2 после запятой |
| `currency` | string | `RUB`, `USD`, `EUR` |
| `description` | string \| null | до 255 символов |
| `metadata` | object \| null | произвольный JSON |
| `webhook_url` | string | валидный URL, не loopback / не private IP |

**Response `202 Accepted`:**

```json
{
  "payment_id": "16d2e781-a1aa-44cd-a220-1179c93f7b45",
  "status": "pending",
  "created_at": "2026-10-08T18:02:19.915Z"
}
```

**Ошибки:**

| Код | Причина |
|---|---|
| `401` / `403` | отсутствует или неверный `X-API-Key` |
| `422` | отсутствует `Idempotency-Key`, невалидные поля, SSRF-URL |

### Получение платежа

```http
GET /api/v1/payments/{payment_id}
```

**Response `200 OK`:**

```json
{
  "id": "16d2e781-a1aa-44cd-a220-1179c93f7b45",
  "amount": 100.50,
  "currency": "USD",
  "description": "Test payment",
  "metadata": {"order_id": "42"},
  "status": "succeeded",
  "webhook_url": "https://webhook.site/your-unique-id",
  "created_at": "2026-10-08T18:02:19.915Z",
  "updated_at": "2026-10-08T18:02:22.123Z"
}
```

**Ошибки:** `404` если платёж не найден.

---

## Как это работает

### Идемпотентность

Заголовок `Idempotency-Key` обязателен. При повторном POST с тем же ключом
возвращается **тот же** платёж — новая запись в БД не создаётся. Это
защищает от случайных дублей при ретраях на стороне клиента.

Реализация: колонка `payments.idempotency_key` с `UNIQUE`-констрейнтом;
сервис проверяет наличие платежа до вставки.

### Outbox pattern

При создании платежа в **одной транзакции** записываются:

1. Запись в `payments` (статус `pending`).
2. Запись в `outbox` (событие `payment.created`, статус `pending`).

Транзакция коммитится атомарно. Гарантия: **если платёж сохранён, событие
тоже сохранено**. Публикация в RabbitMQ — отдельный процесс
(`run_outbox_publisher`), который читает `outbox` со статусом `pending`
и публикует их в очередь `payments.new`. После публикации запись помечается
`processed`.

Это гарантирует, что событие не потеряется, даже если RabbitMQ был
временно недоступен в момент создания платежа.

Outbox-publisher запускается через `lifespan` FastAPI — живёт в контейнере `api`.

### Обработка платежа (consumer)

Consumer читает `payments.new`, для каждого сообщения:

1. Ждёт 2–5 секунд (эмуляция обработки).
2. С вероятностью 90% ставит `succeeded`, с 10% — `failed`.
3. Обновляет статус в БД.
4. Отправляет webhook на `webhook_url`.

`failed` — это **бизнес-результат** (платёжный шлюз отклонил платёж),
а не техническая ошибка. Такие платежи **не уходят в DLQ** — webhook с
`status: failed` доставляется как обычно.

### Retry и DLQ

Webhook отправляется **до 3 раз** с экспоненциальной задержкой:

| Попытка | Пауза перед попыткой |
|---|---|
| 1 | — |
| 2 | 2 сек |
| 3 | 4 сек |

Если все 3 попытки провалились — consumer бросает исключение. FastStream
нак'ает сообщение (без `requeue`), RabbitMQ через аргументы очереди
`payments.new` (`x-dead-letter-exchange: payments.dlx`,
`x-dead-letter-routing-key: payments.dead`) отправляет его в `payments.dlx`
→ `payments.dlq`. DLQ-хендлер логирует сообщение как `CRITICAL`.

### SSRF-защита

Поле `webhook_url` проверяется Pydantic-валидатором: URL не должен вести
на loopback (`127.0.0.1`, `::1`), private (`10/8`, `172.16/12`,
`192.168/16`) или link-local (`169.254/16`, включая AWS metadata
`169.254.169.254`) адреса.

---