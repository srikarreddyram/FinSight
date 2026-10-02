"""The research universe: S&P 500 members since 2010, including companies later removed (platform PRD).

    uv run python -m warehouse.universe            # rebuild the `universe` table and add new companies

Membership is rebuilt from Wikipedia: today's constituents (with CIKs) plus the dated table of additions and
removals, walked backwards from today. It runs on CIKs, not tickers: tickers get renamed (FB -> META) and reused
(IR was Ingersoll-Rand, now Trane; today's IR is a different company). Each company counts its share lines, so
GOOG joining in 2014 doesn't make Alphabet leave when the change is undone.

A removed company's CIK comes from its name at the time, looked up in SEC's list of every name any filer has
used (so "Facebook" finds Meta's CIK). A name shared by several filers (a parent and its subsidiaries) goes to
the one that filed 10-Ks around the change date. Anything unresolved is logged and left out.

Known limits: Wikipedia's change log is volunteer-maintained; its 2010-01-01 membership comes out within a few
names of 500. Yahoo has no prices for most acquired companies, so survivorship bias is reduced, not removed
(see the PRD's risks).
"""

from __future__ import annotations

import io
import json
import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb
import httpx
import pandas as pd

from app.config import get_settings
from warehouse import db

log = logging.getLogger(__name__)

CURRENT_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
CHANGES_URL = "https://en.wikipedia.org/wiki/Historical_components_of_the_S%26P_500"
CIK_NAMES_URL = "https://www.sec.gov/Archives/edgar/cik-lookup-data.txt"
WIKI_HEADERS = {"User-Agent": "FinSight/0.1 (student research project)"}  # no contact email: that is for SEC only
HISTORY_START = date(2010, 1, 1)


# Wikipedia's name for a company -> the name it filed under with the SEC, where they differ by more than a suffix.
SEC_NAMES = {
    "DuPont": "DuPont E I de Nemours",  # the pre-2017 company; DowDuPont is handled by HISTORICAL_TICKERS
    "TSYS": "Total System Services",
    "CA Technologies": "CA, Inc.",
    "JCPenney": "Penney J C Co",
    "Suntory Global Spirits": "Beam Inc",
    "QuintilesIMS": "Quintiles IMS Holdings",
}
# Old tickers whose row in the change log can't be told apart by name: DowDuPont (DWDP, 2017-2019) appears as
# "DuPont", the same name as the company it replaced.
HISTORICAL_TICKERS = {"DWDP": 1666700}
# Reorganisations that changed the company's name as well as its SEC ID: successor CIK -> the name its
# predecessor filed under. Same-name reorganisations (Disney 2019, Cigna 2018, Medtronic 2015) need no entry.
PREDECESSOR_NAMES = {
    1652044: "Google Inc",  # Alphabet, 2015 holding company
    1707925: "Praxair Inc",  # Linde plc, 2018: Praxair was the accounting acquirer
    1618921: "Walgreen Co",  # Walgreens Boots Alliance, 2014
    1841666: "Apache Corp",  # APA Corporation, 2021 holding company
    1792044: "Mylan N.V.",  # Viatris, 2020
    1623613: "Mylan Inc",  # Mylan N.V., 2015 inversion
    1681459: "FMC Technologies Inc",  # TechnipFMC, 2017
    2005951: "WestRock Co",  # Smurfit Westrock, 2024
    1636023: "Rock Tenn Co",  # WestRock, 2015: Rock-Tenn was the accounting acquirer
    2041610: "Paramount Global",  # Paramount Skydance, 2025
    2115436: "Exxon Mobil Corp",  # 2026 redomicile under a new SEC ID
    1571949: "IntercontinentalExchange Inc",  # ICE Group, 2013 (NYSE Euronext deal)
    1585644: "Windstream Corp",  # Windstream Holdings, 2013
    1039101: "L 3 Communications Holdings Inc",  # L3 Technologies absorbed its holding company, 2016
    1578845: "Watson Pharmaceuticals Inc",  # Actavis plc (later Allergan plc), 2013
}


@dataclass(frozen=True)
class Change:
    day: date
    added: str | None
    added_name: str | None
    removed: str | None
    removed_name: str | None


@dataclass(frozen=True)
class Stay:
    cik: int
    ticker: str
    name: str
    start: date | None  # None: already a member when the history starts
    end: date | None  # None: still a member


