"""Mock ATS on 127.0.0.1:8799 (CONTRACT_C §6): a Greenhouse-shaped board API, posting pages and hosted application
forms, including the cases the browser must stop at — a CAPTCHA form, a login wall, a sensitive-ID field — plus a
fee-scam posting and an ineligible posting for the pipeline's filters. Submissions go to data/mock_ats/.

Run: `python -m mock_ats` (or `make mock-ats`)."""
from __future__ import annotations

import html
import json
import os
import time
from pathlib import Path

from email.parser import BytesParser
from email.policy import default as email_policy

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

DATA = Path(os.environ.get("HQ_MOCK_ATS_DIR", Path(__file__).resolve().parent.parent / "data" / "mock_ats"))
BASE = "http://127.0.0.1:8799"

JOBS = {
    "1001": {"title": "Machine Learning Intern", "variant": "normal", "location": "Bengaluru, India",
             "content": "<p>Mocktech builds recommendation systems. As a Machine Learning Intern you will work on "
                        "collaborative filtering and data pipelines in Python with pandas and scikit-learn.</p>"
                        "<p>Requirements: currently pursuing a Bachelor's degree in Computer Science. Familiarity with "
                        "Python and scikit-learn.</p><p>Stipend: ₹40,000 per month. Duration: 6 months.</p>"},
    "1002": {"title": "Data Science Intern (CAPTCHA form)", "variant": "captcha", "location": "Remote, India",
             "content": "<p>Work on data cleaning and churn models with pandas. Requirements: pursuing a Bachelor's "
                        "degree. Stipend: ₹30,000 per month.</p>"},
    "1003": {"title": "Software Engineering Intern (login wall)", "variant": "login", "location": "Hyderabad, India",
             "content": "<p>Build Python services. Requirements: pursuing a B.Tech. Stipend: ₹35,000 per month.</p>"},
    "1004": {"title": "AI Research Intern (sensitive ID field)", "variant": "sensitive", "location": "Delhi, India",
             "content": "<p>Research on recommender systems. Requirements: pursuing a Bachelor's degree. "
                        "Stipend: ₹30,000 per month.</p>"},
    "1005": {"title": "Machine Learning Intern — Fast Track", "variant": "fee", "location": "Remote, India",
             "content": "<p>Guaranteed internship with certificate. A registration fee of Rs. 2,999 is payable "
                        "to confirm your seat. Stipend: ₹10,000 per month.</p>"},
    "1006": {"title": "Data Analyst Intern", "variant": "ineligible", "location": "Pune, India",
             "content": "<p>Graduation Year: 2026 pass-out candidates only. Stipend: ₹20,000 per month.</p>"},
}

app = FastAPI(title="Mock ATS", docs_url=None, redoc_url=None)


def _page(title: str, body: str, head: str = "") -> HTMLResponse:
    return HTMLResponse(f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>{head}"
                        f"</head><body><h1>{html.escape(title)}</h1>{body}</body></html>")


