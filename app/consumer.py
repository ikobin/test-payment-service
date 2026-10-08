import asyncio
import logging
import random
import uuid

import httpx
from faststream import FastStream
from faststream.rabbit import ExchangeType, RabbitBroker, RabbitExchange, RabbitQueue

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import PaymentStatus
from app.service import PaymentService

logger = logging.getLogger("payment_consumer")

broker = RabbitBroker(settings.rabbitmq_url)
app = FastStream(broker)

# Dead Letter Queue настройка
dlx = RabbitExchange("payments.dlx", type=ExchangeType.DIRECT)
dlq = RabbitQueue("payments.dlq", routing_key="payments.dead")

main_queue = RabbitQueue(
    "payments.new",
    arguments={
        "x-dead-letter-exchange": "payments.dlx",
        "x-dead-letter-routing-key": "payments.dead",
    },
)


async def send_webhook_with_retry(
    webhook_url: str,
    payload: dict,
    max_retries: int = 3,
) -> bool:
    async with httpx.AsyncClient(timeout=5.0) as client:
        for attempt in range(1, max_retries + 1):
            try:
                response = await client.post(webhook_url, json=payload)
                if response.is_success:
                    logger.info(f"Webhook успешно доставлен на {webhook_url} (Попытка {attempt})")
                    return True
                logger.warning(f"Webhook {webhook_url} ответил со кодом {response.status_code}")
            except Exception as e:
                logger.warning(f"Ошибка при вызове webhook {webhook_url}: {e}")

            if attempt < max_retries:
                await asyncio.sleep(2**attempt)

    return False


@broker.subscriber(main_queue)
async def process_payment_event(data: dict):
    payment_id = uuid.UUID(data["payment_id"])
    webhook_url = data["webhook_url"]

    logger.info(f"Начало обработки платежа {payment_id}")

    await asyncio.sleep(random.uniform(2.0, 5.0))
    is_success = random.random() < 0.90
    final_status = PaymentStatus.SUCCEEDED if is_success else PaymentStatus.FAILED

    async with AsyncSessionLocal() as session:
        service = PaymentService(session)
        await service.update_status(payment_id, final_status)

    logger.info(f"Статус платежа {payment_id} установлен в: {final_status.value}")

    webhook_payload = {
        "payment_id": str(payment_id),
        "status": final_status.value,
        "amount": data.get("amount"),
        "currency": data.get("currency"),
    }

    webhook_ok = await send_webhook_with_retry(
        webhook_url=webhook_url,
        payload=webhook_payload,
        max_retries=3,
    )

    if not webhook_ok:
        logger.error(f"Не удалось доставить webhook для платежа {payment_id}. Перенаправление в DLQ.")
        raise RuntimeError(f"Webhook delivery failed for {payment_id}")


@broker.subscriber(dlq, exchange=dlx)
async def handle_dead_letter_queue(data: dict):
    logger.critical(f"[DLQ] Сообщение попало в Dead Letter Queue: {data}")
