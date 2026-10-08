import asyncio
import logging

from faststream.rabbit import RabbitBroker
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Outbox, OutboxStatus

logger = logging.getLogger("outbox_publisher")


async def run_outbox_publisher() -> None:
    broker = RabbitBroker(settings.rabbitmq_url)
    await broker.connect()
    logger.info("Outbox publisher подключился к RabbitMQ")

    try:
        while True:
            try:
                async with AsyncSessionLocal() as session:
                    stmt = (
                        select(Outbox)
                        .where(Outbox.status == OutboxStatus.PENDING)
                        .order_by(Outbox.created_at.asc())
                        .limit(50)
                    )
                    result = await session.execute(stmt)
                    events = result.scalars().all()

                    for event in events:
                        try:
                            await broker.publish(
                                message=event.payload,
                                queue="payments.new",
                            )
                            event.status = OutboxStatus.PROCESSED
                        except Exception as pub_err:
                            logger.error(f"Ошибка публикации события {event.id}: {pub_err}")
                            event.status = OutboxStatus.FAILED

                    await session.commit()
            except Exception as e:
                logger.error(f"Ошибка во время цикла Outbox Relay: {e}")

            await asyncio.sleep(1.0)
    finally:
        await broker.close()
