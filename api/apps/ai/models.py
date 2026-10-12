from django.db import models

from apps.core.models import TenantModel


class CallOutcome(models.TextChoices):
    OK = "ok"
    REUSED = "reused"  # unchanged input: the stored reply was returned, the provider not called
    BAD_OUTPUT = "bad_output"  # the reply failed its schema twice
    UNAVAILABLE = "unavailable"  # the provider could not be reached


class AiCall(TenantModel):
    """One call to the model provider (spec gap G-05, AI §8): what it cost and what came back.

    `reply` is kept so that running a feature again on unchanged input returns the stored
    result instead of paying for it twice. `source_id` and `job_id` are plain IDs: this table
    is written by every AI feature and must not depend on any of them."""

    feature = models.CharField(max_length=40)
    model = models.CharField(max_length=80)
    prompt_version = models.CharField(max_length=20)
    input_hash = models.CharField(max_length=64)
    outcome = models.CharField(max_length=12, choices=CallOutcome.choices)
    tokens_in = models.PositiveIntegerField(default=0)
    tokens_out = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    duration_ms = models.PositiveIntegerField(default=0)
    reply = models.JSONField(null=True, blank=True)
    gaps = models.JSONField(default=list, blank=True)
    source_id = models.UUIDField(null=True, blank=True)
    job_id = models.UUIDField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["org_id", "feature", "input_hash"]),
            models.Index(fields=["org_id", "created_at"]),
        ]


class AiDroppedItem(TenantModel):
    """A draft the checks refused (AI §2, §4). Kept for quality review; never shown as a record."""

    call = models.ForeignKey(AiCall, on_delete=models.PROTECT, related_name="dropped")
    reason = models.CharField(max_length=40)
    item = models.JSONField()


class Decision(models.TextChoices):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class RejectReason(models.TextChoices):
    WRONG = "wrong"
    DUPLICATE = "duplicate"
    TOO_VAGUE = "too_vague"
    NOT_TESTABLE = "not_testable"


class AiDraft(TenantModel):
    """What the AI said about one drafted record, and what a person then decided (spec gap
    G-06, AI §6, §9). One table for every kind of record AI can draft; the record itself (a
    requirement, a case revision, a defect) carries `origin` and `review_state`."""

    target_type = models.CharField(max_length=20)
    target_id = models.UUIDField()
    call = models.ForeignKey(AiCall, null=True, on_delete=models.PROTECT, related_name="drafts")
    # vague (bool), possible_duplicate_of (display ID), assumptions (list of strings)
    flags = models.JSONField(default=dict, blank=True)
    decision = models.CharField(max_length=10, choices=Decision.choices, blank=True)
    reject_reason = models.CharField(max_length=20, choices=RejectReason.choices, blank=True)
    decided_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    # Accepted in under 2 seconds: counted and shown to the QA lead (AI §6 "Over-trust").
    fast_accept = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["target_type", "target_id"], name="one_ai_draft_per_record"
            )
        ]
