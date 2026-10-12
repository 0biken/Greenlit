"""Choices shared by several apps (DATA §3)."""

from django.db import models


class Priority(models.TextChoices):
    """Requirement and case priority; also defect severity (same four words)."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ReviewState(models.TextChoices):
    """Objects AI can draft carry this. Only accepted rows count anywhere (DATA §3)."""

    DRAFT = "draft"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class Origin(models.TextChoices):
    HUMAN = "human"
    AI = "ai"
