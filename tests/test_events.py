from datetime import date

from warehouse.events import rows_from_submissions


def test_keeps_trouble_forms_with_8k_items():
    block = {
        "accessionNumber": ["a1", "a2", "a3", "a4"],
        "form": ["8-K", "4", "NT 10-K", "10-K/A"],
        "filingDate": ["2020-03-02", "2020-03-03", "2020-03-31", "2020-06-01"],
        "items": ["4.01,9.01", "", "", ""],
    }
    rows = rows_from_submissions(7, [block])
    assert rows == [
        (7, "a1", "8-K", date(2020, 3, 2), "4.01,9.01"),
        (7, "a3", "NT 10-K", date(2020, 3, 31), None),
        (7, "a4", "10-K/A", date(2020, 6, 1), None),
    ]
