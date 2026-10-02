from datetime import date

from warehouse.universe import Change, norm_name, reconstruct, ticker

CIKS = {"META": 1, "FB": 1, "GOOGL": 2, "GOOG": 2, "OLDCO": 3, "NEWCO": 4, "IR": 5}


def _resolve(tk, name, day, removal=False):
    if tk == "IR" and day < date(2020, 3, 1):
        return 6  # the ticker was reused: in 2010 it was a different company
    return CIKS.get(tk)


def test_walk_back_handles_renames_share_classes_reuse_and_rejoins():
    current = {"META": 1, "GOOGL": 2, "GOOG": 2, "NEWCO": 4, "IR": 5}
    changes = [
        Change(date(2020, 3, 2), "IR", "Ingersoll Rand", "OLDCO", "Old Co"),
        Change(date(2018, 1, 5), "NEWCO", "New Co", None, None),
        Change(date(2016, 1, 5), None, None, "NEWCO", "New Co"),  # New Co left in 2016 and rejoined in 2018
        Change(date(2014, 4, 3), "GOOG", "Alphabet C", None, None),  # second share class only
        Change(date(2013, 12, 23), "FB", "Facebook", None, None),  # now META
        Change(date(2012, 1, 1), None, None, "IR", "Ingersoll-Rand"),  # the old IR, CIK 6
        Change(date(2005, 1, 1), "OLDCO", "Old Co", None, None),  # before the history: ignored
    ]
    stays = {(s.cik, s.start, s.end) for s in reconstruct(current, changes, _resolve)}
    assert stays == {
        (1, date(2013, 12, 23), None),  # Meta joined as FB
        (2, None, None),  # Alphabet was a member throughout; adding GOOG didn't start a stay
        (4, date(2018, 1, 5), None), (4, None, date(2016, 1, 5)),
        (5, date(2020, 3, 2), None),  # today's IR
        (6, None, date(2012, 1, 1)),  # the old IR, left in 2012
        (3, None, date(2020, 3, 2)),
    }  # fmt: skip


def test_ticker_and_name_normalisation():
    assert ticker("BRK.B") == "BRK-B" and ticker("ALLE |") == "ALLE" and ticker(float("nan")) is None
    assert norm_name("Ingersoll-Rand plc") == norm_name("INGERSOLL-RAND PLC") == "ingersoll rand"
    assert norm_name("Michael Kors Holdings Ltd") == norm_name("Michael Kors") == "michael kors"
    assert norm_name("AT&T Inc.") == "at and t"
    assert norm_name("21st Century Fox") == norm_name("TWENTY-FIRST CENTURY FOX, INC.")
    assert norm_name("Twenty-First Century Fox Class B") == norm_name("TWENTY-FIRST CENTURY FOX, INC.")
    assert norm_name("Comcast Class K Special") == norm_name("Comcast Series K") == "comcast"
    assert norm_name("AETNA INC /PA/") == norm_name("DUN & BRADSTREET CORP/NW").replace("dun and bradstreet", "aetna")


