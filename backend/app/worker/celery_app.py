from celery import Celery
from celery.schedules import crontab

from app.core.config import settings
from app.core.encryption import get_data_cipher

get_data_cipher()

celery_app = Celery(
    "noki",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.worker.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=None,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    task_soft_time_limit=270,
    task_time_limit=300,
    worker_max_tasks_per_child=100,
    worker_max_memory_per_child=512_000,
    result_expires=3600,
    broker_transport_options={"visibility_timeout": 3600},
    task_send_sent_event=True,
    worker_send_task_events=True,
    task_routes={
        "noki.send_mail": {"queue": settings.mail_queue},
    },
    beat_schedule={
        "cleanup-orphans-every-six-hours": {
            "task": "noki.cleanup_orphans",
            "schedule": crontab(minute=0, hour="*/6"),
        },
        "cleanup-avatar-orphans-daily": {
            "task": "noki.cleanup_avatar_orphans",
            "schedule": crontab(minute=35, hour=2),
        },
    },
)
