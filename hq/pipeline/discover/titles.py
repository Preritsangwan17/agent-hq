"""Title prefilter (`classify.title`): keep internships, co-ops, fellowships, working-student, junior/new-grad,
part-time, contract and freelance roles in AI/ML/data/software/research; drop everything else. Deterministic
first; `uncertain` titles can go to the title_filter model. "Internal", "International" and "Internet" are not
internships (word boundaries)."""
from __future__ import annotations

import re
from dataclasses import dataclass

STUDENT = re.compile(
    r"\b(interns?|internships?|co-?op|trainee|apprentice(ship)?|fellows?|fellowships?|werkstudent|working student|"
    r"student|students|new[- ]grad(uate)?|graduate program|junior|jr\.?|entry[- ]level|early[- ]career|"
    r"part[- ]time|contract(or)?|freelance|research assistant|summer (research|program|school)|residency|"
    r"university grad|campus|placement|praktikum|stagiaire|stage)\b", re.I)
TECH = re.compile(
    r"\b(machine learning|ml|ai|a\.i\.|artificial intelligence|data|software|engineer(ing)?|developer|research(er)?|"
    r"scien(ce|tist)|analytics|analyst|nlp|computer vision|llm|genai|gen ai|deep learning|backend|back-end|frontend|"
    r"front-end|full[- ]stack|infrastructure|platform|sde|swe|applied|quant(itative)?|mlops|robotics|algorithm|"
    r"computational|technical|technology|product engineer|devops|cloud|systems|coding|code|python|safety|"
    r"security engineer|modeling|modelling|statistic(s|al))\b", re.I)
DROP = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|manager|director|head of|vp|vice president|chief|"
    r"sales|account executive|account development|account manager|business development|bdr|sdr|marketing|"
    r"recruit(er|ing)|talent acquisition|finance|financial analyst|accounting|accountant|legal|counsel|paralegal|"
    r"human resources|\bhr\b|people partner|payroll|tax|audit|customer success|customer support|support specialist|"
    r"communications|partnerships?|events?|warehouse|logistics|facilities|office|executive assistant|"
    r"procurement|brand|social media|copywriter|content writer|graphic designer|ux writer|operations associate|"
    r"ph\.?d|master'?s|mba|postdoc(toral)?|security|design|designer|ux|ui/ux|electrical|firmware|mechanical|hardware|"
    r"civil|chemical|manufacturing|asic|fpga|rf|analog|embedded|mechatronics|process engineer)\b",
    re.I)
SOFT = re.compile(r"\b(software|ml|machine learning|ai|data|research scientist|applied scientist)\b", re.I)
HARDWARE = {"electrical", "firmware", "mechanical", "hardware", "civil", "chemical", "manufacturing", "asic", "fpga",
            "rf", "analog", "embedded", "mechatronics", "process engineer"}


@dataclass(frozen=True)
class TitleDecision:
    target: bool
    uncertain: bool
    reason: str


def classify_title(title: str) -> TitleDecision:
    t = " ".join((title or "").split())
    if not t:
        return TitleDecision(False, False, "empty title")
    main = re.sub(r"\([^)]*\)", " ", t)            # "(Customer Success)" qualifies the team, not the role
    head = re.split(r"\s[-–—|]\s", main)[0]
    if head != main and STUDENT.search(head) and TECH.search(head):
        main = head                                  # "… Intern - Warsaw Security": the suffix is the team/city
    drop = DROP.search(main) or re.search(r"\b(ph\.?d|master'?s)\b", t, re.I)
    student = STUDENT.search(t)
    tech = TECH.search(t)
    if drop:
        word = drop.group(0).lower()
        # "Embedded Software Engineer Intern" stays; "Firmware Engineer Co-Op" goes
        if not (word in HARDWARE and SOFT.search(main)):
            return TitleDecision(False, False, f"not a target role ({drop.group(0)})")
    if student and re.match(r"fellows?$", student.group(0), re.I) and re.search(r"fellows program", t, re.I):
        return TitleDecision(False, True, "company fellows programme — check who it is for")
    if student and tech:
        return TitleDecision(True, False, f"{student.group(0)} · {tech.group(0)}")
    if student and not tech:
        return TitleDecision(False, True, f"{student.group(0)} but no technical keyword")
    if tech and not student:
        return TitleDecision(False, False, "technical but not student/entry level")
    return TitleDecision(False, False, "no target keywords")
