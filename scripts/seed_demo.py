# Idempotent demo seed — run via:  uv run manage.py shell < scripts/seed_demo.py
# Creates/ensures the demo account, workspace, agent, end user, wallet credits,
# and a FRESH API key (prints it as SEED_API_KEY=... for dev-up.sh to capture).
from decimal import Decimal

from django.utils import timezone

from apps.accounts.models import User
from apps.agents.models import Agent
from apps.agents.models.agent import ModelTier
from apps.api_keys.models import APIKey
from apps.api_keys.scopes import APIKeyScopes
from apps.billing.models import BillingHold, CreditWallet, HoldStatus
from apps.end_users.models import ControlProfile, EndUser
from apps.runs.models.run import Run, RunStatus
from apps.workspaces.models import Workspace, WorkspaceMember
from apps.workspaces.models.member import WorkspaceRole

EMAIL = "demo@midsphere.local"
PASSWORD = "demo12345"

# 1. account (verified, active, known password)
user, _ = User.objects.get_or_create(email=EMAIL, defaults={"full_name": "Demo Owner"})
user.set_password(PASSWORD)
user.is_active = True
if user.email_verified_at is None:
    user.email_verified_at = timezone.now()
user.save()

# 2. workspace + admin membership
ws, _ = Workspace.objects.get_or_create(
    slug="demo", defaults={"name": "Demo", "owner": user, "billing_email": EMAIL}
)
WorkspaceMember.objects.get_or_create(
    workspace=ws,
    user=user,
    defaults={"role": WorkspaceRole.ADMIN, "joined_at": timezone.now()},
)

# 3. agent
Agent.objects.get_or_create(
    workspace=ws,
    name="demo-agent",
    defaults={
        "description": "Demo agent for the SDK notebooks.",
        "system_prompt": "You are Sukuna, a helpful agent. Be concise.",
        "default_model_tier": ModelTier.FREE,
        "is_active": True,
    },
)

# 4. end user + per-user controls
eu, _ = EndUser.objects.get_or_create(
    workspace=ws,
    external_user_id="demo-user",
    defaults={"display_name": "Demo User", "tier_label": "pro"},
)
ControlProfile.objects.update_or_create(
    end_user=eu,
    defaults={
        "credits": 1000,
        "model_tier": "pro",
        "concurrency_max": 10,
        "credit_grant_per_period": 1000,
    },
)

# 5. wallet credits + clear any orphaned holds/runs from prior sessions
wallet, _ = CreditWallet.objects.get_or_create(workspace=ws)
for hold in BillingHold.objects.filter(wallet=wallet, status=HoldStatus.ACTIVE):
    hold.release()
Run.objects.filter(
    workspace=ws, status__in=(RunStatus.QUEUED, RunStatus.RUNNING)
).update(status=RunStatus.CANCELLED)
if wallet.available() < Decimal("100"):
    wallet.record_dodo_credit_grant(
        Decimal("1000.00"), dodo_payment_id=f"seed-{timezone.now().timestamp()}"
    )

# 6. a fresh API key (replace any prior demo-sdk key so the notebook always has a valid one)
APIKey.objects.filter(workspace=ws, name="demo-sdk").delete()
_, secret = APIKey.create_for_workspace(
    ws, name="demo-sdk", scopes=sorted(APIKeyScopes().values), created_by=user
)

print(f"SEED_API_KEY={secret}")
print(f"SEED_LOGIN={EMAIL} / {PASSWORD}")
