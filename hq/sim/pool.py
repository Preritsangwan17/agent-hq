"""Curated pool of plausible AI/ML/data/software roles at clearly FICTIONAL organisations (all URLs and
addresses use the reserved `.example` TLD), plus the sim-only FX table, living-cost numbers and pay maths.

Nothing here is real: these rows only ever appear with `is_simulated=1` and a SIM tag in the UI.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hq.util.timeutil import today_ist

# INR per unit of currency — rough, sim-only (the real pipeline uses hq/pipeline/verify/fx.py).
SIM_FX_INR = {"INR": 1.0, "USD": 88.0, "EUR": 103.0, "CHF": 110.0, "GBP": 118.0, "TWD": 2.85, "JPY": 0.59,
              "SGD": 68.5, "CAD": 64.0, "AED": 24.0}

HOME_CITY = "greater_noida"  # remote roles are costed against Prerit's own base


@dataclass(frozen=True)
class City:
    name: str
    country_iso2: str
    lat: float
    lon: float
    living_cost_inr: int  # provisional sim estimate for a student's month (rent share + food + transport)


CITIES: dict[str, City] = {
    "bengaluru": City("Bengaluru", "IN", 12.9716, 77.5946, 28000),
    "hyderabad": City("Hyderabad", "IN", 17.3850, 78.4867, 24000),
    "pune": City("Pune", "IN", 18.5204, 73.8567, 24000),
    "gurugram": City("Gurugram", "IN", 28.4595, 77.0266, 30000),
    "mumbai": City("Mumbai", "IN", 19.0760, 72.8777, 35000),
    "noida": City("Noida", "IN", 28.5355, 77.3910, 25000),
    "greater_noida": City("Greater Noida", "IN", 28.4744, 77.5040, 25000),
    "chennai": City("Chennai", "IN", 13.0827, 80.2707, 24000),
    "new_delhi": City("New Delhi", "IN", 28.6139, 77.2090, 30000),
    "san_francisco": City("San Francisco", "US", 37.7749, -122.4194, 280000),
    "new_york": City("New York", "US", 40.7128, -74.0060, 270000),
    "seattle": City("Seattle", "US", 47.6062, -122.3321, 230000),
    "boston": City("Boston", "US", 42.3601, -71.0589, 240000),
    "berlin": City("Berlin", "DE", 52.5200, 13.4050, 115000),
    "munich": City("Munich", "DE", 48.1351, 11.5820, 135000),
    "tubingen": City("Tübingen", "DE", 48.5216, 9.0576, 100000),
    "zurich": City("Zurich", "CH", 47.3769, 8.5417, 210000),
    "lausanne": City("Lausanne", "CH", 46.5197, 6.6323, 185000),
    "taipei": City("Taipei", "TW", 25.0330, 121.5654, 60000),
    "hsinchu": City("Hsinchu", "TW", 24.8138, 120.9675, 50000),
    "chiayi": City("Chiayi", "TW", 23.4801, 120.4491, 42000),
    "tokyo": City("Tokyo", "JP", 35.6762, 139.6503, 110000),
    "kyoto": City("Kyoto", "JP", 35.0116, 135.7681, 90000),
    "singapore": City("Singapore", "SG", 1.3521, 103.8198, 150000),
    "london": City("London", "GB", 51.5072, -0.1276, 185000),
    "cambridge_uk": City("Cambridge", "GB", 52.2053, 0.1218, 150000),
    "edinburgh": City("Edinburgh", "GB", 55.9533, -3.1883, 125000),
    "toronto": City("Toronto", "CA", 43.6532, -79.3832, 150000),
    "montreal": City("Montreal", "CA", 45.5019, -73.5674, 115000),
    "vancouver": City("Vancouver", "CA", 49.2827, -123.1207, 150000),
    "dubai": City("Dubai", "AE", 25.2048, 55.2708, 140000),
    "abu_dhabi": City("Abu Dhabi", "AE", 24.4539, 54.3773, 130000),
    "amsterdam": City("Amsterdam", "NL", 52.3676, 4.9041, 150000),
    "delft": City("Delft", "NL", 52.0116, 4.3571, 115000),
    "eindhoven": City("Eindhoven", "NL", 51.4416, 5.4697, 110000),
}


@dataclass(frozen=True)
class PaySpec:
    raw: str
    status: str = "listed"          # listed|unknown|variable|unpaid|fee_required
    min: float | None = None
    max: float | None = None
    currency: str | None = None
    period: str = "month"           # month|hour|year|unknown
    hours_per_week: float | None = None
    benefits: dict[str, bool] = field(default_factory=dict)  # housing/meals/travel


@dataclass(frozen=True)
class SimRole:
    key: str
    company: str
    slug: str
    title: str
    kind: str
    role_type: str
    city: str
    work_mode: str
    board: str                      # greenhouse|lever|ashby|careers|program_page|lab_page
    channel: str                    # email|ats_form|portal
    pay: PaySpec
    eligibility: tuple[str, str]    # (verdict, exact quote from the posting)
    job_quote: str
    summary: str
    fit: int
    deadline_days: int | None = 21  # None = rolling
    trap: str | None = None         # scam|mill|ineligible|expired|unpaid|low_pay (what verification should catch)
    scam_signal: str | None = None
    apply_local: str = "internships"
    duration_months: float | None = 3

    @property
    def apply_email(self) -> str | None:
        return f"{self.apply_local}@{self.slug}.example" if self.channel == "email" else None

    @property
    def board_label(self) -> str:
        return {"greenhouse": "Greenhouse board", "lever": "Lever board", "ashby": "Ashby board",
                "careers": "Careers page", "program_page": "Program page", "lab_page": "Lab page"}[self.board]


def _m(raw: str, lo: float, hi: float | None, cur: str, **kw: Any) -> PaySpec:
    return PaySpec(raw=raw, min=lo, max=hi if hi is not None else lo, currency=cur, **kw)


ROLES: list[SimRole] = [
    SimRole("nimbus-ml-intern", "Nimbus Labs", "nimbuslabs", "Machine Learning Intern (Summer 2027)", "internship",
            "ml", "bengaluru", "hybrid", "greenhouse", "ats_form", _m("INR 40,000/month", 40000, None, "INR"),
            ("eligible", "Open to B.Tech students in their 2nd year or above"),
            "you will prototype ranking models on real usage data with a mentor",
            "Prototype and evaluate ranking models for Nimbus Labs' document search product.", 82),
    SimRole("aurora-perception", "Aurora Robotics", "aurorarobotics", "Perception Research Intern",
            "research_internship", "ml", "munich", "onsite", "lever", "ats_form",
            _m("EUR 2,100/month", 2100, None, "EUR"),
            ("eligible", "Bachelor's or Master's students with strong Python and linear algebra"),
            "you will benchmark depth-estimation models on our warehouse robot fleet data",
            "Benchmark monocular depth models for warehouse robots.", 78, 30),
    SimRole("quillfeather-nlp", "Quillfeather AI", "quillfeather", "NLP Engineering Intern (Remote, India)",
            "internship", "ml", "bengaluru", "remote", "ashby", "email", _m("INR 35,000/month", 35000, None, "INR"),
            ("eligible", "2nd-year undergrads welcome"),
            "help us build evaluation sets for Indic-language summarisation",
            "Build evaluation sets and baselines for Indic-language summarisation.", 85, 14, apply_local="careers"),
    SimRole("lumen-data-analyst", "Lumen Grid Analytics", "lumengrid", "Data Analyst Intern — Energy Forecasting",
            "internship", "data", "pune", "onsite", "greenhouse", "ats_form",
            _m("INR 25,000/month", 25000, None, "INR"),
            ("eligible_gaps", "SQL required; exposure to time-series forecasting is a plus"),
            "you will clean smart-meter data and build weekly demand dashboards",
            "Clean smart-meter data and maintain demand-forecast dashboards.", 70, 18),
    SimRole("tessellate-werkstudent", "Tessellate Data", "tessellate", "Data Engineering Werkstudent", "part_time",
            "data", "berlin", "hybrid", "ashby", "ats_form",
            _m("EUR 15/hour, 20 h/week", 15, None, "EUR", period="hour", hours_per_week=20),
            ("ineligible", "Must be enrolled at a German university (Werkstudent status required)"),
            "you will maintain dbt models for our customer analytics warehouse",
            "Maintain dbt models and Airflow jobs for the analytics warehouse.", 71, 25, trap="ineligible",
            duration_months=6),
    SimRole("kestrel-cv", "Kestrel Vision", "kestrelvision", "Computer Vision Intern", "internship", "ml", "hsinchu",
            "onsite", "lever", "email", _m("TWD 30,000/month", 30000, None, "TWD"),
            ("eligible", "Undergraduate students of any year are welcome to apply"),
            "you will label, train and evaluate defect-detection models for semiconductor inspection",
            "Train and evaluate defect-detection models for wafer inspection images.", 80, 20),
    SimRole("marlowe-bioml", "Marlowe Bio-ML", "marlowebio", "ML for Genomics Intern", "internship", "research",
            "cambridge_uk", "onsite", "greenhouse", "ats_form", _m("GBP 2,300/month", 2300, None, "GBP"),
            ("ineligible", "Open to 2026 graduates only"),
            "you will apply sequence models to single-cell expression data",
            "Apply sequence models to single-cell expression data.", 74, 28, trap="ineligible"),
    SimRole("orchard-mlops", "Orchard Compute", "orchardcompute", "MLOps Intern", "internship", "software",
            "hyderabad", "hybrid", "lever", "ats_form", _m("INR 45,000/month", 45000, None, "INR"),
            ("eligible", "Pre-final and final year students; 2nd-years with strong projects considered"),
            "you will turn research notebooks into reproducible YAML-configured pipelines",
            "Turn research notebooks into reproducible, configurable training pipelines.", 74, 16),
    SimRole("pelican-speech", "Pelican Speech", "pelicanspeech", "Speech Recognition Research Intern",
            "research_internship", "research", "tokyo", "onsite", "careers", "email",
            _m("JPY 1,800–2,200/hour (hours set per project)", 1800, 2200, "JPY", period="hour", status="variable"),
            ("eligible", "Undergraduate or graduate students"),
            "you will study accent robustness of our Japanese–English ASR models",
            "Study accent robustness of bilingual speech recognition models.", 76, 35, apply_local="research"),
    SimRole("halcyon-rl", "Halcyon Robotics", "halcyonrobotics", "Reinforcement Learning Intern", "internship", "ml",
            "zurich", "onsite", "ashby", "ats_form", _m("CHF 3,500/month", 3500, None, "CHF"),
            ("eligible_gaps", "Prior RL coursework preferred"),
            "you will train manipulation policies in simulation before real-robot trials",
            "Train manipulation policies in simulation for a bin-picking arm.", 79, 40, duration_months=6),
    SimRole("cinder-backend", "Cinder Systems", "cindersystems", "Backend Engineering Intern (Python)", "internship",
            "software", "gurugram", "onsite", "greenhouse", "ats_form", _m("INR 30,000/month", 30000, None, "INR"),
            ("eligible", "Students graduating between 2027 and 2029"),
            "you will build internal APIs for our model-serving platform",
            "Build internal Python APIs for the model-serving platform.", 66, 12),
    SimRole("brightwater-ds", "Brightwater Analytics", "brightwater", "Data Science Intern", "internship", "data",
            "singapore", "hybrid", "lever", "ats_form", _m("SGD 1,800/month", 1800, None, "SGD"),
            ("eligible", "Open to undergraduate students"),
            "you will build churn and lifetime-value models for retail clients",
            "Churn and lifetime-value modelling for retail clients.", 72, 22, trap="low_pay"),
    SimRole("juniper-llm-eval", "Juniper Neural", "juniperneural", "LLM Evaluation Contractor (part-time, remote)",
            "contract", "ml", "san_francisco", "remote", "ashby", "email",
            _m("USD 25–35/hour (flexible hours)", 25, 35, "USD", period="hour", status="variable"),
            ("eligible", "Open to students worldwide"),
            "you will write adversarial evaluation prompts and grade model outputs",
            "Write adversarial evaluation prompts and grade model outputs.", 81, None, apply_local="contractors",
            duration_months=4),
    SimRole("vireo-clinical-nlp", "Vireo Health AI", "vireohealth", "Clinical NLP Intern", "internship", "ml",
            "boston", "onsite", "greenhouse", "ats_form", _m("USD 7,000/month", 7000, None, "USD"),
            ("ineligible", "Requires US work authorization; we are unable to sponsor visas"),
            "you will extract medication events from de-identified clinical notes",
            "Extract medication events from de-identified clinical notes.", 73, 30, trap="ineligible"),
    SimRole("saffron-bi", "Saffron Data Co.", "saffrondata", "Business Intelligence Intern", "internship", "data",
            "mumbai", "onsite", "careers", "email", _m("INR 20,000/month", 20000, None, "INR"),
            ("eligible", "Any undergraduate student"),
            "you will build weekly sales dashboards in SQL and Python",
            "Build weekly sales dashboards for regional teams.", 55, 10, trap="low_pay"),
    SimRole("tidewell-geo", "Tidewell Maps", "tidewellmaps", "Geospatial ML Intern", "internship", "ml", "amsterdam",
            "hybrid", "lever", "ats_form", _m("EUR 1,600/month", 1600, None, "EUR"),
            ("eligible_gaps", "Some GIS experience is helpful but not required"),
            "you will segment cycle lanes from aerial imagery",
            "Segment cycle lanes from aerial imagery for city planners.", 73, 26),
    SimRole("obsidian-search", "Obsidian Search", "obsidiansearch", "Search Relevance Intern", "internship", "ml",
            "toronto", "hybrid", "greenhouse", "ats_form",
            _m("CAD 28/hour, 40 h/week", 28, None, "CAD", period="hour", hours_per_week=40),
            ("eligible", "Open to undergraduate students in any year"),
            "you will run offline relevance experiments on query logs",
            "Offline relevance experiments and learning-to-rank baselines.", 77, 24, duration_months=4),
    SimRole("larkspur-quant", "Larkspur Finance ML", "larkspurml", "Quant Research Intern", "internship", "research",
            "london", "onsite", "greenhouse", "ats_form", _m("GBP 45,000/year (pro rata)", 45000, None, "GBP",
                                                              period="year"),
            ("ineligible", "Penultimate-year students only (graduating in 2027)"),
            "you will test signal-decay hypotheses on historical market data",
            "Test signal-decay hypotheses on historical market data.", 68, 19, trap="ineligible", duration_months=2.5),
    SimRole("meridian-mobility", "Meridian Mobility", "meridianmobility", "Mobility Data Science Intern",
            "internship", "data", "dubai", "onsite", "lever", "ats_form", _m("AED 7,000/month", 7000, None, "AED"),
            ("eligible", "Undergraduates in CS or Data Science; any year"),
            "you will forecast ride demand around metro stations",
            "Forecast ride demand around metro stations.", 69, 21),
    SimRole("quokka-game-ai", "Quokka Games AI", "quokkagames", "Game AI Programming Intern", "internship",
            "software", "montreal", "onsite", "ashby", "ats_form",
            _m("CAD 24/hour, 37.5 h/week", 24, None, "CAD", period="hour", hours_per_week=37.5),
            ("eligible_gaps", "C++ experience preferred"),
            "you will prototype utility-based NPC behaviours",
            "Prototype utility-based NPC behaviours for an open-world title.", 64, 33, duration_months=4),
    SimRole("fennec-secml", "Fennec Security ML", "fennecsec", "ML Security Research Intern", "research_internship",
            "research", "edinburgh", "onsite", "careers", "email", _m("GBP 2,000/month", 2000, None, "GBP"),
            ("eligible", "Open to undergraduates"),
            "you will measure how data poisoning affects small recommendation models",
            "Measure data-poisoning effects on small recommendation models.", 75, 27, apply_local="research"),
    SimRole("ember-oak-fellowship", "Ember & Oak Research", "emberoak", "Summer Research Fellowship in Interpretability",
            "fellowship", "research", "lausanne", "onsite", "program_page", "portal",
            _m("CHF 1,600/month + housing + meals + travel", 1600, None, "CHF",
               benefits={"housing": True, "meals": True, "travel": True}),
            ("eligible", "Undergraduates who will have completed at least two years of study by June 2027"),
            "fellows spend ten weeks on a mentored interpretability project",
            "Ten-week mentored interpretability fellowship with housing and travel covered.", 88, 45,
            duration_months=2.5),
    SimRole("solstice-climate", "Solstice Climate AI", "solsticeclimate", "Climate Data Science Intern",
            "internship", "data", "vancouver", "hybrid", "lever", "ats_form",
            PaySpec(raw="Competitive stipend (not listed)", status="unknown", period="unknown"),
            ("eligible", "Open to students in any year of a CS or environmental science degree"),
            "you will downscale regional precipitation forecasts",
            "Downscale regional precipitation forecasts with ML.", 71, 29),
    SimRole("arcadia-mt", "Arcadia Language Lab", "arcadia-lab", "Undergraduate Research Internship — Low-resource MT",
            "research_internship", "research", "taipei", "onsite", "lab_page", "email",
            _m("TWD 18,000/month + dorm + meal card + airfare", 18000, None, "TWD",
               benefits={"housing": True, "meals": True, "travel": True}),
            ("eligible", "Undergraduate students from partner countries, 2nd year and above"),
            "interns join a small team building translation models for low-resource languages",
            "Build translation models for low-resource languages in a university lab.", 84, 38, apply_local="prof.lin",
            duration_months=2),
    SimRole("hoshizora-vurp", "Hoshizora Institute of AI", "hoshizora", "Visiting Undergraduate Research Program",
            "program", "research", "kyoto", "onsite", "program_page", "portal",
            _m("JPY 150,000/month + housing + meals + travel", 150000, None, "JPY",
               benefits={"housing": True, "meals": True, "travel": True}),
            ("eligible", "Undergraduate students (2nd year and above)"),
            "participants join a lab for eight weeks and present a poster at the end",
            "Eight-week visiting research program with stipend, housing and travel.", 86, 50, duration_months=2),
    SimRole("glacierpoint-platform", "Glacierpoint AI", "glacierpoint", "ML Platform Contractor (Remote, 6 months)",
            "contract", "software", "seattle", "remote", "ashby", "email", _m("USD 3,000/month for 20 h/week", 3000,
                                                                             None, "USD"),
            ("eligible", "Open to students; 20 hours per week"),
            "you will harden our feature-store ingestion jobs",
            "Harden feature-store ingestion jobs for an ML platform team.", 72, None, apply_local="contracts",
            duration_months=6),
    SimRole("ironbark-sde", "Ironbark Cloud", "ironbarkcloud", "Final-Year SDE Intern (PPO)", "internship",
            "software", "chennai", "onsite", "greenhouse", "ats_form", _m("INR 50,000/month", 50000, None, "INR"),
            ("ineligible", "Only 7th/8th semester students (Batch of 2027)"),
            "you will ship features on our storage control plane",
            "Ship features on a storage control plane.", 62, 15, trap="ineligible", duration_months=6),
    SimRole("copperleaf-cv", "Copperleaf Retail AI", "copperleaf", "Retail Computer Vision Intern", "internship",
            "ml", "bengaluru", "onsite", "lever", "ats_form", _m("INR 30,000–40,000/month", 30000, 40000, "INR"),
            ("eligible", "Open to all undergraduate years"),
            "you will count shelf gaps from store camera frames",
            "Detect shelf gaps from in-store camera frames.", 77, 17),
    SimRole("morrow-recsys", "Morrow Media", "morrowmedia", "Recommender Systems Intern", "internship", "ml", "noida",
            "hybrid", "careers", "email", _m("INR 25,000/month", 25000, None, "INR"),
            ("eligible", "2nd and 3rd year B.Tech students"),
            "you will improve our KNN-based 'read next' recommendations",
            "Improve 'read next' recommendations for a publishing app.", 90, 13),
    SimRole("starling-junior-ml", "Starling Fintech", "starlingfintech", "Junior ML Engineer (0–1 yrs)", "job", "ml",
            "bengaluru", "onsite", "ashby", "ats_form",
            _m("₹8–10 LPA", 800000, 1000000, "INR", period="year"),
            ("ineligible", "B.Tech 2026/2027 graduates; full-time role"),
            "you will own fraud-model monitoring end to end",
            "Own fraud-model monitoring for card transactions.", 67, 20, trap="ineligible", duration_months=None),
    SimRole("skillforge-virtual", "SkillForge Virtual Internships", "skillforge-vi",
            "Data Science Virtual Internship + Certificate", "internship", "data", "noida", "remote", "careers",
            "email", PaySpec(raw="Stipend up to ₹15,000 (registration fee ₹1,499, refundable)",
                             status="fee_required", min=0, max=15000, currency="INR"),
            ("eligible", "Anyone can apply"), "complete 4 guided projects and receive a certificate",
            "Guided 'virtual internship' with a paid registration step.", 40, 7, trap="scam",
            scam_signal="asks for a ₹1,499 'registration fee' before onboarding", apply_local="enroll"),
    SimRole("certipath-ai", "CertiPath Academy", "certipath", "AI Internship Program (Certificate Only)", "program",
            "ml", "new_delhi", "remote", "careers", "portal",
            PaySpec(raw="Unpaid; certificate provided; training fee ₹2,999", status="fee_required", min=0, max=0,
                    currency="INR"),
            ("eligible", "Open to all students"), "earn an industry-recognised AI certificate",
            "Certificate-only 'internship' that charges a training fee.", 35, 10, trap="mill",
            scam_signal="matches a known internship mill; certificate-only wording and a training fee"),
    SimRole("quickhire-ml", "QuickHire Global Solutions", "quickhire-global", "Remote ML Engineer Intern — Immediate Joining",
            "internship", "ml", "dubai", "remote", "careers", "email", _m("USD 2,000/month", 2000, None, "USD"),
            ("eligible", "Freshers and students welcome"), "immediate joining, no interview required",
            "Vague remote role promising pay without an interview.", 45, 5, trap="scam",
            scam_signal="recruiter writes from a free-mail address and asks for Aadhaar and bank details before any "
                        "interview", apply_local="hr.desk"),
    SimRole("brightpath-python", "BrightPath InternHub", "brightpath-hub", "Python Developer Internship (Work From Home)",
            "internship", "software", "pune", "remote", "careers", "email",
            PaySpec(raw="₹5,000/month after completing paid training", status="fee_required", min=5000, max=5000,
                    currency="INR"),
            ("eligible", "Any graduate or student"), "complete our paid bootcamp to unlock the internship",
            "Internship gated behind a paid bootcamp.", 38, 9, trap="mill",
            scam_signal="stipend only after 'paid training' — a known mill pattern"),
    SimRole("aster-robot-learning", "Aster Robotics Lab", "asterlab", "Robot Learning Research Intern",
            "research_internship", "research", "delft", "onsite", "lab_page", "email",
            _m("EUR 1,200/month", 1200, None, "EUR"),
            ("eligible", "BSc students with Python experience"),
            "you will collect teleoperation demos for imitation learning",
            "Collect teleoperation demonstrations for imitation learning.", 78, -5, trap="expired",
            apply_local="lab.admin"),
    SimRole("nimbus-applied-winter", "Nimbus Labs", "nimbuslabs", "Applied Scientist Intern (Winter)", "internship",
            "research", "bengaluru", "onsite", "greenhouse", "ats_form", _m("INR 60,000/month", 60000, None, "INR"),
            ("eligible", "Undergraduate and graduate students"),
            "you will run retrieval-augmented QA experiments",
            "Retrieval-augmented QA experiments for enterprise search.", 80, -2, trap="expired"),
    SimRole("harbor-civic-data", "Harbor Civic Data", "harborcivic", "Data for Good Volunteer Intern", "internship",
            "data", "new_delhi", "hybrid", "careers", "email",
            PaySpec(raw="Unpaid (certificate of completion)", status="unpaid", min=0, max=0, currency="INR"),
            ("eligible", "Open to all students"), "you will clean public transport datasets for civic dashboards",
            "Volunteer data cleaning for civic transport dashboards.", 58, 20, trap="unpaid", apply_local="volunteer"),
    SimRole("wrenfield-ai", "Wrenfield Labs", "wrenfield", "AI Research Intern", "research_internship", "research",
            "eindhoven", "onsite", "lab_page", "email",
            PaySpec(raw="Stipend as per university norms", status="unknown", period="unknown"),
            ("eligible", "Bachelor students in CS, EE or mathematics"),
            "you will evaluate small vision-language models on factory manuals",
            "Evaluate small vision-language models on technical manuals.", 74, 31, apply_local="research"),
    SimRole("polaris-edge", "Polaris Edge AI", "polarisedge", "Edge AI Intern", "internship", "ml", "hyderabad",
            "onsite", "lever", "ats_form", PaySpec(raw="Stipend: competitive", status="unknown", period="unknown"),
            ("eligible", "B.Tech students, 2nd year onwards"),
            "you will quantise detection models for low-power cameras",
            "Quantise detection models for low-power cameras.", 68, 23),
    SimRole("lattice-loom-evals", "Lattice & Loom AI", "latticeloom", "Research Engineering Intern — Evaluation",
            "internship", "ml", "san_francisco", "onsite", "ashby", "ats_form",
            _m("USD 9,500/month", 9500, None, "USD"),
            ("eligible_gaps", "International students considered with J-1 sponsorship"),
            "you will build evaluation harnesses for long-context models",
            "Build evaluation harnesses for long-context language models.", 83, 34),
    SimRole("gossamer-ads-ml", "Gossamer Labs", "gossamerlabs", "Applied ML Intern (Ads)", "internship", "ml",
            "new_york", "hybrid", "greenhouse", "ats_form",
            _m("USD 45/hour, 40 h/week", 45, None, "USD", period="hour", hours_per_week=40),
            ("eligible_gaps", "Visa sponsorship available (J-1) for international students"),
            "you will test calibration methods for click-through models",
            "Calibration experiments for click-through-rate models.", 70, 26),
    SimRole("dunebridge-arabic-nlp", "Dunebridge AI Institute", "dunebridge", "Visiting Student Researcher — Arabic NLP",
            "research_internship", "research", "abu_dhabi", "onsite", "program_page", "portal",
            _m("AED 4,000/month + housing + meals + travel", 4000, None, "AED",
               benefits={"housing": True, "meals": True, "travel": True}),
            ("eligible", "Undergraduates with a research interest in NLP"),
            "visiting students join a group working on dialectal Arabic speech and text",
            "Visiting research on dialectal Arabic NLP with full support.", 80, 42, duration_months=3),
    SimRole("lotus-peak-mas", "Lotus Peak Lab", "lotuspeak", "Visiting Research Intern — Multi-agent Systems",
            "research_internship", "research", "chiayi", "onsite", "lab_page", "email",
            _m("TWD 15,000/month + dorm", 15000, None, "TWD", benefits={"housing": True}),
            ("eligible", "Undergraduate students with programming experience"),
            "interns implement coordination algorithms for small robot swarms",
            "Implement coordination algorithms for small robot swarms.", 81, 36, apply_local="prof.chen"),
    SimRole("neckarwerk-probml", "Neckarwerk AI", "neckarwerk", "Probabilistic ML Research Intern",
            "research_internship", "research", "tubingen", "onsite", "careers", "email",
            _m("EUR 1,800/month", 1800, None, "EUR"),
            ("eligible", "Undergraduate students with a strong maths background"),
            "you will compare Bayesian deep-learning baselines on tabular data",
            "Compare Bayesian deep-learning baselines on tabular data.", 79, 30, apply_local="jobs"),
]
ROLES_BY_KEY = {r.key: r for r in ROLES}


def role_for_canonical_key(canonical_key: str) -> SimRole | None:
    """Canonical keys are 'sim:<role key>:<requisition>'."""
    parts = canonical_key.split(":")
    return ROLES_BY_KEY.get(parts[1]) if len(parts) >= 3 and parts[0] == "sim" else None


def compute_pay(role: SimRole) -> dict[str, Any]:
    """All pay columns for an opportunity (CONTRACT §5 Pay semantics), from the sim FX and living-cost tables."""
    p = role.pay
    city = CITIES[HOME_CITY if role.work_mode == "remote" else role.city]
    fx = SIM_FX_INR.get(p.currency or "", None)
    out: dict[str, Any] = {
        "pay_raw": p.raw, "pay_status": p.status, "pay_min": p.min, "pay_max": p.max, "pay_currency": p.currency,
        "pay_period": p.period, "fx_rate": fx if p.currency and p.currency != "INR" else (1.0 if fx else None),
        "fx_date": today_ist().isoformat() if fx else None,
        "living_cost_monthly_inr": city.living_cost_inr,
        "living_cost_basis": ("sim: remote — Prerit's base (Greater Noida)" if role.work_mode == "remote"
                              else f"sim: {city.name} student estimate"),
        "living_cost_confidence": "provisional",
        "pay_monthly_local_min": None, "pay_monthly_local_max": None, "pay_monthly_inr_min": None,
        "pay_monthly_inr_mid": None, "pay_monthly_inr_max": None, "pay_hourly_inr_min": None,
        "pay_hourly_inr_max": None, "pay_ratio": None, "hours_per_week": p.hours_per_week,
    }
    benefits: dict[str, Any] = dict(p.benefits)
    if p.status in ("unknown",) or fx is None or p.min is None:
        out["benefits_json"] = benefits
        return out
    lo, hi = p.min, p.max if p.max is not None else p.min
    if p.period == "hour":
        out["pay_hourly_inr_min"] = round(lo * fx, 2)
        out["pay_hourly_inr_max"] = round(hi * fx, 2)
        if p.hours_per_week is None:  # never assume 40 h
            out["pay_status"] = "variable"
            out["benefits_json"] = benefits
            return out
        factor = p.hours_per_week * 52 / 12
        mlo, mhi = lo * factor, hi * factor
    elif p.period == "year":
        mlo, mhi = lo / 12, hi / 12
    else:
        mlo, mhi = lo, hi
    out["pay_monthly_local_min"], out["pay_monthly_local_max"] = round(mlo, 2), round(mhi, 2)
    inr_lo, inr_hi = round(mlo * fx), round(mhi * fx)
    out["pay_monthly_inr_min"], out["pay_monthly_inr_max"] = inr_lo, inr_hi
    out["pay_monthly_inr_mid"] = round((inr_lo + inr_hi) / 2)
    if benefits:
        benefits["allowance_inr"] = inr_lo
    if inr_lo and city.living_cost_inr:
        out["pay_ratio"] = round(inr_lo / city.living_cost_inr, 2)
    out["benefits_json"] = benefits
    return out


def is_funded_program(role: SimRole, min_inr: float) -> bool:
    b = role.pay.benefits
    pay = compute_pay(role)
    return bool(b.get("housing") and b.get("meals") and b.get("travel")
                and (pay["pay_monthly_inr_min"] or 0) >= min_inr)
