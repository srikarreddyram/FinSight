"""FinSight UI: answer on the left, the cited filing page (passage highlighted) on the right.

uv run uvicorn app.api:app          # terminal 1
uv run streamlit run ui/streamlit_app.py   # terminal 2
"""

from __future__ import annotations

import os

import httpx
import streamlit as st

API = os.environ.get("FINSIGHT_API", "http://localhost:8000")

st.set_page_config(page_title="FinSight", layout="wide")
st.markdown(
    "<style>.block-container{padding-top:1.5rem} div[data-testid='stHorizontalBlock'] button{white-space:nowrap}</style>",
    unsafe_allow_html=True,
)


@st.cache_data(ttl=30)
def documents() -> list[dict]:
    try:
        return httpx.get(f"{API}/documents", timeout=10).json()
    except httpx.HTTPError:
        return []


@st.cache_data(show_spinner=False)
def page_png(doc_id: str, page: int, snippet: str, rows: bool) -> bytes | None:
    params = {"snippet": snippet[:1500], "rows": rows}
    r = httpx.get(f"{API}/documents/{doc_id}/page/{page}.png", params=params, timeout=60)
    return r.content if r.status_code == 200 else None


def ask(question: str, run: str) -> dict:
    r = httpx.post(f"{API}/ask", json={"question": question, "run": run}, timeout=180)
    r.raise_for_status()
    return r.json()


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.title("FinSight")
    st.caption("Citation-first answers over 10-Ks, 20-Fs, annual reports and earnings calls.")
    docs = documents()
    indexed = [d for d in docs if d["indexed"]]
    if not docs:
        st.error(f"API not reachable at {API}. Start it with `uv run uvicorn app.api:app`.")
    else:
        companies = sorted({d["company"] for d in indexed})
        st.metric("Indexed filings", len(indexed))
        with st.expander(f"{len(companies)} companies"):
            st.write(", ".join(companies) or "none yet")
    run = st.selectbox("Pipeline", ["E", "D", "C", "B", "A"], help="Ablation runs: E is the full system, A the naive baseline.")

    with st.expander("Upload a filing"), st.form("upload", clear_on_submit=True):
        f = st.file_uploader("PDF", type=["pdf"])
        c1, c2 = st.columns(2)
        ticker = c1.text_input("Ticker")
        company = c2.text_input("Company")
        doc_type = c1.selectbox("Type", ["annual_report", "10-K", "10-Q", "20-F", "earnings_call"])
        fy = c2.number_input("Fiscal year (year it ends)", 2000, 2100, 2025)
        period = c1.selectbox("Period", ["FY", "Q1", "Q2", "Q3", "Q4"])
        fye = c2.number_input("FY end month", 1, 12, 3)
        accurate = st.checkbox("Accurate tables (Docling, a few minutes)")
        if st.form_submit_button("Ingest") and f and ticker and company:
            with st.spinner("Parsing and indexing..."):
                r = httpx.post(
                    f"{API}/ingest",
                    files={"file": (f.name, f.getvalue(), "application/pdf")},
                    data={
                        "ticker": ticker,
                        "company": company,
                        "doc_type": doc_type,
                        "fiscal_year": fy,
                        "period": period,
                        "fiscal_year_end_month": fye,
                        "parser": "docling" if accurate else "pdfplumber",
                    },
                    timeout=900,
                )
            if r.status_code == 200:
                st.success(f"Indexed {r.json()['chunks']} chunks in {r.json().get('total_s')} s")
                documents.clear()
            else:
                st.error(r.text)

# ------------------------------------------------------------------ main
examples = [
    "What is the FY2018 capital expenditure amount (in USD millions) for 3M?",
    "Compare Nike's and PepsiCo's gross margin in their FY2022 filings.",
    "What are the main risk factors Boeing lists about the 737 MAX in FY2022?",
    "What was Infosys's operating margin in FY24 and FY25, and what drove the change?",
]
question = st.text_input("Ask about the filings", key="q", placeholder=examples[0])
cols = st.columns(len(examples))
for c, ex in zip(cols, examples, strict=True):
    if c.button(ex[:48] + "…", help=ex):
        question = ex
        st.session_state.pop("sel", None)

if question and st.session_state.get("asked") != (question, run):
    with st.spinner("Searching filings..."):
        try:
            st.session_state.result = ask(question, run)
            st.session_state.asked = (question, run)
            st.session_state.pop("sel", None)
        except httpx.HTTPError as e:
            st.error(f"Request failed: {e}")

res = st.session_state.get("result")
if res:
    left, right = st.columns([1.05, 1])
    with left:
        if res["refused"]:
            st.warning(res["answer"])
        else:
            st.markdown(res["answer"])
        if res.get("table_markdown"):
            st.markdown(res["table_markdown"])
        cites = res["citations"] if not res["refused"] else res["closest"]
        if cites:
            st.caption("Sources" if not res["refused"] else "Closest passages")
            for c in cites:
                label = f"{c['label']} · {c['section']}" + (" · table" if c["chunk_type"] == "table" else "")
                if st.button(label, key=f"cite-{c['id']}", width="stretch"):
                    st.session_state.sel = c
        t = res.get("timings", {})
        u = res.get("usage", {})
        st.caption(
            f"{t.get('total_s', 0):.1f} s · {u.get('calls', 0)} LLM calls · {u.get('input_tokens', 0):,} in / {u.get('output_tokens', 0):,} out tokens"
        )
        with st.expander("How this answer was built"):
            if res.get("parsed_query"):
                pq = res["parsed_query"]
                st.write(
                    {
                        "companies": pq["tickers"],
                        "fiscal years": pq["fiscal_years"],
                        "sections": pq["sections"],
                        "comparison": pq["is_comparison"],
                    }
                )
            if res.get("figures"):
                st.write("Figures (verified against the cited page):")
                st.dataframe(
                    [{k: f[k] for k in ("name", "display", "source_id", "verified")} for f in res["figures"]], hide_index=True
                )
            if res.get("calculations"):
                st.write("Computed in Python:")
                st.dataframe(
                    [{k: c[k] for k in ("name", "op", "inputs", "display", "error")} for c in res["calculations"]],
                    hide_index=True,
                )
            if res.get("stripped_sentences"):
                st.write("Removed sentences:")
                for s_ in res["stripped_sentences"]:
                    st.code(s_, language=None)
            st.write("Retrieved (reranked):")
            st.dataframe(
                [
                    {"source": c["label"], "section": c["section"], "type": c["chunk_type"], "score": c["score"]}
                    for c in res["retrieved"]
                ],
                hide_index=True,
            )

    with right:
        sel = st.session_state.get("sel") or (cites[0] if cites else None)
        if sel:
            st.subheader(sel["label"])
            st.markdown(f"[Open PDF at page {sel['page']}]({API}/documents/{sel['doc_id']}/pdf#page={sel['page']})")
            # Prefer the exact figure quotes the answer used; fall back to the start of the cited chunk.
            png = page_png(
                sel["doc_id"], sel["page"], sel.get("highlight") or sel.get("snippet", ""), sel["chunk_type"] == "table"
            )
            if png:
                st.image(png, width="stretch")
            else:
                st.info("Page image unavailable (is the PDF downloaded?).")
                st.text(sel.get("snippet", ""))
