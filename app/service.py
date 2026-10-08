import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Outbox, OutboxStatus, Payment, PaymentStatus
from app.schemas import PaymentCreateRequest


class PaymentService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_payment_by_id(self, payment_id: uuid.UUID) -> Payment | None:
        stmt = select(Payment).where(Payment.id == payment_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_payment_by_idempotency_key(self, idempotency_key: str) -> Payment | None:
        stmt = select(Payment).where(Payment.idempotency_key == idempotency_key)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_payment_with_outbox(
        self,
        payload: PaymentCreateRequest,
        idempotency_key: str,
    ) -> tuple[Payment, bool]:
        """
        Логика:
        1. Проверка идемпотентности.
        2. Атомарное сохранение Payment и Outbox события в единой транзакции.
        
        Возвращает:
        tuple(Payment, created_new), где:
            Payment сам объект,
            created_new указывает, был создан новый платеж или возвращен дубликат по ключу идемпотентности
        """
        existing_payment = await self.get_payment_by_idempotency_key(idempotency_key)
        if existing_payment:
            return existing_payment, False

        payment = Payment(
            id=uuid.uuid4(),
            amount=payload.amount,
            currency=payload.currency,
            description=payload.description,
            metadata_info=payload.metadata,
            status=PaymentStatus.PENDING,
            idempotency_key=idempotency_key,
            webhook_url=str(payload.webhook_url),
        )

        outbox_event = Outbox(
            id=uuid.uuid4(),
            event_type="payment.created",
            payload={
                "payment_id": str(payment.id),
                "amount": float(payment.amount),
                "currency": payment.currency,
                "webhook_url": payment.webhook_url,
            },
            status=OutboxStatus.PENDING,
        )

        self.db.add(payment)
        self.db.add(outbox_event)
        await self.db.commit()
        await self.db.refresh(payment)

        return payment, True

    async def update_status(self, payment_id: uuid.UUID, new_status: PaymentStatus) -> None:
        stmt = (
            update(Payment)
            .where(Payment.id == payment_id)
            .values(status=new_status)
        )
        await self.db.execute(stmt)
        await self.db.commit()