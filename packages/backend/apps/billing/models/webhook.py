from __future__ import annotations

from typing import Any, ClassVar

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.billing.schemas import WebhookProviders
from apps.core.exceptions import Conflict
from apps.core.models import TimestampedModel


class WebhookDelivery(TimestampedModel):
    """Generic webhook dedup table — keyed by ``(provider, event_id)``.

    Inserted at the edge of every webhook receiver. The ``UNIQUE`` constraint
    collapses replays into a single ``IntegrityError`` the receiver can
    short-circuit on. Phase 4 (Dodo) writes here; the sandbox metering
    receiver in the blocked-on-sandbox-refactor section uses the same table.
    """

    provider = models.CharField(max_length=32)
    event_id = models.CharField(max_length=128)
    received_at = models.DateTimeField(default=timezone.now, db_index=True)
    processed_at = models.DateTimeField(blank=True, null=True)
    payload_hash = models.CharField(max_length=128, blank=True, default="")
    history = HistoricalRecords()

    class Meta:
        db_table = "billing_webhookdelivery"
        ordering = ("-created_at",)
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("provider", "event_id"),
                name="unique_webhook_delivery_event",
            ),
            models.CheckConstraint(
                condition=models.Q(provider__in=tuple(sorted(WebhookProviders().values))),
                name="webhookdelivery_provider_valid",
            ),
            models.CheckConstraint(
                condition=~models.Q(event_id=""),
                name="webhookdelivery_event_id_non_empty",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("provider", "created_at")),
            models.Index(fields=("processed_at",)),
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.event_id}"

    def clean(self) -> None:
        super().clean()
        errors = self._validation_errors()
        if errors:
            raise ValidationError(errors)

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean(validate_unique=False, validate_constraints=False)
        super().save(*args, **kwargs)

    @transaction.atomic
    def mark_processed(self) -> None:
        delivery = type(self).objects.select_for_update().get(pk=self.pk)
        if delivery.processed_at is not None:
            raise Conflict("Webhook delivery already processed.")
        delivery.processed_at = timezone.now()
        delivery.save(update_fields=("processed_at", "updated_at"))
        self.processed_at = delivery.processed_at

    def _validation_errors(self) -> dict[str, str]:
        errors = {}
        if self.provider not in WebhookProviders().values:
            errors["provider"] = f"Unknown provider: {self.provider}"
        if not self.event_id.strip():
            errors["event_id"] = "Webhook deliveries require a non-empty event ID."
        return errors
