"""Per-project display IDs (M1-13, DATA §4)."""

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import connection

from apps.core.models import CounterKind, Organisation, Project
from apps.core.numbering import format_display_id, next_number, parse_display_id
from apps.core.tenancy import org_scope


def make_org_with_projects(*keys: str):
    org_id = uuid.uuid4()
    with org_scope(org_id):
        org = Organisation.objects.create(id=org_id, name="Num", slug=f"num-{org_id.hex[:8]}")
        projects = [Project.objects.create(org_id=org.id, name=k, key=k) for k in keys]
    return org, projects


@pytest.mark.django_db
def test_numbers_count_up_from_one_per_project_and_kind():
    org, (hube, other) = make_org_with_projects("HUBE", "OTHR")
    with org_scope(org.id):
        bugs = [next_number(hube.id, org.id, CounterKind.DEFECT) for _ in range(3)]
        reqs = [next_number(hube.id, org.id, CounterKind.REQUIREMENT) for _ in range(2)]
        other_bugs = [next_number(other.id, org.id, CounterKind.DEFECT) for _ in range(2)]
    assert bugs == [1, 2, 3]
    assert reqs == [1, 2]
    assert other_bugs == [1, 2]


@pytest.mark.django_db
def test_a_rolled_back_insert_does_not_burn_a_number():
    org, (project,) = make_org_with_projects("ROLL")
    with org_scope(org.id):
        first = next_number(project.id, org.id, CounterKind.DEFECT)
        try:
            with org_scope(org.id):
                assert next_number(project.id, org.id, CounterKind.DEFECT) == first + 1
                raise RuntimeError("the insert failed")
        except RuntimeError:
            pass
        assert next_number(project.id, org.id, CounterKind.DEFECT) == first + 1


@pytest.mark.django_db(transaction=True)
def test_fifty_concurrent_inserts_get_fifty_unique_gap_free_numbers():
    org, (project,) = make_org_with_projects("RACE")

    def take() -> int:
        try:
            with org_scope(org.id):
                return next_number(project.id, org.id, CounterKind.DEFECT)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=10) as pool:
        numbers = list(pool.map(lambda _: take(), range(50)))
    assert sorted(numbers) == list(range(1, 51))


@pytest.mark.parametrize(
    "kind,number,expected",
    [
        (CounterKind.REQUIREMENT, 102, "REQ-102"),
        (CounterKind.TEST_PLAN, 3, "TP-3"),
        (CounterKind.TEST_CASE, 42, "TC-0042"),
        (CounterKind.TEST_RUN, 19, "RUN-019"),
        (CounterKind.EVIDENCE, 310, "EV-0310"),
        (CounterKind.DEFECT, 1042, "BUG-1042"),
        (CounterKind.REPORT, 8, "RPT-008"),
        (CounterKind.TEST_CASE, 12345, "TC-12345"),
    ],
)
def test_formats_match_the_examples_in_the_spec(kind, number, expected):
    assert format_display_id(kind, number) == expected


def test_the_project_key_prefixes_ids_shown_outside_their_project():
    assert format_display_id(CounterKind.DEFECT, 1042, "hube") == "HUBE-BUG-1042"


@pytest.mark.parametrize(
    "text,key,kind,number",
    [
        ("BUG-1042", None, CounterKind.DEFECT, 1042),
        ("HUBE-BUG-1042", "HUBE", CounterKind.DEFECT, 1042),
        ("hube-bug-1042", "HUBE", CounterKind.DEFECT, 1042),
        ("  TC-0042 ", None, CounterKind.TEST_CASE, 42),
        ("RUN-019", None, CounterKind.TEST_RUN, 19),
    ],
)
def test_parse_reads_what_people_type(text, key, kind, number):
    assert parse_display_id(text) == (key, kind, number)


@pytest.mark.parametrize(
    "text", ["", "BUG", "BUG-", "BUG-x", "XYZ-1", "1042", "A-BUG-1", "BUG-1-2"]
)
def test_parse_rejects_things_that_are_not_ids(text):
    assert parse_display_id(text) is None


def test_format_then_parse_round_trips():
    for kind in CounterKind:
        text = format_display_id(kind, 57, "HUBE")
        assert parse_display_id(text) == ("HUBE", kind, 57)
