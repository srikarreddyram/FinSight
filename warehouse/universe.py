"""The research universe: S&P 500, 400 and 600 members, including companies later removed (platform PRD).

    uv run python -m warehouse.universe            # rebuild the `universe` table and add new companies
    uv run python -m warehouse.universe --dry-run  # only report what the rebuild would give

Membership is rebuilt from Wikipedia, one index at a time: today's constituents plus the dated table of
additions and removals, walked backwards from today. Each index goes back only as far as its change log is
complete (INDEXES): 2010 for the S&P 500, 2016 for the 400 and 2020 for the 600. Before that date a company
is not counted as a member of that index, because who belonged then isn't known. It runs on CIKs, not tickers: tickers get renamed (FB -> META) and reused
(IR was Ingersoll-Rand, now Trane; today's IR is a different company). Each company counts its share lines, so
GOOG joining in 2014 doesn't make Alphabet leave when the change is undone.

A removed company's CIK comes from its name at the time, looked up in SEC's list of every name any filer has
used (so "Facebook" finds Meta's CIK). A name shared by several filers (a parent and its subsidiaries) goes to
the one that filed 10-Ks around the change date. Anything unresolved is logged and left out.

Known limits: Wikipedia's change log is volunteer-maintained; its 2010-01-01 membership comes out within a few
names of 500. Yahoo has no prices for delisted companies, so a member that was later acquired or went bankrupt
has features but no returns: survivorship bias is reduced, not removed (see the PRD's risks).
"""

from __future__ import annotations

import argparse
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

WIKI = "https://en.wikipedia.org/wiki/"
CIK_NAMES_URL = "https://www.sec.gov/Archives/edgar/cik-lookup-data.txt"
WIKI_HEADERS = {"User-Agent": "FinSight/0.1 (student research project)"}  # no contact email: that is for SEC only
HISTORY_START = date(2010, 1, 1)


@dataclass(frozen=True)
class Index:
    name: str
    page: str  # Wikipedia page with today's constituents (first table)
    changes_page: str  # page whose table `changes_table` is the dated change log
    changes_table: int
    start: date  # membership is rebuilt back to here and not before


# Start dates follow the change logs. The 400's log reaches 2012 but lists 16 to 25 changes a year before
# 2016 against 40 to 60 after, so its early years are incomplete; the 600's log begins in December 2019.
INDEXES = (
    Index("sp500", "List_of_S%26P_500_companies", "Historical_components_of_the_S%26P_500", 0, HISTORY_START),
    Index("sp400", "List_of_S%26P_400_companies", "List_of_S%26P_400_companies", 1, date(2016, 1, 1)),
    Index("sp600", "List_of_S%26P_600_companies", "List_of_S%26P_600_companies", 1, date(2020, 1, 1)),
)