def ticker(s) -> str | None:
    """'BRK.B' -> 'BRK-B' (SEC and Yahoo style); footnote marks and stray characters dropped."""
    if not isinstance(s, str):
        return None
    t = re.sub(r"[^A-Z0-9.\-]", "", s.upper()).replace(".", "-")
    return t or None


_SUFFIX = re.compile(
    r"\b(the|inc|incorporated|corp|corporation|co|company|companies|ltd|limited|plc|llc|lp|nv|sa|ag|se|holdings?|group)\b"
)


def norm_name(name: str) -> str:
    n = name.lower().replace("&", " and ").replace("21st", "twenty first")
    n = re.sub(r"\(.*?\)", " ", n)
    n = re.sub(r"\b(class|series)\s+[a-z]\b(\s+special)?", " ", n)  # share classes: "Fox Class B", "Comcast Series K"
    n = re.sub(r"/[^/]*/?\s*$", " ", n)  # SEC state and status tags: "AETNA INC /PA/", "DUN & BRADSTREET CORP/NW"
    n = re.sub(r"[^a-z0-9 ]", " ", n.replace("-", " "))
    n = _SUFFIX.sub(" ", n)
    return " ".join(n.split())


def reconstruct(
    current: dict[str, int], changes: list[Change], resolve, start: date = HISTORY_START, links: list | None = None
) -> list[Stay]:
    """Membership stays since `start`. current: ticker -> CIK today.
    resolve(ticker, name, day, removal) -> CIK | None.

    A company that reorganised under a new CIK (BlackRock 2024, Broadcom, Perrigo) is added under its old CIK
    but is a member today under the new one; its stay goes to today's CIK and (new, old, day) is appended to
    `links`, so the predecessor's filings can be joined in."""
    lines: Counter[int] = Counter(current.values())
    label: dict[int, tuple[str, str]] = {cik: (t, t) for t, cik in current.items()}
    ends: dict[int, date | None] = {cik: None for cik in lines}  # end of the stay currently being walked back
    stays: list[Stay] = []
    removed: set[int] = set()
    options = getattr(resolve, "candidates", None) or (lambda *a: [c] if (c := resolve(*a)) is not None else [])
    by_day: dict[date, list[Change]] = defaultdict(list)
    for ch in changes:
        if ch.day >= start:
            by_day[ch.day].append(ch)
    for day in sorted(by_day, reverse=True):
        after = Counter(lines)  # share lines right after the day's changes: only these can have been added that day
        taken: Counter[int] = Counter()
        # Undo the day's removals first, so a rename (KFT out, MDLZ in, same CIK) isn't a leave and rejoin.
        for ch in by_day[day]:
            if not ch.removed:
                continue
            cands = options(ch.removed, ch.removed_name, day, True)
            if not cands:
                log.warning("%s: removed %s (%s) has no CIK; left out", day, ch.removed, ch.removed_name)
                continue
            cik = cands[0]
            removed.add(cik)
            if lines[cik] == 0:  # it left here, so it was a member just before
                ends[cik] = day
                label[cik] = (ch.removed, ch.removed_name or ch.removed)
            lines[cik] += 1
        # Then the additions, unambiguous ones first: each takes its first candidate with a line left from just
        # after the day, so once MDLZ has claimed Mondelez's, "Kraft Foods" (KRFT) falls through to Kraft Foods Group.
        adds = [(ch, options(ch.added, ch.added_name, day, False)) for ch in by_day[day] if ch.added]
        for ch, cands in sorted(adds, key=lambda x: len(x[1])):
            cik = next((c for c in cands if after[c] - taken[c] > 0), None)
            successor = current.get(ch.added)
            # A reorganisation under a new CIK is silent in the change log. A company that was itself removed
            # (21st Century Fox, sold to Disney) is not the predecessor of a spin-off that kept its ticker.
            if cik is None and cands and cands[0] not in removed and successor and after[successor] - taken[successor] > 0:
                if links is not None:
                    links.append((successor, cands[0], day))
                cik = successor
            if cik is None:
                log.warning("%s: added %s (%s) is not a member when walking back; skipped", day, ch.added, ch.added_name)
                continue
            taken[cik] += 1
            lines[cik] -= 1
            label[cik] = (ch.added, ch.added_name or ch.added)
            if lines[cik] == 0:  # its first share line joined here
                stays.append(Stay(cik, *label[cik], day, ends.pop(cik)))
    stays += [Stay(cik, *label[cik], None, ends[cik]) for cik, n in lines.items() if n > 0]
    return stays


