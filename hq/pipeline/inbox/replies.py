"""Info-request replies and follow-ups: deterministic templates, then the same fact + quality gates as every other
outbound text. Only the allowed items (résumé re-send, GitHub, LinkedIn, repository links) are ever answered."""
from __future__ import annotations

from typing import Any

from hq.pipeline.draft.writer_input import doc_config
from hq.pipeline.gates.fact_deterministic import check_document
from hq.pipeline.gates.quality import check_quality

ITEMS: dict[str, dict[str, Any]] = {
    "resume": {"text": "I have attached my résumé as a PDF.", "fact_ids": ["F-NAME"]},
    "github": {"text": "My GitHub profile is https://github.com/Preritsangwan17.", "fact_ids": ["F-GITHUB"]},
    "linkedin": {"text": "My LinkedIn profile is https://www.linkedin.com/in/prerit-sangwan-1b7572304.",
                 "fact_ids": ["F-LINKEDIN"]},
    "repo": {"text": "The book recommendation system is at "
                     "https://github.com/Preritsangwan17/End-to-End-Book-Recommendation-System and the churn "
                     "prediction project is at https://github.com/Preritsangwan17/Churn-ml-model-project.",
             "fact_ids": ["F-BOOK-NAME", "F-CHURN-NAME"]},
}


def _sent(i: int, text: str, kind: str, fact_ids: list[str] | None = None, paragraph: int | None = None) -> dict:
    return {"idx": i, "text": text, "kind": kind, "fact_ids": fact_ids or [], "job_quote_ids": [],
            "paragraph": paragraph}


def recipient_name(from_name: str | None) -> str:
    first = (from_name or "").strip().split()
    if first and first[0].isalpha() and len(first[0]) > 1 and first[0].lower() not in ("the", "team", "hr", "no"):
        return first[0]
    return "Hiring Team"


def reply_sentences(items: list[str], *, recipient: str, company: str | None, role: str | None) -> list[dict]:
    out = [_sent(0, f"Dear {recipient},", "salutation")]
    about = f" about the {role} role at {company}" if role and company else (f" from {company}" if company else "")
    out.append(_sent(1, f"Thank you for your message{about}.", "logistics", paragraph=0))
    for key in items:
        spec = ITEMS[key]
        out.append(_sent(len(out), spec["text"], "claim", spec["fact_ids"], paragraph=1))
    out.append(_sent(len(out), "Please let me know if you need anything else.", "closing", paragraph=2))
    return out


def followup_sentences(*, recipient: str, company: str, role: str) -> list[dict]:
    return [_sent(0, f"Dear {recipient},", "salutation"),
            _sent(1, f"I am writing to follow up on my application for the {role} role at {company}.",
                  "logistics", paragraph=0),
            _sent(2, "I remain interested in the role and would be glad to share anything else you need.", "closing",
                  paragraph=1)]


def acknowledgement_sentences(kind: str, *, recipient: str, company: str, role: str) -> list[dict]:
    """Approval-only drafts. None accepts an offer, promises availability, or agrees to terms."""
    message = {
        "interview_invite": f"Thank you for inviting me to interview for the {role} role at {company}.",
        "assessment": f"Thank you for sharing the assessment for the {role} role at {company}.",
        "offer": f"Thank you for sending the offer for the {role} role at {company}.",
        "joining": f"Thank you for sharing the joining instructions for the {role} role at {company}.",
    }[kind]
    next_line = {
        "interview_invite": "Could you please confirm the available time slots and time zone?",
        "assessment": "I have received the instructions and will review them carefully.",
        "offer": "I will review the details carefully and respond separately.",
        "joining": "I will review the steps and follow up if anything needs clarification.",
    }[kind]
    return [_sent(0, f"Dear {recipient},", "salutation"),
            _sent(1, message, "logistics", paragraph=0),
            _sent(2, next_line, "closing", paragraph=1)]


def assemble(sentences: list[dict]) -> str:
    cfg = doc_config()
    paras: list[list[str]] = []
    key_prev: Any = object()
    for s in sentences:
        key = "salutation" if s["kind"] == "salutation" else s.get("paragraph")
        if key != key_prev:
            paras.append([])
            key_prev = key
        paras[-1].append(s["text"])
    body = "\n\n".join(" ".join(p) for p in paras)
    return f"{body}\n\n{cfg.get('signoff') or 'Best regards,'}\n{cfg.get('contact_line') or ''}".strip() + "\n"


def gate(sentences: list[dict], *, doc_kind: str, org: str | None) -> tuple[bool, list[str]]:
    """Fact rules (with citations) + the quality gate for this document type."""
    fact = check_document(sentences, require_citations=True)
    problems = [f"{v['text'][:80]}: {', '.join(x['rule'] for x in v['violations'])}"
                for v in fact.sentences if not v["passed"]]
    q = check_quality(sentences, doc_kind=doc_kind, org=org or "")
    problems += [c["message"] for c in q.checks if not c["passed"] and not (c["check"] == "names_org" and not org)]
    return not problems, problems
