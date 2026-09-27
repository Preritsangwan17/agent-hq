"""Browser adapter for ATS forms (CONTRACT_C §6) — v1 fills ONLY the local mock ATS (127.0.0.1:8799).

Playwright with a request filter that aborts everything not on loopback (so third-party scripts such as a CAPTCHA
widget never load). It stops and hands over a pack at the first sign of anything HQ must never do: a CAPTCHA, a login
or account wall, a password field, a sensitive-ID field (national ID/SSN/Aadhaar/PAN/passport/bank), a fee, or a
required question it has no confirmed answer for. Filled-form and confirmation screenshots are kept as evidence."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from hq import settings as paths
from hq.adapters.base import RunContext, RunResult
from hq.pipeline.agents.common import label, need_effect
from hq.pipeline.apply.answers import resolve
from hq.util import netguard
from hq.util.timeutil import now_iso

MOCK_PORT = 8799
SENSITIVE = re.compile(r"\b(ssn|social security|national id|aadha+r|pan (card|number)|passport|bank account|ifsc|"
                       r"date of birth|dob)\b", re.I)
CAPTCHA = re.compile(r"g-recaptcha|h-captcha|hcaptcha|cf-turnstile|captcha", re.I)
FEE = re.compile(r"\b(registration|application|processing|training)\s+fee\b|\bpay\s+(?:rs\.?|₹|inr)", re.I)
CHROMIUM = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"


class Stop(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class SubmissionUnconfirmed(Exception):
    """The submit action may have reached the ATS, but no trustworthy confirmation was observed."""


def allowed_url(url: str) -> bool:
    return netguard.host_of(url) in ("127.0.0.1", "localhost") and f":{MOCK_PORT}" in url


def form_url(url: str) -> str:
    return url if url.rstrip("/").endswith("/apply") else url.rstrip("/") + "/apply"


def _chromium_path() -> str | None:
    import glob

    if Path(CHROMIUM).exists():
        return CHROMIUM
    found = sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome"))
    return found[-1] if found else None


async def _fields(page) -> list[dict[str, Any]]:
    return await page.evaluate("""() => Array.from(document.querySelectorAll('form input, form textarea, form select'))
      .filter(el => el.type !== 'hidden' && el.type !== 'submit')
      .map(el => {
        const lab = el.id ? document.querySelector(`label[for="${el.id}"]`) : el.closest('label');
        return {name: el.name, id: el.id, tag: el.tagName.toLowerCase(), type: el.type || '',
                required: el.required, label: (lab ? lab.textContent : el.name || '').replace(/\\*/g, '').trim(),
                options: el.tagName === 'SELECT' ? Array.from(el.options).map(o => o.text).filter(t => t && t !== 'Select') : null};
      })""")


async def fill_and_submit(url: str, *, conn, letter: str, resume_path: str | None, shot: Path,
                          submit: bool = True) -> dict[str, Any]:
    """Fill the form at `url`. Returns {ref, filled, screenshot}; raises Stop(reason) at any stop condition."""
    from playwright.async_api import async_playwright

    if not allowed_url(url):
        raise Stop("the browser only fills the local mock ATS in v1")
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=_chromium_path(), headless=True)
        try:
            page = await browser.new_page()
            blocked: list[str] = []

            async def gate(route):
                if allowed_url(route.request.url):
                    await route.continue_()
                else:
                    blocked.append(route.request.url)
                    await route.abort()

            await page.route("**/*", gate)
            if form_url(url) != url:  # read the posting itself first: a fee there is a stop even if the form is clean
                await page.goto(url, wait_until="domcontentloaded", timeout=15_000)
                if FEE.search(await page.inner_text("body")):
                    raise Stop("the posting asks for a fee — HQ never pays")
            await page.goto(form_url(url), wait_until="domcontentloaded", timeout=15_000)
            body = await page.content()
            if await page.locator("input[type=password]").count():
                raise Stop("the site wants a login/account — HQ never creates accounts or enters passwords")
            if CAPTCHA.search(body) or any("captcha" in b for b in blocked):
                raise Stop("the form has a CAPTCHA — HQ never solves CAPTCHAs")
            text = await page.inner_text("body")
            if FEE.search(text):
                raise Stop("the page asks for a fee — HQ never pays")
            fields = await _fields(page)
            if not fields:
                raise Stop("no application form found on the page")
            for f in fields:  # scan everything before typing anything
                if SENSITIVE.search(f["label"] or f["name"]):
                    raise Stop(f"the form asks for “{f['label'] or f['name']}” — sensitive IDs are always yours to enter")
            filled = []
            for f in fields:
                lab = f["label"] or f["name"]
                sel = f"#{f['id']}" if f["id"] else f"[name='{f['name']}']"
                if f["type"] == "file":
                    if re.search(r"resume|cv", lab, re.I):
                        if not resume_path:
                            raise Stop("no résumé to upload")
                        await page.set_input_files(sel, resume_path)
                        filled.append({"label": lab, "value": Path(resume_path).name})
                    elif f["required"]:
                        raise Stop(f"required upload “{lab}” HQ has no file for")
                    continue
                if re.search(r"cover letter", lab, re.I) and f["tag"] == "textarea":
                    await page.fill(sel, letter)
                    filled.append({"label": lab, "value": f"{len(letter.split())} words"})
                    continue
                ans = resolve(conn, lab, required=f["required"], options=f["options"])
                if ans.status != "filled":
                    if f["required"]:
                        raise Stop(f"“{lab}” needs you ({ans.note or 'no confirmed answer'})")
                    continue
                if f["tag"] == "select":
                    choice = next((o for o in f["options"] or [] if o.lower() == ans.value.lower()), None)
                    if choice is None:
                        if f["required"]:
                            raise Stop(f"“{lab}”: none of the options match the stored answer")
                        continue
                    await page.select_option(sel, label=choice)
                else:
                    await page.fill(sel, ans.value)
                filled.append({"label": lab, "value": ans.value})
            shot.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(shot), full_page=True)
            if not submit:
                return {"ref": None, "filled": filled, "screenshot": str(shot)}
            try:
                await page.click("button[type=submit]")
                await page.wait_for_selector("#confirmation", timeout=10_000)
                ref = (await page.inner_text("#ref")).strip()
                if not re.fullmatch(r"MOCK-[A-Za-z0-9-]+", ref):
                    raise ValueError("confirmation has no valid application reference")
                confirmation_shot = shot.with_name("ats_confirmation.png")
                await page.screenshot(path=str(confirmation_shot), full_page=True)
            except Exception as exc:
                raise SubmissionUnconfirmed("submit was attempted but ATS confirmation could not be verified") from exc
            return {"ref": ref, "filled": filled, "screenshot": str(shot),
                    "confirmation_screenshot": str(confirmation_shot)}
        finally:
            await browser.close()


async def submit_mock_ats(task: dict[str, Any], ctx: RunContext, opp: dict[str, Any], app: dict[str, Any],
                          doc: dict[str, Any]) -> RunResult:
    if app.get("status") in ("submission_attempted", "submitted"):
        return RunResult(output={"ok": False, "stage_reason": "application already attempted; verify before retrying"},
                         summary=f"{label(opp)}: submission already attempted — check ATS evidence first")
    url = opp.get("apply_url") or opp.get("url") or ""
    resume = None
    if app.get("resume_doc_id"):
        rows = ctx.query("SELECT content_path FROM documents WHERE id=?", (app["resume_doc_id"],))
        resume = rows[0]["content_path"] if rows else None
    shot = paths.ARTIFACTS / "applications" / opp["id"] / "ats_form.png"
    ctx.progress(0.3, f"Filling the mock ATS form for {label(opp)}…")
    try:
        res = await fill_and_submit(url, conn=ctx.conn, letter=doc["content_text"] or "", resume_path=resume, shot=shot)
    except SubmissionUnconfirmed as exc:
        reason = str(exc)
        need = need_effect(opp, kind="decision", title=f"Verify submission: {label(opp)}",
                           instructions=("The mock ATS submit action may have succeeded, but no application reference "
                                         "was verified. Check the ATS submission record before trying again. "
                                         "Do not submit a second application until the first attempt is resolved."),
                           application_id=app["id"], direct_url=url, priority=85,
                           payload={"decision": "ats_submission_ambiguous"})
        return RunResult(output={"ok": False, "submission_attempted": True, "stage_reason": reason},
                         effects=[{"op": "application.update", "id": app["id"],
                                   "values": {"status": "submission_attempted"}},
                                  {"op": "opp.update", "id": opp["id"], "values": {"stage_reason": reason}}, need],
                         summary=f"{label(opp)}: submission attempted; confirmation needs verification")
    except Stop as exc:
        return RunResult(output={"ok": False, "fallback_pack": True, "stage_reason": exc.reason},
                         summary=f"{label(opp)}: stopped at the form ({exc.reason}) — building a pack instead")
    except Exception as exc:  # browser missing, mock ATS down: fall back to a pack rather than retry-loop
        return RunResult(output={"ok": False, "fallback_pack": True, "stage_reason": f"browser error: {exc}"[:300]},
                         summary=f"{label(opp)}: browser failed ({type(exc).__name__}) — building a pack instead")
    effects = [{"op": "application.update", "id": app["id"],
                "values": {"status": "submitted", "submitted_at": now_iso(), "submission_ref": f"mock_ats:{res['ref']}",
                           "answers_json": res["filled"]}},
               {"op": "document.update", "id": doc["id"], "values": {"status": "sent"}}]
    return RunResult(output={"ok": True, "ref": res["ref"], "screenshot": res["screenshot"],
                             "confirmation_screenshot": res["confirmation_screenshot"]}, effects=effects,
                     summary=f"{label(opp)}: submitted on the mock ATS (ref {res['ref']}, {len(res['filled'])} fields)")
