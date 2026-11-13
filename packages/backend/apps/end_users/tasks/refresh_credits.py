from __future__ import annotations

import structlog
from celery import shared_task
from django.utils import timezone

from apps.end_users.models import EndUser

logger = structlog.get_logger()


@shared_task
def refresh_due_credits() -> int:
    qs = EndUser.objects.filter(
        profile__next_credit_refresh_at__lte=timezone.now(),
    ).select_related("profile")
    count = 0
    for end_user in qs.iterator(chunk_size=200):
        end_user.refresh_credits()
        count += 1
    logger.info("credit_refresh_completed", refreshed=count)
    return count
