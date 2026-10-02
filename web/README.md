# FinSight web

React + TypeScript + Vite front end for the FinSight API.

```bash
# terminal 1, repo root
uv run uvicorn app.api:app

# terminal 2
cd web
npm install
npm run dev          # http://localhost:5173, proxies /api to http://localhost:8000
```

Set `FINSIGHT_API` to point the dev proxy at another backend. `npm run build` type-checks and writes `dist/`.

What's on screen:

- **Answer**: citation chips such as `[3M FY18 p.60]` open the source page. Green figures were found printed on the
  cited page; blue ones were computed in Python.
- **Source viewer**: the rendered filing page with the rows the answer used highlighted, page navigation, and a
  link that opens the PDF at that page.
- **Refusals**: "Not found in the filings" with the closest passages.
- **How this answer was built**: detected companies and fiscal years, reranked evidence with scores, every
  figure's verification result, removed sentences, latency and LLM calls.
- **Library**: indexed filings by company, plus uploading a new filing.
- Links are shareable: `/?q=What+was+3M%27s+FY2018+capex%3F` asks on load.
