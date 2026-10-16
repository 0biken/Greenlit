"""Request shapes shared by every screen that reviews AI drafts (requirements, cases)."""

from rest_framework import serializers

from apps.ai.drafts import ACCEPT_ALL_MAX
from apps.ai.models import Decision, RejectReason


class ReviewSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=Decision.choices)
    reason = serializers.ChoiceField(
        choices=RejectReason.choices, required=False, allow_blank=True, default=""
    )
    viewed_ms = serializers.IntegerField(
        min_value=0, required=False, help_text="How long the draft was on screen before deciding"
    )


class AcceptManySerializer(serializers.Serializer):
    numbers = serializers.ListField(
        child=serializers.IntegerField(min_value=1), min_length=1, max_length=ACCEPT_ALL_MAX
    )
    viewed_ms = serializers.IntegerField(min_value=0, required=False)
