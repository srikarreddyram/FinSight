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
    assert norm_name("Sotheby's") == norm_name("SOTHEBYS") == "sothebys" and norm_name("MACY'S, INC.") == "macys"
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


def test_change_log_rows_with_footnoted_dates_and_one_sided_changes():
    import pandas as pd

    from warehouse.universe import parse_changes

    table = pd.DataFrame(
        [
            ["August 9, 2019[186]", "ABC", "Abc Corp", "XYZ", "Xyz Inc", "Market capitalization change."],
            ["March 26, 2012", "WXS", "Wright Express", float("nan"), float("nan"), "Spin-off."],
            ["not a date", "QQQ", "Q", "RRR", "R", ""],
        ]
    )
    assert parse_changes(table) == [
        Change(date(2019, 8, 9), "ABC", "Abc Corp", "XYZ", "Xyz Inc"),
        Change(date(2012, 3, 26), "WXS", "Wright Express", None, None),
    ]


def test_constituents_take_ciks_from_the_page_or_from_sec_tickers():
    import pandas as pd

    from warehouse.universe import constituents

    with_cik = pd.DataFrame(
        {"Symbol": ["AAP", "BRK.B"], "Security": ["Advance Auto Parts", "Berkshire"], "CIK": [1158449, 1067983]}
    )
    assert constituents(with_cik, {}, "sp600") == [("AAP", 1158449, "Advance Auto Parts"), ("BRK-B", 1067983, "Berkshire")]
    without = pd.DataFrame({"Symbol": ["AA", "ZZZZ"], "Security": ["Alcoa", "Unknown Co"]})
    assert constituents(without, {"AA": 1675149}, "sp400") == [("AA", 1675149, "Alcoa")]  # no CIK: left out


def test_an_index_with_a_later_start_ignores_older_changes():
    # The S&P 600's log starts in 2020: a 2018 change is before its history and must not create a stay.
    changes = [
        Change(date(2022, 5, 2), "NEWCO", "New Co", "OLDCO", "Old Co"),
        Change(date(2018, 1, 5), "META", "Meta", None, None),
    ]
    stays = {(s.cik, s.start, s.end) for s in reconstruct({"META": 1, "NEWCO": 4}, changes, _resolve, start=date(2020, 1, 1))}
    assert stays == {(1, None, None), (4, date(2022, 5, 2), None), (3, None, date(2022, 5, 2))}


def test_a_member_that_reorganised_starts_when_its_predecessor_joined_or_left():
    from warehouse.universe import Stay, close_open_starts

    stays = [
        Stay(10, "NEW", "Newco", date(2016, 1, 1), date(2025, 3, 1), "sp400"),  # open: its 2021 addition was under ID 11
        Stay(20, "DINO", "Renamed", date(2016, 1, 1), None, "sp400"),  # open: its predecessor left the S&P 500 in 2021
        Stay(30, "OLD", "Member all along", date(2016, 1, 1), None, "sp400"),
        Stay(40, "ADD", "Joined in 2019", date(2019, 5, 1), None, "sp400"),  # not open: left alone
    ]
    out = close_open_starts(
        stays,
        [True, True, True, False],
        links=[(10, 11, date(2022, 6, 1)), (40, 41, date(2020, 1, 1))],
        fixes={20: date(2021, 6, 4)},
        unmatched={"sp400": [(11, date(2021, 5, 17)), (41, date(2018, 1, 1))], "sp600": [(11, date(2023, 1, 1))]},
    )
    assert [x.start for x in out] == [date(2021, 5, 17), date(2021, 6, 4), date(2016, 1, 1), date(2019, 5, 1)]


def test_a_ticker_that_passed_to_another_active_company_is_resolved_by_name():
    from warehouse.universe import Resolver

    names = [("WILLIS TOWERS WATSON PLC", 70), ("WEIGHT WATCHERS INTERNATIONAL INC", 71), ("HILL-ROM HOLDINGS, INC.", 72)]
    r = Resolver(None, {"WTW": 70, "HRC": 72}, {}, names)
    filed = {70: [date(2017, 2, 1), date(2018, 2, 1)], 71: [date(2017, 3, 1), date(2018, 3, 1)], 72: [date(2021, 11, 1)]}
    r.ten_k_dates = lambda cik: filed.get(cik, [])
    # WTW is Willis Towers Watson's ticker today, and Willis was filing in 2018 too; the name says Weight Watchers.
    # An addition keeps the holder first (the walk back takes the first candidate with a share line to give).
    assert r.candidates("WTW", "Weight Watchers", date(2018, 9, 18)) == [70, 71]
    assert r("WTW", "Willis Towers Watson", date(2018, 9, 18)) == 70
    # A name SEC spells differently finds nothing by name, so the ticker's holder stands.
    assert r("HRC", "Hillrom", date(2021, 12, 20), removal=True) == 72


