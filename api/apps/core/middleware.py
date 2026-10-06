"""Organisation scope for every request (M1-04, DATA §8 rule 2, SEC §4 checks 1 and 2).

The whole request runs in one transaction, and the database scope is set inside it with
`set_config(..., true)`, so it ends with the request. (Django's ATOMIC_REQUESTS wraps only the
view, after middleware, so it cannot be used for this.)

1. Who are you?  A signed-in user. Anonymous requests get no scope at all.
2. Which organisation?  The `X-Org` header names an organisation by slug. The user must have an
   active membership in it, or the answer is "not found", the same answer as for an
   organisation that does not exist, so nothing leaks about other tenants.
"""

import logging
from collections.abc import Callable

from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse

from apps.core.models import MembershipStatus
from apps.core.tenancy import get_scope, restore_scope, set_scope

ORG_HEADER = "X-Org"
security_log = logging.getLogger("greenlit.security")

NOT_FOUND = {"detail": "Not found."}


class TenancyMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request.org = None  # type: ignore[attr-defined]
        request.membership = None  # type: ignore[attr-defined]

        with transaction.atomic():
            previous = get_scope()
            response = self._respond(request)
            # Only on a normal return: if the request failed, the transaction rolls back and
            # Postgres reverts the local settings with it.
            restore_scope(previous)
            return response

    def _respond(self, request: HttpRequest) -> HttpResponse:
        user = request.user
        if not user.is_authenticated:
            set_scope(None, None)
            return self.get_response(request)

        # Memberships and organisations are readable by their own user before an organisation
        # is chosen (see the policies in migration 0003).
        set_scope(None, user.pk)

        slug = request.headers.get(ORG_HEADER, "").strip()
        if slug:
            found = self._membership_for(user.pk, slug)
            if found is None:
                # Possible probing: log IDs only, never the requested value.
                security_log.warning("org lookup refused", extra={"user_id": str(user.pk)})
                return JsonResponse(NOT_FOUND, status=404)
            request.org, request.membership = found  # type: ignore[attr-defined]
            set_scope(request.org.pk, user.pk)  # type: ignore[attr-defined]

        return self.get_response(request)

    @staticmethod
    def _membership_for(user_id, slug: str):
        from apps.core.models import Membership, Organisation

        org = Organisation.objects.filter(slug=slug).first()
        if org is None:
            return None
        membership = Membership.objects.filter(
            org_id=org.pk, user_id=user_id, status=MembershipStatus.ACTIVE
        ).first()
        if membership is None:
            return None
        return org, membership