class Resolver:
    """Historical ticker/name -> CIK. Candidates in order: the ticker (today's constituents, then SEC's ticker
    list), filers with exactly that name, then filers whose name contains all its words ("Heinz" -> "HEINZ H J
    CO"). The first candidate that filed a 10-K within two years of the change wins; that check is what stops
    reused tickers (today's IR only exists since 2017) and look-alike names (subsidiaries, trusts)."""

    NEAR_DAYS = 730
    MAX_FUZZY = 25

    def __init__(self, edgar, current: dict[str, int], sec_tickers: dict[str, int], cik_names: list[tuple[str, int]]):
        self.edgar, self.current, self.sec_tickers = edgar, current, sec_tickers
        self.by_name: dict[str, set[int]] = defaultdict(set)
        self.by_token: dict[str, set[int]] = defaultdict(set)
        self.tokens: dict[int, list[set[str]]] = defaultdict(list)
        self.first: dict[tuple[int, int], str] = {}  # (cik, name index) -> first word of that name
        for name, cik in cik_names:
            n = norm_name(name)
            self.by_name[n].add(cik)
            toks = set(n.split())
            if n:
                self.first[(cik, len(self.tokens[cik]))] = n.split()[0]
            self.tokens[cik].append(toks)
            for t in toks:
                self.by_token[t].add(cik)
        self._filings: dict[int, list[date]] = {}
        self.cache: dict[tuple, list[int]] = {}
        self.cache_path: Path | None = None

    def load_cache(self, path: Path) -> None:
        """10-K dates per CIK from an earlier run (filing history before today doesn't change)."""
        self.cache_path = path
        if path.exists():
            raw = json.loads(path.read_text())
            self._filings = {int(k): [date.fromisoformat(d) for d in v] for k, v in raw.items()}

    def save_cache(self) -> None:
        if self.cache_path:
            self.cache_path.write_text(json.dumps({k: [d.isoformat() for d in v] for k, v in self._filings.items()}))

    def ten_k_dates(self, cik: int) -> list[date]:
        if cik not in self._filings:
            from ingest.fetch_edgar import SUBMISSIONS_URL

            try:
                sub = self.edgar.get(SUBMISSIONS_URL.format(cik=cik)).json()
                blocks = [sub["filings"]["recent"]] + [
                    self.edgar.get(f"https://data.sec.gov/submissions/{p['name']}").json()
                    for p in sub["filings"].get("files", [])
                ]
                self._filings[cik] = [
                    date.fromisoformat(d)
                    for b in blocks
                    for f, d in zip(b["form"], b["filingDate"], strict=True)
                    if f in ("10-K", "10-K405")
                ]
            except Exception:  # noqa: BLE001  (no submissions file: not a filer we can use)
                self._filings[cik] = []
        return self._filings[cik]

    def _near(self, cik: int, day: date, before: bool = False) -> int:
        """10-Ks filed within two years of day; for a removal, only before it (the company existed then)."""
        return sum(abs((d - day).days) <= self.NEAR_DAYS and (not before or d < day) for d in self.ten_k_dates(cik))

    def _fuzzy(self, name: str, first_word_only: bool = False) -> list[int]:
        words = norm_name(name).split()
        if first_word_only:
            words = words[:1] if words and len(words[0]) >= 5 else []
        # Initials run together ("CR Bard") match SEC's spaced-out form ("BARD C R INC").
        words = {w2 for w in words for w2 in (list(w) if 2 <= len(w) <= 3 and not re.search(r"[aeiouy]", w) else [w])}
        if not words:
            return []
        cands = set.intersection(*(self.by_token.get(w, set()) for w in words))
        if first_word_only:
            # The word must start the filer's name and be nearly all of it: "Lorillard" -> "LORILLARD, INC.", not
            # "TONE IN TWENTY", and not Ribbon Communications' old shell name "Solstice Sapphire Investments".
            (w,) = words
            cands = {
                c for c in cands
                if any(self.first.get((c, i)) == w and len(t) <= 2 for i, t in enumerate(self.tokens[c]))
            }  # fmt: skip
        # All the words must appear in one of a filer's names, not spread across several of them.
        extra = {
            c: min(len(t - words) for t in self.tokens[c] if words <= t) for c in cands if any(words <= t for t in self.tokens[c])
        }
        return sorted(extra, key=extra.get)[: self.MAX_FUZZY]

    def __call__(self, tk: str | None, name: str | None, day: date, removal: bool = False) -> int | None:
        cands = self.candidates(tk, name, day, removal)
        return cands[0] if cands else None

    def candidates(self, tk: str | None, name: str | None, day: date, removal: bool = False) -> list[int]:
        """Every plausible CIK, best first. A ticker that checks out is the only candidate."""
        key = (tk, name, day, removal)
        if key not in self.cache:
            self.cache[key] = self._candidates(tk, name, day, removal)
        return self.cache[key]

    def _candidates(self, tk: str | None, name: str | None, day: date, removal: bool = False) -> list[int]:
        if tk in HISTORICAL_TICKERS:
            return [HISTORICAL_TICKERS[tk]]
        for cik in dict.fromkeys(c for c in (self.current.get(tk), self.sec_tickers.get(tk)) if c):
            # A company added before its first 10-K (a fresh spin-off) has no filings to check against; a reused
            # ticker's new owner always has some, just not near the date.
            if self._near(cik, day, removal) or (not removal and not self.ten_k_dates(cik)):
                return [cik]
        name = SEC_NAMES.get(name, name)
        groups = (
            lambda: sorted(self.by_name.get(norm_name(name), ())),
            lambda: self._fuzzy(name),
            lambda: self._fuzzy(name, True),
        )
        out: list[int] = []
        for group in (g() for g in groups) if name else ():
            scored = sorted(((self._near(c, day, removal), c) for c in group if c not in out), reverse=True)
            out += [c for n, c in scored if n]
            if out:  # a closer kind of match wins outright; fuzzier groups only fill in when it found nothing
                break
        return out


