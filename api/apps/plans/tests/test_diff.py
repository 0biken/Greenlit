"""Steps are compared as an ordered list (M3-06; DATA "Versioning", "Diff")."""

from apps.plans.diff import diff_steps


def ops(old, new):
    return [(row["op"], row["text"], row["before"], row["after"]) for row in diff_steps(old, new)]


def test_identical_steps_are_all_the_same():
    assert ops(["a", "b"], ["a", "b"]) == [("same", "a", 1, 1), ("same", "b", 2, 2)]


def test_a_reordered_step_shows_as_moved_not_deleted_and_added():
    assert ops(["a", "b", "c"], ["c", "a", "b"]) == [
        ("moved", "c", 3, 1),
        ("same", "a", 1, 2),
        ("same", "b", 2, 3),
    ]


def test_added_and_removed_steps_sit_where_they_belong():
    assert ops(["a", "b", "c"], ["a", "x", "c"]) == [
        ("same", "a", 1, 1),
        ("removed", "b", 2, None),
        ("added", "x", None, 2),
        ("same", "c", 3, 3),
    ]


def test_a_reworded_step_is_a_removal_and_an_addition():
    assert ops(["Pay"], ["Pay by card"]) == [
        ("removed", "Pay", 1, None),
        ("added", "Pay by card", None, 1),
    ]


def test_a_repeated_step_is_matched_once():
    assert [o for o, *_ in ops(["a", "a"], ["a"])] == ["same", "removed"]