def test_resolver_uses_10k_dates_to_reject_reused_tickers_and_look_alike_names():
    from warehouse.universe import Resolver

    names = [("INGERSOLL-RAND PLC", 6), ("INGERSOLL RAND INC.", 5), ("GARDNER DENVER HOLDINGS INC.", 5),
             ("HEINZ H J CO", 7), ("HEINZ H J FINANCE CO", 8), ("VERTEX PHARMACEUTICALS INC / MA", 9),
             ("VERTEX PHARMACEUTICALS (SAN DIEGO) LLC", 10), ("TONE IN TWENTY", 11), ("LORILLARD, INC.", 12),
             ("LORILLARD TOBACCO CO", 13)]  # fmt: skip
    r = Resolver(None, {"IR": 5, "VRTX": 9}, {}, names)
    filed = {
        11: [date(2015, 3, 1)],
        12: [date(2015, 2, 1)],
        5: [date(2018, 2, 1), date(2019, 2, 1), date(2020, 2, 1)],
        6: [date(2010, 2, 1), date(2011, 2, 1)],
        7: [date(2012, 6, 1)],
        9: [date(2013, 2, 1)],
    }
    r.ten_k_dates = lambda cik: filed.get(cik, [])
    assert r("IR", "Ingersoll-Rand", date(2011, 6, 1)) == 6  # today's IR filed nothing back then
    assert r("IR", "Ingersoll Rand", date(2020, 3, 2)) == 5
    assert r("HNZ", "Heinz", date(2013, 6, 6)) == 7  # found by words, the finance subsidiary never filed a 10-K
    assert r("VRTX", "Vertex Pharmaceuticals", date(2013, 9, 20)) == 9
    assert r("LO", "Lorillard Tobacco Company", date(2015, 6, 11)) == 12  # the subsidiary never filed; the parent did
    assert r("XX", "Twenty Widgets", date(2015, 6, 1)) is None  # "twenty" doesn't start "TONE IN TWENTY"
    # A removal needs a 10-K before the date: today's IR (first 10-K 2018) can't be a company removed in 2017.
    assert r("IR", "Ingersoll Rand", date(2017, 6, 1), removal=True) is None


def test_a_company_that_reorganised_under_a_new_cik_keeps_its_stay():
    links = []
    old = {("BLK", date(2011, 4, 1)): 100}
    stays = reconstruct({"BLK": 200}, [Change(date(2011, 4, 1), "BLK", "BlackRock", None, None)],
                        lambda tk, n, d, removal=False: old.get((tk, d)), links=links)  # fmt: skip
    assert [(s.cik, s.start) for s in stays] == [(200, date(2011, 4, 1))]
    assert links == [(200, 100, date(2011, 4, 1))]


def test_a_removed_company_is_not_the_predecessor_of_a_spin_off_that_kept_its_ticker():
    links = []
    ciks = {("FOXA", date(2019, 3, 4)): 300, ("FOX", date(2015, 9, 18)): 300}
    changes = [
        Change(date(2019, 3, 4), "FOXA", "Fox Corporation", "FOXA", "Twenty-First Century Fox"),
        Change(date(2015, 9, 18), "FOX", "Twenty-First Century Fox Class B", None, None),
    ]
    resolve = lambda tk, n, d, removal=False: 400 if n == "Fox Corporation" else ciks.get((tk, d))  # noqa: E731
    reconstruct({"FOXA": 400}, changes, resolve, links=links)
    assert links == []


def test_a_rename_and_a_same_day_spin_off_with_the_old_name():
    # 2 Oct 2012: Kraft Foods Inc (KFT, CIK 1) renamed itself Mondelez (MDLZ) and spun off Kraft Foods Group
    # (KRFT, CIK 2), which Wikipedia also calls "Kraft Foods". KRFT left in 2015 (merged into Kraft Heinz).
    changes = [
        Change(date(2015, 7, 6), None, None, "KRFT", "Kraft Foods Group"),
        Change(date(2012, 10, 2), "KRFT", "Kraft Foods", "KFT", "Kraft Foods"),
        Change(date(2012, 10, 2), "MDLZ", "Mondelez", None, None),
    ]
    cands = {"KRFT": [1, 2], "MDLZ": [1], "KFT": [1]}

    class R:
        def candidates(self, tk, name, day, removal=False):
            return [2] if (tk, removal) == ("KRFT", True) else cands[tk]

        __call__ = candidates

    stays = {(s.cik, s.start, s.end) for s in reconstruct({"MDLZ": 1}, changes, R())}
    assert stays == {(1, None, None), (2, date(2012, 10, 2), date(2015, 7, 6))}


def test_primary_ticker_is_the_index_symbol_or_secs_first_listing_never_a_preferred_share():
    from warehouse.universe import primary_tickers

    wiki = [("GOOGL", 2, "Alphabet (Class A)"), ("GOOG", 2, "Alphabet (Class C)")]
    sec = [("F", 37996), ("F-PB", 37996), ("F-PD", 37996), ("GOOGL", 2), ("GOOG", 2), ("TAP", 24545), ("TAP-A", 24545)]
    assert primary_tickers(wiki, sec) == {2: "GOOGL", 37996: "F", 24545: "TAP"}