# Wikipedia's name for a company -> the name it filed under with the SEC, where they differ by more than a suffix.
SEC_NAMES = {
    "DuPont": "DuPont E I de Nemours",  # the pre-2017 company; DowDuPont is handled by HISTORICAL_TICKERS
    "TSYS": "Total System Services",
    "CA Technologies": "CA, Inc.",
    "JCPenney": "Penney J C Co",
    "Suntory Global Spirits": "Beam Inc",
    "QuintilesIMS": "Quintiles IMS Holdings",
    "U.S. Steel": "United States Steel",
    "Aimco": "Apartment Investment & Management",
    "San Jose Water Group": "SJW Group",
    "Hillrom": "Hill-Rom Holdings",
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
    index: str = "sp500"


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
    n = re.sub(r"['’]s\b", "s", n)  # "Sotheby's" files as SOTHEBYS, "Macy's" as MACY'S: both become one word
    n = re.sub(r"\(.*?\)", " ", n)
    n = re.sub(r"\b(class|series)\s+[a-z]\b(\s+special)?", " ", n)  # share classes: "Fox Class B", "Comcast Series K"
    n = re.sub(r"/[^/]*/?\s*$", " ", n)  # SEC state and status tags: "AETNA INC /PA/", "DUN & BRADSTREET CORP/NW"
    n = re.sub(r"[^a-z0-9 ]", " ", n.replace("-", " "))
    n = _SUFFIX.sub(" ", n)
    return " ".join(n.split())


def reconstruct(
    current: dict[str, int],
    changes: list[Change],
    resolve,
    start: date = HISTORY_START,
    links: list | None = None,
    unmatched: list | None = None,
) -> list[Stay]:
    """Membership stays since `start`. current: ticker -> CIK today.
    resolve(ticker, name, day, removal) -> CIK | None. An addition that resolves to a company with no share
    line to take is skipped and, if `unmatched` is given, recorded there as (CIK, day).

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
                if unmatched is not None and cands:
                    unmatched.append((cands[0], day))
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
        self.failed = 0  # lookups that failed for a reason other than "no such filer": never cached
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
            except httpx.HTTPStatusError as e:
                if e.response.status_code != 404:  # anything but "no such filer" is a failed lookup, not an answer
                    self.failed += 1
                    log.warning("CIK %d: submissions lookup failed (%s); treated as no 10-Ks this run", cik, e)
                    return []
                blocks = []
            except httpx.TransportError as e:
                self.failed += 1
                log.warning("CIK %d: submissions lookup failed (%s); treated as no 10-Ks this run", cik, e)
                return []
            self._filings[cik] = [
                date.fromisoformat(d)
                for b in blocks
                for f, d in zip(b["form"], b["filingDate"], strict=True)
                if f in ("10-K", "10-K405")
            ]
        return self._filings[cik]

    def _near(self, cik: int, day: date, before: bool = False) -> int:
        """10-Ks filed within two years of day; for a removal, only before it (the company existed then)."""
        return sum(abs((d - day).days) <= self.NEAR_DAYS and (not before or d < day) for d in self.ten_k_dates(cik))

    def _fuzzy(self, name: str, first_word_only: bool = False) -> list[int]:
        words = norm_name(name).split()
        if first_word_only:
            words = words[:1] if words and len(words[0]) >= 5 else []
        # Initials run together ("CR Bard") match SEC's spaced-out form ("BARD C R INC"); tried only when the
        # words as written find nothing, since "CSG Systems" and "SJW Group" file under exactly those letters.
        spaced = {w2 for w in words for w2 in (list(w) if 2 <= len(w) <= 3 and not re.search(r"[aeiouy]", w) else [w])}
        for variant in dict.fromkeys((frozenset(words), frozenset(spaced))):
            found = self._with_words(set(variant), first_word_only)
            if found:
                return found
        return []

    def _with_words(self, words: set[str], first_word_only: bool) -> list[int]:
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

    def _named(self, cik: int, name: str | None) -> bool:
        """Whether any name the filer has used shares a word with `name` (true when either is unknown)."""
        words = set(norm_name(SEC_NAMES.get(name, name)).split()) if name else set()
        return not words or cik not in self.tokens or any(words & t for t in self.tokens[cik])

    def _candidates(self, tk: str | None, name: str | None, day: date, removal: bool = False) -> list[int]:
        if tk in HISTORICAL_TICKERS:
            return [HISTORICAL_TICKERS[tk]]
        by_ticker: list[int] = []
        for cik in dict.fromkeys(c for c in (self.current.get(tk), self.sec_tickers.get(tk)) if c):
            # A company added before its first 10-K (a fresh spin-off) has no filings to check against; a reused
            # ticker's new owner always has some, just not near the date.
            if self._near(cik, day, removal) or (not removal and not self.ten_k_dates(cik)):
                if self._named(cik, name):
                    return [cik]
                # A ticker can pass between two companies that were both filing at the time (WTW was Weight
                # Watchers until 2019 and is Willis Towers Watson now; CPWR and EP belong to shells today), so
                # a holder with an unrelated name is not the only candidate: the name search adds its own.
                by_ticker = by_ticker or [cik]
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
        if not by_ticker:
            return out
        # Against a ticker holder with an unrelated name. A removal takes its first candidate, and a filer that
        # matches the row's name is the likelier one (COR was CoreSite Realty and is Cencora now); where the row
        # uses a brand name that only a subsidiary files under ("Aimco"), SEC_NAMES gives the legal name. An
        # addition takes the first candidate with a share line to give, so the holder can stay first.
        rest = [c for c in out if c not in by_ticker]
        return rest + by_ticker if removal else by_ticker + rest


def find_predecessors(
    resolver: Resolver,
    stays: list[Stay],
    company_names: dict[int, str] | None = None,
    since: date = HISTORY_START,
    hints: tuple[int, ...] = (),
) -> tuple[list[tuple[int, int, date]], dict[int, date]]:
    """Reorganisations the index change log doesn't record: a member whose 10-Ks begin well after its membership
    did, and the company that filed them before. Returns (links, start fixes).

    A predecessor must have filed 10-Ks for years and up to the successor's first one. It is looked for by name;
    failing that, among `hints` (companies that were added to an index but never left it under their own ID),
    where it must also have stopped filing as the successor began, and be the only one that did: that finds a
    reorganisation that changed the name too (WWE became TKO). If the predecessor was itself an index member
    under its own ID (two constituents in sequence), nothing is linked; instead the successor's open-ended start
    is set to the day the predecessor left."""
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

        def filed_until(c: int, first: date = first) -> int:
            """How many 10-Ks c filed before the successor's first one, if they ran for years and right up to it."""
            before = [d for d in resolver.ten_k_dates(c) if d < first]
            return len(before) if len(before) >= 3 and (first - max(before)).days <= 550 else 0

        by_name = [*sorted(resolver.by_name.get(norm_name(search), ())), *resolver._fuzzy(search)] if search else []
        scored = {c: filed_until(c) for c in dict.fromkeys(by_name) if c != cik and c not in seen}
        best = max(scored, key=scored.get) if any(scored.values()) else None
        if best is None:
            search = None
            handed_over = [
                c for c in dict.fromkeys(hints)
                if c != cik and c not in seen and filed_until(c) and (max(resolver.ten_k_dates(c)) - first).days < 200
            ]  # fmt: skip
            if len(handed_over) != 1:
                continue
            best = handed_over[0]
        if best in starts and best in ends and ends[best] is not None:  # both were constituents, one after the other
            fixes[cik] = ends[best]
            continue
        links.append((cik, best, first))
        if search:
            names[best] = search
        queue.append(best)
    return links, fixes


def close_open_starts(
    stays: list[Stay],
    is_open: list[bool],
    links: list[tuple[int, int, date]],
    fixes: dict[int, date],
    unmatched: dict[str, list[tuple[int, date]]],
) -> list[Stay]:
    """Start dates for stays the walk back left open (`is_open`), which normally means "a member since before
    the history". A company that reorganised under a new SEC ID while a member has no addition under that ID:
    it joined either on the day its predecessor left an index (`fixes`, from find_predecessors) or on the day
    the predecessor was added to this one (an unmatched addition of a company it is linked to)."""
    preds: dict[int, set[int]] = defaultdict(set)
    for successor, predecessor, _ in links:
        preds[successor].add(predecessor)
    out = []
    for x, open_ in zip(stays, is_open, strict=True):
        day = fixes.get(x.cik) if open_ else None
        if open_ and day is None:
            line, queue = set(), [x.cik]
            while queue:  # predecessors of predecessors too (Viatris <- Mylan N.V. <- Mylan Inc)
                for p in preds.get(queue.pop(), ()):
                    if p not in line:
                        line.add(p)
                        queue.append(p)
            days = [d for c, d in unmatched.get(x.index, ()) if c in line and (x.end is None or d < x.end)]
            day = max(days, default=None)
        if day is not None and (x.end is None or day < x.end) and (x.start is None or day > x.start):
            x = Stay(x.cik, x.ticker, x.name, day, x.end, x.index)
        out.append(x)
    return out


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


def parse_changes(table: pd.DataFrame) -> list[Change]:
    """A Wikipedia change-log table (date, added ticker and name, removed ticker and name, ...) as Changes.
    Dates can carry a footnote mark ("August 9, 2019[186]")."""
    out = []
    for r in table.iloc[:, :5].itertuples(index=False):
        day = pd.to_datetime(re.sub(r"\[.*?\]", "", str(r[0])).strip(), errors="coerce")
        if pd.isna(day):
            log.warning("change log row with unreadable date %r; skipped", r[0])
            continue
        name = lambda v: v if isinstance(v, str) else None  # noqa: E731
        out.append(Change(day.date(), ticker(r[1]), name(r[2]), ticker(r[3]), name(r[4])))
    return out


def stored_ticker(cik: int, label: str, listed: dict[int, str]) -> str:
    """The ticker a company is stored and priced under. A company SEC still lists uses its symbol there. One
    that is gone keeps its last symbol with its CIK appended (KG~1047699): the bare symbol may have passed to
    another company since (KG, DELL, FOX), and Yahoo keeps no history for delisted shares, so whatever it returns
    for the old symbol is someone else's price. Nothing is ever fetched for a symbol with a "~"."""
    return listed.get(cik) or f"{label}~{cik}"


def _wiki_tables(index: Index) -> tuple[pd.DataFrame, pd.DataFrame]:
    get = lambda page: httpx.get(WIKI + page, headers=WIKI_HEADERS, follow_redirects=True, timeout=60).text  # noqa: E731
    html = get(index.page)
    current = pd.read_html(io.StringIO(html), flavor="lxml")[0]
    changes_html = html if index.changes_page == index.page else get(index.changes_page)
    return current, pd.read_html(io.StringIO(changes_html), flavor="lxml")[index.changes_table]


def constituents(table: pd.DataFrame, sec_tickers: dict[str, int], index: str) -> list[tuple[str, int, str]]:
    """(ticker, CIK, name) for today's members. The S&P 400 page has no CIK column, so its CIKs come from
    SEC's ticker list."""
    out = []
    for i, (sym, name) in enumerate(zip(table["Symbol"], table["Security"], strict=True)):
        t = ticker(sym)
        cik = int(table["CIK"].iloc[i]) if "CIK" in table.columns else sec_tickers.get(t)
        if cik is None:
            log.warning("%s: %s (%s) has no CIK in SEC's ticker list; left out", index, t, name)
            continue
        out.append((t, cik, name))
    return out


@dataclass
class Built:
    stays: list[Stay]
    links: list[tuple[int, int, date]]
    tickers: dict[int, str]  # CIK -> the ticker to price it with
    names: dict[int, str]  # CIK -> display name, for today's members
    sec_names: dict[int, str]  # CIK -> a name from SEC's list, for everyone else


def compute() -> Built:
    """Membership stays and predecessor links, from Wikipedia and EDGAR. Writes nothing but the 10-K date cache."""
    from ingest.fetch_edgar import TICKERS_URL, Edgar

    s = get_settings()
    edgar = Edgar(s.sec_user_agent)
    sec_rows = list(edgar.get(TICKERS_URL).json().values())
    sec = [(ticker(v["ticker"]), int(v["cik_str"])) for v in sec_rows]
    sec_tickers: dict[str, int] = {}
    for t, cik in sec:
        sec_tickers.setdefault(t, cik)
    cache = Path(s.data_dir) / "cache" / "cik-lookup-data.txt"
    if not cache.exists():
        cache.write_bytes(edgar.get(CIK_NAMES_URL).content)
    cik_names = []
    for line in cache.read_text(encoding="latin-1").splitlines():
        name, _, rest = line.rpartition(":")[0].rpartition(":")
        if name and rest.isdigit():
            cik_names.append((name, int(rest)))
    pages = {}
    for idx in INDEXES:
        current_df, changes_df = _wiki_tables(idx)
        pages[idx.name] = (constituents(current_df, sec_tickers, idx.name), parse_changes(changes_df))
    wiki = [row for idx in INDEXES for row in pages[idx.name][0]]
    links: list[tuple[int, int, date]] = []
    # Ticker lookups see every index's members, so a company that moved between indexes resolves either way.
    resolver = Resolver(edgar, {t: cik for t, cik, _ in reversed(wiki)}, sec_tickers, cik_names)
    resolver.load_cache(cache.parent / "ten_k_dates.json")
    wiki_names: dict[int, str] = {}
    for _, cik, name in wiki:
        wiki_names.setdefault(cik, re.sub(r"\s*\((?:Class|Series) \w+\)$", "", name))
    stays: list[Stay] = []
    is_open: list[bool] = []
    unmatched: dict[str, list[tuple[int, date]]] = {}
    try:
        for idx in INDEXES:
            members, changes = pages[idx.name]
            unmatched[idx.name] = []
            found = reconstruct(
                {t: cik for t, cik, _ in members}, changes, resolver, start=idx.start, links=links, unmatched=unmatched[idx.name]
            )
            # Only the S&P 500's history covers the whole study, so only its members can predate the start.
            first = None if idx.start == HISTORY_START else idx.start
            stays += [Stay(x.cik, x.ticker, x.name, x.start or first, x.end, idx.name) for x in found]
            is_open += [x.start is None for x in found]
            log.info("%s: %d stays from %d current members and %d changes", idx.name, len(found), len(members), len(changes))
        hints = tuple(c for rows in unmatched.values() for c, _ in rows)
        found_links, fixes = find_predecessors(resolver, stays, wiki_names, hints=hints)
    finally:
        resolver.save_cache()
    links = list({(a, b): (a, b, d) for a, b, d in [*links, *found_links]}.values())
    stays = close_open_starts(stays, is_open, links, fixes, unmatched)
    log.info("%d predecessor links, %d start fixes", len(links), len(fixes))
    if resolver.failed:
        log.warning("%d SEC lookups failed; companies resolved through them may be missing. Run again.", resolver.failed)
    sec_name: dict[int, str] = {}
    for name, cik in cik_names:
        sec_name.setdefault(cik, name.title())
    return Built(stays, links, primary_tickers(wiki, sec), wiki_names, sec_name)


def build(con: duckdb.DuckDBPyConnection, built: Built | None = None) -> list[Stay]:
    b = built or compute()
    con.execute("delete from cik_links")
    con.executemany("insert into cik_links values (?, ?, ?)", b.links)
    for _, pred, _ in b.links:  # a predecessor gets a row so the loaders fetch its filings; it has no ticker of its own
        con.execute("insert into companies (cik, name) values (?, ?) on conflict (cik) do nothing", [pred, b.sec_names.get(pred)])
    con.execute("delete from universe")
    con.executemany(
        "insert into universe (cik, ticker, name, start_date, end_date, source, index_name) values (?, ?, ?, ?, ?, 'wikipedia', ?)",
        [(x.cik, x.ticker, x.name, x.start, x.end, x.index) for x in b.stays],
    )
    for x in b.stays:
        con.execute(
            "insert into companies (cik, ticker, name) values (?, ?, ?) "
            "on conflict (cik) do update set ticker = excluded.ticker, name = excluded.name",
            [x.cik, stored_ticker(x.cik, x.ticker, b.tickers), b.names.get(x.cik, x.name)],
        )
    return b.stays


def count_on(stays: list[Stay], day: date, index: str | None = None) -> int:
    """Distinct members on `day` (of one index, or of any), from stays in memory."""
    return len({
        x.cik for x in stays
        if (x.start is None or x.start <= day) and (x.end is None or x.end > day) and index in (None, x.index)
    })  # fmt: skip


def members_on(con: duckdb.DuckDBPyConnection, day: date, index: str | None = None) -> list[int]:
    """CIKs that were members on `day`: of one index, or of any when index is None."""
    return [r[0] for r in con.execute(
        "select distinct cik from universe where coalesce(start_date, date '1900-01-01') <= ? and (end_date is null or end_date > ?)"
        " and (? is null or index_name = ?)",
        [day, day, index, index],
    ).fetchall()]  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="rebuild membership and report it, without touching the warehouse")
    ap.add_argument("--dump", type=Path, help="also write the stays to this CSV")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    built = compute()
    stays = built.stays
    if not args.dry_run:
        con = db.connect()
        build(con, built)
        con.close()
    if args.dump:
        pd.DataFrame(stays).sort_values(["index", "cik", "end"]).to_csv(args.dump, index=False)
    for d in (date(2010, 1, 4), date(2016, 6, 30), date(2020, 6, 30), date(2023, 6, 30), date.today()):
        counts = {idx.name: count_on(stays, d, idx.name) for idx in INDEXES}
        log.info("members on %s: %s, %d in all", d, counts, count_on(stays, d))
    log.info("%d stays, %d companies ever in the universe since %s", len(stays), len({x.cik for x in stays}), HISTORY_START)


if __name__ == "__main__":
    main()
