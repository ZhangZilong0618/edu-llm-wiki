"""Tests for citation filtering and renumbering in chat responses."""

from routes import chat


def test_citations_are_renumbered_to_returned_page_order():
    cited = [{"path": f"p{index}.md"} for index in range(1, 9)]
    response = "A [7] B [1] C [2][8] <!-- cited: 1,2,7,8 -->"

    cleaned, actual_cited = chat._filter_actual_citations(response, cited)

    assert cleaned == "A [1] B [2] C [3][4]"
    assert [page["path"] for page in actual_cited] == [
        "p7.md",
        "p1.md",
        "p2.md",
        "p8.md",
    ]


def test_hidden_only_citation_is_returned_and_renumbered():
    cited = [{"path": "one.md"}, {"path": "two.md"}]
    response = "Answer without visible markers <!-- cited: 2 -->"

    cleaned, actual_cited = chat._filter_actual_citations(response, cited)

    assert cleaned == "Answer without visible markers"
    assert [page["path"] for page in actual_cited] == ["two.md"]


def test_no_citation_returns_empty_page_list():
    cleaned, actual_cited = chat._filter_actual_citations("No citations", [{"path": "one.md"}])

    assert cleaned == "No citations"
    assert actual_cited == []


def test_out_of_range_citation_is_ignored():
    cited = [{"path": "one.md"}, {"path": "two.md"}]
    response = "Answer [9]"

    cleaned, actual_cited = chat._filter_actual_citations(response, cited)

    assert cleaned == "Answer [9]"
    assert actual_cited == []