def test_a_removal_goes_to_the_filer_with_the_rows_name_not_an_unrelated_ticker_holder():
    from warehouse.universe import SEC_NAMES, Resolver

    names = [
        ("CENCORA, INC.", 1),
        ("CORESITE REALTY CORP", 2),
        ("APARTMENT INVESTMENT & MANAGEMENT CO", 3),
        ("AIMCO PROPERTIES L.P.", 4),
    ]
    r = Resolver(None, {}, {"COR": 1, "AIV": 3}, names)
    r.ten_k_dates = lambda cik: [date(2017, 3, 1), date(2020, 3, 1), date(2021, 3, 1)]
    assert r("COR", "CoreSite", date(2021, 12, 28), removal=True) == 2  # COR is Cencora's ticker today
    assert r.candidates("COR", "CoreSite Realty", date(2017, 8, 10)) == [1, 2]  # an addition: holder first, then the name
    # "Aimco" is a brand: only the operating partnership files under it, so the legal name is listed by hand.
    assert SEC_NAMES["Aimco"] == "Apartment Investment & Management"
    assert r("AIV", "Aimco", date(2020, 12, 21), removal=True) == 3


def test_a_renamed_reorganisation_is_found_among_additions_that_never_left():
    from warehouse.universe import Stay, find_predecessors

    yearly = lambda a, b: [date(y, 2, 15) for y in range(a, b + 1)]  # noqa: E731
    names = [
        ("TKO GROUP HOLDINGS, INC.", 80),
        ("WORLD WRESTLING ENTERTAINMENT INC", 81),
        ("ACQUIRED CO", 82),
        ("LONG GONE CO", 83),
    ]
    filed = {80: yearly(2024, 2026), 81: yearly(2005, 2023), 82: yearly(2005, 2026), 83: yearly(2005, 2019)}
    stays = [Stay(80, "TKO", "TKO Group Holdings", date(2016, 1, 1), date(2025, 3, 24), "sp400")]
    r = _resolver(names, filed)
    # 81 stopped filing as TKO began; 82 kept filing and 83 stopped years earlier, so neither handed over to it.
    links, fixes = find_predecessors(r, stays, hints=(81, 82, 83))
    assert [(s, p) for s, p, _ in links] == [(80, 81)] and fixes == {}
    assert find_predecessors(r, stays) == ([], {})  # no hint, and no filer named TKO before 2024
    filed[83] = yearly(2005, 2023)  # two companies that stopped at the same time: too ambiguous to link
    assert find_predecessors(r, stays, hints=(81, 83)) == ([], {})


def test_a_delisted_company_is_never_priced_under_a_symbol_someone_else_may_hold_now():
    from warehouse.universe import stored_ticker

    listed = {1571996: "DELL", 320193: "AAPL"}
    assert stored_ticker(320193, "AAPL", listed) == "AAPL"
    assert stored_ticker(826083, "DELL", listed) == "DELL~826083"  # the Dell that left in 2013, not today's


def test_a_failed_sec_lookup_is_not_remembered_as_no_filings():
    import httpx

    from warehouse.universe import Resolver

    class Edgar:
        def __init__(self):
            self.status = 503

        def get(self, url):
            r = httpx.Response(self.status, request=httpx.Request("GET", url), json={
                "filings": {"recent": {"form": ["10-K", "8-K"], "filingDate": ["2021-02-12", "2021-03-01"]}, "files": []}
            })  # fmt: skip
            r.raise_for_status()
            return r

    edgar = Edgar()
    r = Resolver(edgar, {}, {}, [])
    assert r.ten_k_dates(1050446) == [] and r.failed == 1 and 1050446 not in r._filings  # a server error: no answer yet
    edgar.status = 200
    assert r.ten_k_dates(1050446) == [date(2021, 2, 12)]  # asked again, and now cached
    edgar.status = 404
    assert r.ten_k_dates(999) == [] and 999 in r._filings and r.failed == 1  # "no such filer" is an answer


def test_short_all_consonant_names_match_as_written_before_being_read_as_initials():
    r = _resolver(
        [("CSG SYSTEMS INTERNATIONAL INC", 90), ("BARD C R INC /NJ/", 91)], {90: [date(2026, 2, 20)], 91: [date(2017, 2, 10)]}
    )
    assert r("CSGS", "CSG Systems", date(2026, 5, 18), removal=True) == 90
    assert r("BCR", "CR Bard", date(2017, 12, 29), removal=True) == 91