def _parse_multipart(content_type: str, body: bytes) -> dict[str, str]:
    """Stdlib multipart/urlencoded parsing (no python-multipart dependency); files are recorded by filename."""
    if content_type.startswith("application/x-www-form-urlencoded"):
        from urllib.parse import parse_qsl

        return dict(parse_qsl(body.decode(errors="replace")))
    msg = BytesParser(policy=email_policy).parsebytes(b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body)
    out: dict[str, str] = {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        filename = part.get_filename()
        out[name] = filename if filename is not None else part.get_content().strip()
    return out


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots() -> str:
    return "User-agent: *\nAllow: /\n"


@app.get("/boards-api/v1/boards/mocktech/jobs")
def board(content: bool = False) -> JSONResponse:
    jobs = [{"id": int(k), "title": v["title"], "company_name": "Mocktech",
             "location": {"name": v["location"]}, "absolute_url": f"{BASE}/jobs/{k}", "updated_at": "2026-09-20T10:00:00Z",
             "first_published": "2026-09-20T10:00:00Z", **({"content": v["content"]} if content else {})}
            for k, v in JOBS.items()]
    return JSONResponse({"jobs": jobs})


@app.get("/boards-api/v1/boards/mocktech/jobs/{job_id}")
def job_json(job_id: str, questions: bool = False) -> JSONResponse:
    j = JOBS.get(job_id)
    if not j:
        return JSONResponse({"error": "not found"}, status_code=404)
    qs = [{"label": "First Name", "required": True, "fields": [{"name": "first_name", "type": "input_text"}]},
          {"label": "Last Name", "required": True, "fields": [{"name": "last_name", "type": "input_text"}]},
          {"label": "Email", "required": True, "fields": [{"name": "email", "type": "input_text"}]},
          {"label": "Phone", "required": True, "fields": [{"name": "phone", "type": "input_text"}]},
          {"label": "Resume/CV", "required": True, "fields": [{"name": "resume", "type": "input_file"}]},
          {"label": "Are you legally authorized to work in India?", "required": True,
           "fields": [{"name": "work_auth", "type": "multi_value_single_select",
                       "values": [{"label": "Yes", "value": 1}, {"label": "No", "value": 0}]}]}]
    return JSONResponse({"id": int(job_id), "title": j["title"], "content": j["content"],
                         **({"questions": qs} if questions else {})})


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def posting(job_id: str) -> HTMLResponse:
    j = JOBS.get(job_id)
    if not j:
        return HTMLResponse("<h1>Page not found</h1>", status_code=404)
    return _page(j["title"], f"{j['content']}<p><a href='/jobs/{job_id}/apply'>Apply</a></p>")


@app.get("/jobs/{job_id}/apply", response_class=HTMLResponse)
def form(job_id: str) -> HTMLResponse:
    j = JOBS.get(job_id)
    if not j:
        return HTMLResponse("<h1>Page not found</h1>", status_code=404)
    v = j["variant"]
    head = "<script src='https://www.google.com/recaptcha/api.js'></script>" if v == "captcha" else ""
    if v == "login":
        return _page("Sign in to apply", "<form method='post' action='/login'><label>Email <input name='email' "
                                        "required></label><label>Password <input type='password' name='password' "
                                        "required></label><button>Sign in</button></form>")
    extra = ("<div class='g-recaptcha' data-sitekey='x'></div>" if v == "captcha" else "") + (
        "<label for='ssn'>National ID / SSN *</label><input id='ssn' name='ssn' required>" if v == "sensitive" else "")
    fields = """
      <label for='first_name'>First Name *</label><input id='first_name' name='first_name' required>
      <label for='last_name'>Last Name *</label><input id='last_name' name='last_name' required>
      <label for='email'>Email *</label><input id='email' name='email' type='email' required>
      <label for='phone'>Phone *</label><input id='phone' name='phone' required>
      <label for='resume'>Resume/CV *</label><input id='resume' name='resume' type='file' required>
      <label for='cover_letter'>Cover letter</label><textarea id='cover_letter' name='cover_letter'></textarea>
      <label for='work_auth'>Are you legally authorized to work in India? *</label>
      <select id='work_auth' name='work_auth' required><option value=''>Select</option><option>Yes</option><option>No</option></select>
    """
    return _page(f"Apply: {j['title']}", f"<form method='post' enctype='multipart/form-data'>{fields}{extra}"
                                         "<button type='submit' id='submit_app'>Submit application</button></form>", head)


@app.post("/jobs/{job_id}/apply", response_class=HTMLResponse)
async def submit(job_id: str, request: Request) -> HTMLResponse:
    form_data = _parse_multipart(request.headers.get("content-type", ""), await request.body())
    ref = f"MOCK-{job_id}-{int(time.time() * 1000) % 10_000_000}"
    DATA.mkdir(parents=True, exist_ok=True)
    record = {"ref": ref, "job_id": job_id, "ts": time.time(),
              "fields": form_data}
    with (DATA / "submissions.jsonl").open("a") as f:
        f.write(json.dumps(record) + "\n")
    return _page("Application received", f"<p id='confirmation'>Thanks! Your reference is <b id='ref'>{ref}</b>.</p>")


@app.get("/submissions")
def submissions() -> JSONResponse:
    path = DATA / "submissions.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    return JSONResponse({"items": rows})