def find_predecessors(
    resolver: Resolver, stays: list[Stay], company_names: dict[int, str] | None = None, since: date = HISTORY_START
) -> tuple[list[tuple[int, int, date]], dict[int, date]]:
    """Reorganisations the index change log doesn't record: a member whose 10-Ks begin well after its membership
    did, and the company that filed them before. Returns (links, start fixes).

    A predecessor must have filed 10-Ks for years and up to the successor's first one. If the predecessor was
    itself an index member under its own ID (two constituents in sequence), nothing is linked; instead the
    successor's open-ended start is set to the day the predecessor left."""
    starts: dict[int, date] = {}
    names: dict[int, str] = {}
    ends: dict[int, date | None] = {}
    for x in stays:
        starts[x.cik] = min(starts.get(x.cik, date.max), x.start or since)
        names[x.cik] = (company_names or {}).get(x.cik, x.name)  # a stay's own label can be just the ticker
        ends[x.cik] = None if x.end is None or ends.get(x.cik, x.end) is None else max(ends.get(x.cik, x.end), x.end)
    links, fixes, queue, seen = [], {}, list(starts), set()
    while queue:
        cik = queue.pop(0)
        if cik in seen:
            continue
        seen.add(cik)
        filed = resolver.ten_k_dates(cik)
        first = min(filed) if filed else date.today()
        start = max(starts.get(cik, since), since)
        if (first - start).days < 430:  # its own filings cover its membership
            continue
        search = PREDECESSOR_NAMES.get(cik) or SEC_NAMES.get(names.get(cik, ""), names.get(cik, ""))
        if not search:
            continue
        best, best_n = None, 0
        for c in dict.fromkeys([*sorted(resolver.by_name.get(norm_name(search), ())), *resolver._fuzzy(search)]):
            if c == cik or c in seen:
                continue
            before = [d for d in resolver.ten_k_dates(c) if d < first]
            if len(before) >= 3 and (first - max(before)).days <= 550 and len(before) > best_n:
                best, best_n = c, len(before)
        if best is None:
            continue
        if best in starts and best in ends and ends[best] is not None:  # both were constituents, one after the other
            fixes[cik] = ends[best]
            continue
        links.append((cik, best, first))
        names[best] = search
        queue.append(best)
    return links, fixes


def primary_tickers(wiki: list[tuple[str, int, str]], sec: list[tuple[str, int]]) -> dict[int, str]:
    """The common-stock ticker to price each company with. A CIK has many tickers in SEC's file (Ford: F,
    F-PB, F-PC, F-PD), listed with the primary share first; today's index members use the index's own symbol
    (the first one listed for companies with two share classes)."""
    out: dict[int, str] = {}
    for t, cik, _ in wiki:
        out.setdefault(cik, t)
    for t, cik in sec:
        out.setdefault(cik, t)
    return out


