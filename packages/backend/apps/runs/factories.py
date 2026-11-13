from __future__ import annotations

import os
import uuid
from datetime import timedelta
from decimal import Decimal

import factory
from django.utils import timezone

from apps.agents.factories import AgentFactory
from apps.end_users.factories import EndUserFactory
from apps.runs.models import (
    Artifact,
    ArtifactKind,
    Conversation,
    Rating,
    Run,
    RunEvent,
    RunManifestRecord,
    SandboxInstance,
    SandboxState,
)
from apps.runs.schemas.events import RunStatus
from apps.workspaces.factories import WorkspaceFactory


class RunFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Run

    workspace = factory.SubFactory(WorkspaceFactory)
    agent = factory.LazyAttribute(lambda o: AgentFactory(workspace=o.workspace))
    end_user = factory.LazyAttribute(lambda o: EndUserFactory(workspace=o.workspace))
    run_uid = factory.LazyFunction(uuid.uuid4)
    prompt = factory.Faker("sentence")
    status = RunStatus.QUEUED

    class Params:
        running = factory.Trait(
            status=RunStatus.RUNNING,
            started_at=factory.LazyFunction(timezone.now),
        )
        finished = factory.Trait(
            status=RunStatus.FINISHED,
            started_at=factory.LazyFunction(timezone.now),
            finished_at=factory.LazyFunction(timezone.now),
            total_cost_usd=Decimal("0.05"),
            total_tokens=1500,
        )
        failed = factory.Trait(
            status=RunStatus.FAILED,
            started_at=factory.LazyFunction(timezone.now),
            finished_at=factory.LazyFunction(timezone.now),
            error_message="Tool execution failed",
        )
        cancelled = factory.Trait(
            status=RunStatus.CANCELLED,
            started_at=factory.LazyFunction(timezone.now),
            finished_at=factory.LazyFunction(timezone.now),
        )
        scheduled = factory.Trait(is_scheduled=True)


class RunEventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = RunEvent

    run = factory.SubFactory(RunFactory, running=True)
    sequence_no = factory.Sequence(lambda n: n + 1)
    event_type = "run_usage"
    payload = factory.LazyFunction(lambda: {"type": "run_usage", "total_tokens": 0})


class ArtifactFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Artifact

    run = factory.SubFactory(RunFactory, finished=True)
    name = factory.Sequence(lambda n: f"artifact-{n}.txt")
    kind = ArtifactKind.DOCUMENT
    mime_type = "text/plain"
    size_bytes = 256


class RatingFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Rating

    run = factory.SubFactory(RunFactory, finished=True)
    score = 4
    comment = ""


class ConversationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Conversation

    workspace = factory.SubFactory(WorkspaceFactory)
    agent = factory.LazyAttribute(lambda o: AgentFactory(workspace=o.workspace))
    end_user = factory.LazyAttribute(lambda o: EndUserFactory(workspace=o.workspace))
    title = factory.Faker("sentence", nb_words=4)


class SandboxInstanceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SandboxInstance

    sandbox_id = factory.LazyFunction(lambda: f"sbx-{uuid.uuid4().hex[:12]}")
    workspace = factory.SubFactory(WorkspaceFactory)
    agent = factory.LazyAttribute(lambda o: AgentFactory(workspace=o.workspace))
    sandbox_state = SandboxState.SPAWNING

    class Params:
        booting = factory.Trait(
            sandbox_state=SandboxState.BOOTING,
            boot_started_at=factory.LazyFunction(timezone.now),
        )
        running = factory.Trait(
            sandbox_state=SandboxState.RUNNING,
            boot_started_at=factory.LazyFunction(timezone.now),
            boot_completed_at=factory.LazyFunction(timezone.now),
        )
        paused = factory.Trait(
            sandbox_state=SandboxState.PAUSED,
            boot_started_at=factory.LazyFunction(timezone.now),
            boot_completed_at=factory.LazyFunction(timezone.now),
            last_run_finished_at=factory.LazyFunction(timezone.now),
            pause_count=1,
        )
        terminated = factory.Trait(
            sandbox_state=SandboxState.TERMINATED,
        )


def _make_encrypted_callback_auth() -> bytes:
    from cryptography.fernet import Fernet  # noqa: PLC0415

    from config.runtime import runtime  # noqa: PLC0415

    raw_key = os.urandom(32)
    f = Fernet(runtime.fernet_encryption_key.encode())
    return f.encrypt(raw_key)


class RunManifestRecordFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = RunManifestRecord

    run = factory.SubFactory(RunFactory, running=True)
    sandbox_id = factory.LazyFunction(lambda: f"sbx-{uuid.uuid4().hex[:12]}")
    signing_key_id = "test-key-001"
    manifest_hash = factory.LazyFunction(
        lambda: RunManifestRecord.compute_manifest_hash(uuid.uuid4().bytes),
    )
    callback_auth_encrypted = factory.LazyFunction(_make_encrypted_callback_auth)
    schema_version = 1
    expires_at = factory.LazyFunction(
        lambda: timezone.now() + timedelta(seconds=300),
    )