def _resolver(names, filed):
    from warehouse.universe import Resolver

    r = Resolver(None, {}, {}, names)
    r.ten_k_dates = lambda cik: filed.get(cik, [])
    return r


def test_first_word_fallback_needs_the_word_to_be_nearly_the_whole_name():
    r = _resolver([("SOLSTICE SAPPHIRE INVESTMENTS, INC.", 1), ("RIBBON COMMUNICATIONS INC.", 1), ("NICOR INC", 2)],
                  {1: [date(2025, 3, 1)], 2: [date(2011, 2, 1)]})  # fmt: skip
    assert r("SOLS", "Solstice Advanced Materials", date(2025, 12, 22), removal=True) is None
    assert r("GAS", "Nicor Gas", date(2011, 12, 12), removal=True) == 2


def test_a_fresh_spin_off_is_accepted_by_ticker_before_its_first_10k():
    from warehouse.universe import Resolver

    r = Resolver(None, {"HONA": 50, "IR": 60}, {}, [])
    r.ten_k_dates = lambda cik: {60: [date(2018, 2, 1), date(2019, 2, 1)]}.get(cik, [])
    assert r("HONA", "Honeywell Aerospace", date(2026, 6, 29)) == 50  # no 10-K yet: nothing to contradict the ticker
    assert r("IR", "Ingersoll-Rand", date(2010, 11, 17)) is None  # a reused ticker's owner has filings, just not then


def test_predecessors_are_found_by_filing_history_and_chained():
    from warehouse.universe import PREDECESSOR_NAMES, Stay, find_predecessors

    yearly = lambda a, b: [date(y, 2, 15) for y in range(a, b + 1)]  # noqa: E731
    names = [("WALT DISNEY CO", 10), ("WALT DISNEY CO/", 11), ("WALT DISNEY CO /TA", 12), ("VIATRIS INC", 1792044),
             ("MYLAN N.V.", 1623613), ("MYLAN INC.", 69499), ("FOX CORP", 20), ("TWENTY-FIRST CENTURY FOX, INC.", 21),
             ("STEADY CO", 30)]  # fmt: skip
    filed = {10: yearly(2020, 2026), 11: yearly(2005, 2019), 1792044: yearly(2021, 2026), 1623613: yearly(2016, 2020),
             69499: yearly(2003, 2015), 20: yearly(2020, 2026), 21: yearly(2005, 2019), 30: yearly(2003, 2026)}  # fmt: skip
    stays = [Stay(10, "DIS", "Walt Disney Co", None, None), Stay(1792044, "VTRS", "Viatris", None, None),
             Stay(20, "FOX", "Fox Corp", None, None), Stay(21, "FOXA", "Fox Corp", None, date(2019, 3, 19)),
             Stay(30, "STDY", "Steady Co", None, None)]  # fmt: skip
    assert PREDECESSOR_NAMES[1792044] == "Mylan N.V." and PREDECESSOR_NAMES[1623613] == "Mylan Inc"
    links, fixes = find_predecessors(_resolver(names, filed), stays)
    assert {(s, p) for s, p, _ in links} == {(10, 11), (1792044, 1623613), (1623613, 69499)}  # same name; a two-step chain
    # 21st Century Fox was a constituent itself: Fox Corp isn't linked to it, its open start becomes the day 21CF left.
    assert fixes == {20: date(2019, 3, 19)}


def test_dowdupont_is_told_apart_from_the_dupont_it_replaced():
    r = _resolver([("DUPONT E I DE NEMOURS & CO", 30554), ("DUPONT DE NEMOURS, INC.", 1666700)],
                  {30554: [date(2016, 2, 4), date(2017, 2, 2)], 1666700: [date(2018, 2, 15)]})  # fmt: skip
    assert r("DD", "DuPont", date(2017, 9, 1), removal=True) == 30554  # the old company, by SEC's spelling of its name
    assert r("DWDP", "DuPont", date(2017, 9, 1)) == 1666700  # the merged company, by its ticker
