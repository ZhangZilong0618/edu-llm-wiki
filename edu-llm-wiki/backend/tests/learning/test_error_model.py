"""Misconception classification tests (Brown & Burton 1978)."""
from services.learning.error_model import classify_error, cluster_traces


def test_classify_blank():
    # empty response returns [] by current API contract; a non-empty
    # wrong response returns a list of misconception tags.
    assert classify_error("", "42") == []
    out = classify_error("foo bar", "42")
    assert isinstance(out, list)


def test_classify_wrong():
    tags = classify_error("foo", "bar")
    assert isinstance(tags, list)


def test_cluster_traces_counts():
    out = cluster_traces([("no_response", "..."), ("no_response", "..."), ("off_by_one", "1")])
    by_tag = {c["tag"]: c["count"] for c in out}
    assert by_tag["no_response"] == 2
    assert by_tag["off_by_one"] == 1