def _wiki_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    get = lambda url: httpx.get(url, headers=WIKI_HEADERS, follow_redirects=True, timeout=60).text  # noqa: E731
    current = pd.read_html(io.StringIO(get(CURRENT_URL)), flavor="lxml")[0]
    changes = pd.read_html(io.StringIO(get(CHANGES_URL)), flavor="lxml")[0]
    changes.columns = ["date", "added", "added_name", "removed", "removed_name", "reason", "refs"]
    return current, changes


def build(con: duckdb.DuckDBPyConnection) -> list[Stay]:
    from ingest.fetch_edgar import TICKERS_URL, Edgar

    s = get_settings()
    edgar = Edgar(s.sec_user_agent)
    current_df, changes_df = _wiki_tables()
    current = {ticker(t): int(c) for t, c in zip(current_df["Symbol"], current_df["CIK"], strict=True)}
    sec_rows = list(edgar.get(TICKERS_URL).json().values())
    sec_tickers = {ticker(v["ticker"]): int(v["cik_str"]) for v in sec_rows}
    cache = Path(s.data_dir) / "cache" / "cik-lookup-data.txt"
    if not cache.exists():
        cache.write_bytes(edgar.get(CIK_NAMES_URL).content)
    cik_names = []
    for line in cache.read_text(encoding="latin-1").splitlines():
        name, _, rest = line.rpartition(":")[0].rpartition(":")
        if name and rest.isdigit():
            cik_names.append((name, int(rest)))
    changes = [
        Change(pd.Timestamp(r.date).date(), ticker(r.added), r.added_name if isinstance(r.added_name, str) else None,
               ticker(r.removed), r.removed_name if isinstance(r.removed_name, str) else None)
        for r in changes_df.itertuples()
    ]  # fmt: skip
    links: list[tuple[int, int, date]] = []
    resolver = Resolver(edgar, current, sec_tickers, cik_names)
    resolver.load_cache(cache.parent / "ten_k_dates.json")
    wiki = [
        (ticker(t), int(c), n) for t, c, n in zip(current_df["Symbol"], current_df["CIK"], current_df["Security"], strict=True)
    ]
    trading = primary_tickers(wiki, [(ticker(v["ticker"]), int(v["cik_str"])) for v in sec_rows])
    wiki_names: dict[int, str] = {}
    for _, cik, name in wiki:
        wiki_names.setdefault(cik, re.sub(r"\s*\((?:Class|Series) \w+\)$", "", name))
    try:
        stays = reconstruct(current, changes, resolver, links=links)
        found, fixes = find_predecessors(resolver, stays, wiki_names)
    finally:
        resolver.save_cache()
    stays = [Stay(x.cik, x.ticker, x.name, fixes[x.cik], x.end) if x.start is None and x.cik in fixes else x for x in stays]
    links = list({(a, b): (a, b, d) for a, b, d in [*links, *found]}.values())
    sec_name: dict[int, str] = {}
    for name, cik in cik_names:
        sec_name.setdefault(cik, name.title())
    con.execute("delete from cik_links")
    con.executemany("insert into cik_links values (?, ?, ?)", links)
    for _, pred, _ in links:  # a predecessor gets a row so the loaders fetch its filings; it has no ticker of its own
        con.execute("insert into companies (cik, name) values (?, ?) on conflict (cik) do nothing", [pred, sec_name.get(pred)])
    log.info("%d predecessor links, %d start fixes", len(links), len(fixes))
    con.execute("delete from universe")
    con.executemany(
        "insert into universe values (?, ?, ?, ?, ?, 'wikipedia')", [(x.cik, x.ticker, x.name, x.start, x.end) for x in stays]
    )
    for x in stays:
        con.execute(
            "insert into companies (cik, ticker, name) values (?, ?, ?) "
            "on conflict (cik) do update set ticker = excluded.ticker, name = excluded.name",
            [x.cik, trading.get(x.cik, x.ticker), wiki_names.get(x.cik, x.name)],
        )
    return stays


def members_on(con: duckdb.DuckDBPyConnection, day: date) -> list[int]:
    return [r[0] for r in con.execute(
        "select distinct cik from universe where coalesce(start_date, date '1900-01-01') <= ? and (end_date is null or end_date > ?)",
        [day, day],
    ).fetchall()]  # fmt: skip


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    con = db.connect()
    stays = build(con)
    for d in (date(2010, 1, 4), date(2015, 6, 30), date(2020, 6, 30), date.today()):
        log.info("members on %s: %d", d, len(members_on(con, d)))
    log.info("%d stays, %d companies ever in the universe since %s", len(stays), len({x.cik for x in stays}), HISTORY_START)
    con.close()


if __name__ == "__main__":
    main()
