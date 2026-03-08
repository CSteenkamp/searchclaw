"""Celery app configuration."""

from celery import Celery

from api.config import get_settings

settings = get_settings()

celery_app = Celery(
    "searchclaw",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    worker_concurrency=3,
    task_time_limit=120,
    task_soft_time_limit=110,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=3600,
    task_track_started=True,
)

celery_app.autodiscover_tasks(["api.workers"])
