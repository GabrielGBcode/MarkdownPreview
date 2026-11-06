# Project Atlas

A **fictional** status document used to show the Markdown Viewer preview.

## 1. Overview

- Backend: `atlas-api` (Python, FastAPI)
- Frontend: `atlas-web` (TypeScript)
- Storage: PostgreSQL and an S3-compatible bucket

> Every number in this file is made up. It exists only to test the preview.

## 2. Services

| Service | Port | Owner |
|---|---|---|
| atlas-api | 8080 | Platform |
| atlas-web | 3000 | Frontend |
| atlas-worker | - | Platform |

## 3. Open issues

Legend: **H** = high, **M** = medium, **L** = low.

| # | Area | Description | Where | Sev. | How to reproduce | Suggested fix |
|---|---|---|---|---|---|---|
| 1 | Security | `DEBUG=true` left on in the production config, which exposes stack traces to users | `config/prod.yaml` | H | Open any failing URL and read the response body | Read the flag from the environment and default to `false` |
| 2 | Performance | The `/reports` endpoint runs one query per row (N+1), so a page with 500 rows takes about 4 s | `api/reports.py` | M | Request `/reports?page_size=500` and watch the query log | Use a single `JOIN` or `selectinload` |
| 3 | UX | The upload form gives no feedback while a **large file** is sent | `web/Upload.tsx` | L | Upload a file over 100 MB | Show a progress bar and disable the submit button |
| 4 | Reliability | Retries use a fixed delay, so many clients retry at the same moment after an outage | `worker/retry.py` | M | Stop the database for 30 s and start it again | Use exponential backoff with jitter |

## 4. Example code

```python
def backoff(attempt, base=0.5, cap=30):
    delay = min(cap, base * 2 ** attempt)
    return delay / 2 + random.uniform(0, delay / 2)
```

## 5. Next steps

1. Fix issue 1 before the next release.
2. Add a query-count test for `/reports`.
3. Review the retry policy with the worker team.
