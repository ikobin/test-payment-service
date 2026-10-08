import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.payments import router as payments_router
from app.outbox import run_outbox_publisher


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(run_outbox_publisher())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)
app.include_router(payments_router)
