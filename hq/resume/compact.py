"""Compact one-page résumé with fpdf2 core fonts (re-implements the lost script): same approved content, tighter
layout, no browser needed. Core fonts are Latin-1, so a few typographic characters are mapped to ASCII."""
from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

from hq.resume.content import content

ASCII = str.maketrans({"–": "-", "—": "-", "·": "|", "’": "'", "“": '"', "”": '"', "…": "..."})


def _t(s: str) -> str:
    return s.translate(ASCII).encode("latin-1", "replace").decode("latin-1")


def build_compact(out_path: Path, *, summary: str, order: list[str]) -> Path:
    c = content()
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=False)
    pdf.set_margins(14, 12, 14)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 17)
    pdf.cell(0, 8, _t(c["name"]), new_x="LMARGIN", new_y="NEXT")
    ct = c["contact"]
    pdf.set_font("Helvetica", "", 8.6)
    pdf.cell(0, 4.6, _t(" | ".join([ct["email"], "linkedin.com/in/prerit-sangwan-1b7572304",
                                     "github.com/Preritsangwan17", *ct.get("extras", [])])), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1.5)
    pdf.set_font("Helvetica", "", 9.4)
    pdf.multi_cell(0, 4.6, _t(summary), new_x="LMARGIN", new_y="NEXT")

    def heading(text: str) -> None:
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 9.6)
        pdf.cell(0, 5, _t(text.upper()), new_x="LMARGIN", new_y="NEXT")
        y = pdf.get_y()
        pdf.set_draw_color(150, 150, 150)
        pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
        pdf.ln(1)

    heading("Education")
    ed = c["education"]
    pdf.set_font("Helvetica", "", 9.2)
    pdf.cell(0, 4.6, _t(f"{ed['school']} - {ed['degree']} ({ed['status']})"), new_x="LMARGIN", new_y="NEXT")
    heading("Projects")
    for key in order:
        p = c["projects"][key]
        pdf.set_font("Helvetica", "B", 9.4)
        pdf.cell(150, 4.8, _t(p["title"]))
        pdf.set_font("Helvetica", "", 8.6)
        pdf.cell(0, 4.8, _t(p["date"]), align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "I", 8.4)
        pdf.cell(0, 4.2, _t(p["tech"] + "  " + p["url"]), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 8.8)
        for b in p["bullets"]:
            pdf.set_x(pdf.l_margin + 2)
            pdf.multi_cell(0, 4.3, _t("- " + b["text"]), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
    heading("Skills")
    for s in c["skills"]:
        pdf.set_font("Helvetica", "B", 8.8)
        pdf.cell(26, 4.4, _t(s["label"] + ":"))
        pdf.set_font("Helvetica", "", 8.8)
        pdf.multi_cell(0, 4.4, _t(s["value"]), new_x="LMARGIN", new_y="NEXT")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))
    return out_path
