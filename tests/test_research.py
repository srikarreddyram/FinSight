"""Company research: the Risk Factors comparison, officer titles, and the time machine's month table."""

from research.changes import compare, is_heading, paragraphs, word_diff
from research.timeline import _name, _title


def test_paragraphs_drop_page_furniture_and_fragments():
    text = "Table of Contents\nRisks related to our business\n• Our results could suffer if demand for our products falls sharply.\n12\n"
    assert paragraphs(text) == ["Our results could suffer if demand for our products falls sharply."]


def test_compare_marks_same_changed_new_and_removed():
    old = [
        "Competition in our industry is intense and could reduce our market share and margins.",
        "Our results depend on consumer demand in the markets where we sell our products today.",
        "We rely on a small number of contract manufacturers located mainly in Vietnam.",
    ]
    new = [
        "Competition in our industry is intense and could reduce our market share and margins.",
        "Our results depend on consumer demand in the markets where we sell our products and services.",
        "Our use of artificial intelligence may expose us to new legal and reputational risks.",
    ]
    out = compare(old, new)
    assert [b["status"] for b in out["blocks"]] == ["same", "changed", "new"]
    assert out["summary"] == {"same": 1, "changed": 1, "new": 1, "removed": 1}
    assert out["removed"][0]["text"].startswith("We rely on a small number")
    assert ["+", "and services."] in out["blocks"][1]["segments"] and ["-", "today."] in out["blocks"][1]["segments"]


def test_word_diff_and_headings():
    assert word_diff("a b c d", "a x c d") == [["=", "a"], ["-", "b"], ["+", "x"], ["=", "c d"]]
    assert is_heading("Global economic conditions could have a material adverse effect on our business.")
    assert not is_heading("Short line.") and not is_heading(
        "One sentence here is fine. But two sentences are body text, not a heading."
    )


def test_insider_names_and_titles():
    assert _name("Montagne Amy") == "Amy Montagne" and _name(None) == "Insider"
    assert _title("EVP: CHIEF LEGAL OFFICER") == "EVP: Chief Legal Officer" and _title("President and CEO") == "President and CEO"
