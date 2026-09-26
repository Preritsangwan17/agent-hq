# Agent HQ: inventory of existing work (read-only)

**Paths used below**
- `P` = `/Users/preritsangwan/Library/Application Support/Claude/scratch-workspaces/53fd0e06-f0d3-4ac6-9bac-9b0546625df8/8d474ecb-3352-4f4e-8ce0-81d2e005fcc9/scratch-2026-09-26-25af46/applications`
- `S` = `/private/tmp/claude-501/-Users-preritsangwan-Library-Application-Support-Claude-scratch-workspaces-53fd0e06-f0d3-4ac6-9bac-9b0546625df8-8d474ecb-3352-4f4e-8ce0-81d2e005fcc9-scratch-2026-09-26-25af46/e1eef2d5-323e-4801-89ea-94d033e49932/scratchpad`

The project folder is not a git repo. Nothing was modified, and no `__pycache__` was created.

---

## 1. Project folder files (`P`)

| File | Purpose / contents |
|---|---|
| `P/jobs.json` (9,225 B) | List of the 10 target jobs (see §2). **No script reads it except `draft_letters.py`.** |
| `P/draft_letters.py` (4,052 B) | Drafts cover letters with a local MLX Qwen3 model and writes `P/drafts/<id>.txt` (see §4). |
| `P/letters.py` (11,119 B) | The final, fact-checked letters in a `LETTERS` dict, plus `SIGN`, `BOOK` and `CHURN` URL constants (see §3). |
| `P/build.py` (6,959 B) | For each application: writes `resume.html`, prints it to PDF with headless Chrome, and writes the letter file (see §5). |
| `P/drafts/01-readyly.txt` … `10-epfl.txt` (10 files) | Raw LLM drafts (1.3–1.7 KB each). They include **`07-codingninjas.txt`**, which has no final version (see note below). |
| `P/00-base/` | `resume.html` (summary "…builds end-to-end machine learning projects in Python."; project order book, churn) and `Prerit_Sangwan_Resume.pdf`. No letter. |
| `P/01-readyly/` | `resume.html`, `Prerit_Sangwan_Resume.pdf`, `cover_letter.txt` |
| `P/02-logphase/` | `resume.html`, PDF, `cover_letter.txt` |
| `P/03-reducate/` | `resume.html` (**project order churn, book**), PDF, `cover_letter.txt` |
| `P/04-outlier/` | `resume.html`, PDF, `profile_summary.txt` (a profile blurb, not a letter) |
| `P/05-stripe/` | `resume.html`, PDF, `cover_letter.txt` |
| `P/06-pharmaand/` | `resume.html`, PDF, `cover_letter.txt` |
| `P/07-nccu-teep/` | `resume.html`, `Prerit_Sangwan_Resume.pdf` (Chrome), **`Prerit_Sangwan_Resume_compact.pdf`** (fpdf-style, see §5), `email.txt` (cold email to "Professor Chiu", MARS lab, TEEP) |
| `P/08-mlh/` | `resume.html`, PDF, `cover_letter.txt` |
| `P/09-srfp/` | `resume.html`, PDF, `research_statement.txt` |
| `P/10-epfl/` | `resume.html`, PDF, `cover_letter.txt` |

**Checks run**
- Every letter file on disk is byte-identical to `LETTERS[key]`.
- All 11 résumé PDFs are one page, A4, produced by Skia/PDF m153 (HeadlessChrome/153).
- The `resume.html` files differ only in the summary line and the project order.

**Discrepancy:** `jobs.json` and `drafts/` use id `07-codingninjas` (Coding Ninjas GenAI Intern). `letters.py`, `build.py` and the folders use **`07-nccu-teep`** instead. Coding Ninjas was dropped and has no folder or final letter. The NCCU TEEP target is not in `jobs.json`. No file records why.

---

## 2. `jobs.json`

**Schema:** a list of objects with keys `id, company, role, location, pay, apply, about, angle, project, resume_focus`. `project` is always `"book"` except `03-reducate`, which is `"churn"`.

| id | company | role | pay | apply |
|---|---|---|---|---|
| 01-readyly | Readyly | Product Engineer Intern - AI Agentic Systems | INR 25,000/month | https://in.linkedin.com/jobs/view/product-engineer-intern-%E2%80%93-ai-agentic-systems-at-readyly-4468467368 |
| 02-logphase | LogPhase | Machine Learning Intern | INR 25,000 - 40,000/month | https://internshala.com/internship/detail/work-from-home-machine-learning-internship-at-logphase1789982327 |
| 03-reducate | Reducate.ai | Data Science Intern | INR 15,000/month | https://internshala.com/internship/detail/work-from-home-data-science-internship-at-reducateai1790182395 |
| 04-outlier | Outlier | Coding Expertise for AI Training (India) | USD 13.25 - 27.50/hour (per Outlier's posting) | https://app.outlier.ai/en/expert/opportunities/4494070005 |
| 05-stripe | Stripe | Software Engineer, Intern | Not listed | https://stripe.com/jobs/listing/software-engineer-intern/8031833 |
| 06-pharmaand | pharma& | AI & Machine Learning Intern | INR 15,000/month | https://in.linkedin.com/jobs/view/ai-machine-learning-intern-at-pharma-4469849859 |
| 07-codingninjas | Coding Ninjas | GenAI Intern | Not listed | https://in.linkedin.com/jobs/view/genai-intern-at-coding-ninjas-4468561627 |
| 08-mlh | MLH Fellowship (Major League Hacking) | MLH Fellow (remote, 12 weeks) | Need-based stipend, amount set by track and country | https://fellowship.mlh.com/ |
| 09-srfp | Indian Academy of Sciences, INSA and NASI | Summer Research Fellowship Programme 2027 | Fellowship (amount not verified) | https://webjapps.ias.ac.in/fellowship2027/index.html |
| 10-epfl | EPFL, School of Computer and Communication Sciences | Summer@EPFL 2027 research internship | Not verified | https://summer.epfl.ch/apply.html |

The `angle` fields contain facts that are **not** in the FACTS sheet, and these reached the drafts. Examples: "Gurugram is close to his university in the NCR" and "20 hours/week part-time fits alongside his studies".

---

## 3. `letters.py`: LETTERS keys and output file names (mapping from `build.py`)

| LETTERS key | File written by build.py |
|---|---|
| 01-readyly, 02-logphase, 03-reducate, 05-stripe, 06-pharmaand, 08-mlh, 10-epfl | `cover_letter.txt` |
| 04-outlier | `profile_summary.txt` |
| 07-nccu-teep | `email.txt` (starts with a `Subject:` line) |
| 09-srfp | `research_statement.txt` |

`00-base` is in `TAILOR` but not in `LETTERS`, so it gets no letter. Constants:
- `SIGN`: name, email, LinkedIn and GitHub.
- `BOOK`: `https://github.com/Preritsangwan17/End-to-End-Book-Recommendation-System`
- `CHURN`: `https://github.com/Preritsangwan17/Churn-ml-model-project`

The 10-epfl letter uses its own "Sincerely" sign-off without LinkedIn.

---

## 4. `draft_letters.py`

**FACTS, verbatim:**
```
CANDIDATE FACTS (the ONLY facts you may use; do not add any other skill, tool, grade, date, award or experience):
- Name: Prerit Sangwan. Indian citizen. Email sangwanprerit40@gmail.com.
- LinkedIn: https://www.linkedin.com/in/prerit-sangwan-1b7572304 . GitHub: https://github.com/Preritsangwan17
- Education: 2nd-year B.Tech in Computer Science and Engineering (AI/ML specialisation) at Bennett University, India. No degree yet. No prior internship or job.
- Project "End-to-End Book Recommendation System" (June 2026), https://github.com/Preritsangwan17/End-to-End-Book-Recommendation-System :
  item-based collaborative filtering on the Book-Crossing dataset (1.15 million ratings, 271K books); kept users with 200+ ratings and books with 50+ ratings,
  giving a 742-book by 888-user rating matrix; k-nearest-neighbours model in scikit-learn on a SciPy sparse CSR matrix returning the 5 most similar books;
  4-stage pipeline (ingestion, validation, transformation, training) driven by a YAML config with custom logging and exception handling; ingestion falls back
  to local data if the download fails; Streamlit web app that retrains the model and shows 5 recommendations with cover images; cosine-similarity prototype in Jupyter.
- Project "Telco Customer Churn Prediction" (January 2026), https://github.com/Preritsangwan17/Churn-ml-model-project :
  IBM Telco Customer Churn dataset (7,043 customers, cleaned to 7,032); one-hot encoded categorical fields and binned tenure into 12-month groups (50 features);
  trained a Random Forest classifier (100 trees) and saved the model.
- Skills shown in code: Python, pandas, NumPy, scikit-learn, SciPy sparse matrices, Streamlit, Jupyter, Git/GitHub, YAML config.
- He has NOT used: SQL, PyTorch, TensorFlow, LLM APIs, agent frameworks, cloud, Docker, knowledge graphs. Never imply he has.
- No model accuracy numbers exist. Never state accuracy, users, speed-ups or impact numbers.
- Willing to relocate. Open to learning on the job.
```

**How it runs the model**
- **Model id:** `MODEL = "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-DWQ"`
- **Imports:** `from mlx_lm import generate, load` and `from mlx_lm.sample_utils import make_sampler`
- **Steps:**
  1. `model, tokenizer = load(MODEL)`
  2. `sampler = make_sampler(temp=0.4, top_p=0.9)`
  3. For each job: `messages = [system: "You write honest, specific internship cover letters. You never invent facts.", user: prompt_for(job)]`
  4. `text = tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)`
  5. `generate(model, tokenizer, prompt=text, max_tokens=600, sampler=sampler)`
  6. Writes `drafts/{id}.txt` and prints the word count.
- **Prompt:** `prompt_for(job)` combines FACTS, then JOB (company, role, location, about, angle), then RULES.
- **RULES:** 170–230 words, 3–4 paragraphs, fixed sign-off, "Dear Hiring Team," (or "Dear Selection Committee," for fellowships and research programmes), the relevant GitHub link once, no clichés such as "I am writing to express", no invented facts.

**How the drafts broke the rules**
- 6 of 10 drafts use "I am writing to express": 01, 02, 06, 08, 09, 10.
- 02-logphase has no project link and runs 235 body words.
- 04 and 10 are under 170 words (153 and 158).
- 08, 09 and 10 use "Dear Hiring Team" although they are fellowships or research programmes.

---

## 5. `build.py`

**TAILOR** (`key: (summary, project order)`):
- 00-base: "…builds end-to-end machine learning projects in Python." — book, churn
- 01-readyly: "…builds complete Python workflows, from data pipeline to user-facing app; keen to learn LLM agents on real product work." — book, churn
- 02-logphase: "…focused on data cleaning, deduplication and reproducible Python pipelines." — book, churn
- 03-reducate: "…hands-on data science projects in classification and recommendation using pandas and scikit-learn." — **churn, book**
- 04-outlier: "…writes structured Python in every project." — book, churn
- 05-stripe: "…writes modular, config-driven Python with logging and error handling; interested in ML inside real systems." — book, churn
- 06-pharmaand: "…two ML projects I can walk through in detail: a collaborative-filtering recommender and a churn classifier." — book, churn
- 07-nccu-teep: "…interested in recommender systems, retrieval and learning from sparse data." — book, churn
- 08-mlh: "…ready to move from solo projects to collaborative open-source work." — book, churn
- 09-srfp: "…interested in research on recommender systems and learning from sparse data." — book, churn
- 10-epfl: "…seeking first research experience in recommender systems and sparse data." — book, churn

Every summary starts with "2nd-year Computer Science (AI/ML) student".

**Other constants and `resume_html()`**
- `BOOK` and `CHURN` are hardcoded HTML project blocks: 5 bullets for the book project, 2 for churn.
- `SKILLS_DEFAULT` has three rows: Language, ML and data, Tools.
- `resume_html(summary, order)` builds an HTML page containing:
  - the CSS (A4 page, 14 mm × 15 mm margins, 10.3 pt font)
  - the name and contact line ("Indian citizen · Open to relocation")
  - the summary, escaped with `html.escape`
  - Education (Bennett University, "2nd year, in progress")
  - Projects in the given order, then Skills

**Chrome call**
```
["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--headless=new", "--disable-gpu",
 "--no-pdf-header-footer", f"--print-to-pdf={pdf}", page.as_uri()]   # check=True, capture_output=True
```

**Outputs per TAILOR key:** `<key>/resume.html`, `<key>/Prerit_Sangwan_Resume.pdf`, and the letter file if the key is in LETTERS.

**Compact PDF:** `P/07-nccu-teep/Prerit_Sangwan_Resume_compact.pdf` (3,063 B) was **not produced by build.py**. No script on disk generates it; it came from an inline fpdf script that was not saved. Evidence:
- The file is PDF-1.3 with core Type1 Helvetica fonts, while the Chrome PDFs are PDF-1.4 with Skia fonts.
- Its `/Info` holds only a CreationDate (26 Sep 2026, 18:43:45 IST).
- It has link annotations to both repos.

Its text content matches the 07 résumé (same summary, bullets and skills). The reason it was made (for example an email attachment size limit) is not recorded.

`S/resume_b64.txt` is the base64 of `P/07-nccu-teep/Prerit_Sangwan_Resume.pdf`. It decodes byte-identical, 59,224 B.

---

## 6. Drafts vs corrected letters: sentence-level fact-check gold pairs

The labels are judged against FACTS plus the repo code. The code confirms `drop_duplicates`, users with `value_counts() > 200` (strictly more than 200, while FACTS says "200+"), books with `>= 50`, the local-data fallback, and `NearestNeighbors(algorithm="brute")` on `csr_matrix`. **The Dockerfile in the book repo is empty (0 bytes).**

### 01-readyly
| Draft sentence (bad) | Reason |
|---|---|
| "…demonstrates my ability to design and **deploy** a complete pipeline from data ingestion to model training and user-facing application using Streamlit." | No deployment: the Streamlit app runs locally, there is no hosting, and "cloud" is on the NOT-used list. The final says "structure code so a whole workflow can be rerun end to end". |
| "I am confident that my hands-on experience with data pipelines and **model deployment** will help me quickly adapt…" | "Model deployment" is unsupported. |
| "…a YAML-driven configuration system—skills that **align well with the technical requirements** of your role." | Overclaim: the role wants LLM APIs, agent frameworks, React/Node and AWS, none of which he has. |
| "I am available to work 20 hours per week remotely from India and am happy to relocate if needed." | Availability commitment not in FACTS (it leaked from the `angle` field). Removed. |
| "I am writing to express my interest…" / "I have built a strong foundation in Python and machine learning tools." | Banned cliché; vague puffery. |

### 02-logphase
| Draft sentence (bad) | Reason |
|---|---|
| "…I have worked on projects that align well with the data cleaning and **knowledge graph extension** aspects of your role." | Implies knowledge-graph work, which FACTS lists as NOT used. The final states he hasn't worked with knowledge graphs or LLMs. |
| "…reducing a **1.15 million rating matrix** to a 742-book by 888-user matrix…" | Mischaracterised: 1.15M is a count of ratings, not a matrix. The final says "(1.15 million ratings)". |
| "In my 'Telco Customer Churn Prediction' project, I encoded categorical variables and **binned numerical features**…" | Only tenure was binned (plural overgeneralisation). |
| "I also built a **pipeline for model training and deployment** using YAML configuration and Streamlit…" | "Deployment" is unsupported. Placed right after the churn sentence, the pipeline is **credited to the wrong project** (it belongs to the book recommender). |
| "These experiences have strengthened my ability to work with structured data and build **scalable** ML workflows." | "Scalable" is unsupported. |
| (no GitHub link at all) | Breaks the RULES; the final adds the BOOK link. |

### 03-reducate
| Draft sentence (bad) | Reason |
|---|---|
| "I have worked on real-world datasets and **built end-to-end ML pipelines**, including a churn prediction model… and a book recommendation system…" | The churn project has no pipeline; its repo holds only CSVs and `model.sav`, with no code. Plural "pipelines" is an overclaim. |
| "[Telco paragraph] …I also built a **YAML-driven pipeline with custom logging and exception handling**…" | **Pipeline credited to the wrong project**: it belongs to the book recommender, not churn. The final moves it under the book project. |
| "My academic and project work has given me a solid foundation…" | Puffery. Removed. |

### 04-outlier
| Draft sentence (bad) | Reason |
|---|---|
| "…have built **two end-to-end machine learning systems from scratch**." | The churn project is a data-prep script plus a Random Forest, not an end-to-end system. |
| "I have experience working with structured data, building pipelines, and **deploying models through Streamlit**." | "Deploying" is unsupported. |
| "**My projects** involve data ingestion, validation, transformation, and training stages, all managed with YAML configuration files and custom logging." | Only the book project has this; plural overgeneralisation. |
| (whole draft is a "Dear Hiring Team" letter) | Wrong format: the angle asked for a short profile blurb, which the final provides. |

### 05-stripe
| Draft sentence (bad) | Reason |
|---|---|
| "I have built a **full-stack** recommendation system…" | "Full-stack" is unsupported: Python plus Streamlit only, no frontend, backend or DB. |
| "This project showcased my ability to manage data flow and model training in a structured, **production-like** environment." | "Production-like" is unsupported: local solo project, empty Dockerfile. |
| "My academic and personal projects align with the technical depth and **end-to-end ownership** that Stripe values…" | Puffery; overclaim. |
| (missing) solo-project admission | The final adds "my projects so far are solo". |

### 06-pharmaand
| Draft sentence (bad) | Reason |
|---|---|
| "…handling a **large** sparse matrix, and **deploying** a Streamlit web app…" | The matrix is 742×888, which is not large. "Deploying" is unsupported. |
| "…binning numerical features **to improve model performance**." | No performance or accuracy numbers exist, so this is an unverifiable causal and impact claim. Also only tenure was binned. |
| "Both projects demonstrate my ability to work through the **full lifecycle** of an ML model, from data ingestion to **model deployment**." | No deployment; the churn project has no ingestion pipeline. |
| (missing) PyTorch/TensorFlow/LLM-API disclaimer | The posting lists these as required; the draft is silent. The final adds "I haven't yet used PyTorch, TensorFlow or LLM APIs". |
| (missing) churn repo link | pharma& asks for GitHub links; the final gives both. |

### 07-codingninjas (no corrected counterpart; dropped)
| Draft sentence | Note |
|---|---|
| "…how to translate technical concepts into user-friendly tools—skills I believe align well with your GenAI intern role." | Puffery. |
| "Gurugram is close to my university…" | Not in FACTS (leaked from `angle`). |
| The rest ("haven't worked with LLMs or agents yet") | Accurate. |

### 08-mlh
| Draft sentence (bad) | Reason |
|---|---|
| "…I have built **several** machine learning projects independently…" | He has exactly two. The final says "two machine learning projects on my own". |
| "…aligns **perfectly** with my goal…" / "I am writing to express…" | Cliché. |
| "Dear Hiring Team," | Should be a fellowship salutation. |

### 09-srfp
| Draft sentence (bad) | Reason |
|---|---|
| "The project also involved building a Streamlit web app… which deepened my appreciation for the practical aspects of **deploying ML models**." | "Deploying" is unsupported. |
| Whole draft: "Dear Hiring Team… I am writing to express…" | Wrong format; the programme wants a 150–250 word research-interest write-up. The final is a statement with cold-start, evaluation and sparsity questions. |
| "…Summer Research Fellowship Programme 2027 at the Indian Academy of Sciences." | Incomplete: the programme is run jointly by IASc, INSA and NASI. |

### 10-epfl
| Draft sentence | Reason |
|---|---|
| "I am especially drawn to EPFL's research environment and its focus on innovative machine learning approaches." | Generic and unverified. |
| Overall | **No hard factual errors found.** It was rewritten for being generic and short (158 words; EPFL wants about one page) and for the "Hiring Team" salutation and cliché. |

**Recurring hallucination types:** deploy/deployment (01, 02, 04, 06, 09); full-stack (05); production-like (05); scalable (02); "two end-to-end systems" and "end-to-end ML pipelines" (03, 04); "to improve model performance" (06); pipeline credited to the churn project (03, 02); "several" projects (08); implied knowledge-graph experience (02).

---

## 7. Scratchpad (`S`) and TEEP files

### repos/ (cloned from github.com/Preritsangwan17)

| Repo | Status |
|---|---|
| `S/repos/End-to-End-Book-Recommendation-System` | **Real code**: 41 files, 5 commits, first 2026-06-02. Has the four `components/stage_0x_*.py`, `app.py` (Streamlit), `config/config.yaml` (duplicate `model_training_config` key), a notebook, the BX CSVs (1,149,780 ratings; 271,379 books) and pickled artifacts. `Dockerfile` and all `__init__.py` files are 0 bytes. |
| `S/repos/Churn-ml-model-project` | **Data only, no code**: 1 commit, 2026-01-18. Contains `WA_Fn-UseC_-Telco-Customer-Churn.csv` (7,043 rows), `tel_churn.csv` (7,032 rows × 52 columns = index + Churn + 50 features), `first_telc.csv`, and `model.sav` (a pickled `RandomForestClassifier`). |
| `S/repos/Drinks-Quality-Prediction-System-` | **Empty scaffold**: 28 files, all 0 B except `template.py` (1,695 B) and `README.md`. |
| `S/repos/Global-Mobility-Application-Analyser` | **Empty scaffold** ("visa" package): 31 files, all 0 B except `template.py`, `README.md` and `requirements.txt`. |

The two scaffolds and the empty Dockerfile are good fact-check traps: a file name that suggests a skill (Docker, MLOps) is not evidence of it.

### ATS scanner and its outputs
- **`S/scan.py`** takes comma-separated company slugs in `argv[1]`. For each slug, 24 threads query the Greenhouse (`boards-api.greenhouse.io/v1/boards/{slug}/jobs`), Lever (`api.lever.co/v0/postings/{slug}?mode=json`) and Ashby (`api.ashbyhq.com/posting-api/job-board/{slug}`) APIs. It keeps titles matching `intern|trainee|apprentice|research assistant|student|co-?op|fellow` and prints `SRC | slug | title | location | url | date`.
  - **Bug:** `intern` also matches "Internal" and "International". **72 of 222** output lines are these false positives.
  - The slug lists passed in were not saved.
- **`S/scan1.txt`** (189 lines; ~40 companies including scaleai, stripe, databricks, togetherai, anthropic, openai, rubrik, paytm), **`S/scan2.txt`** (23 lines; lyft, cresta, dropbox, thoughtworks, krafton…), **`S/scan3.txt`** (10 lines; cloudsek, truefoundry, dozee…).
- These make a good title-classification fixture ("is this an internship?"): the Internal/International false positives are negatives, and entries like "Stripe | Software Engineer, Intern | Bengaluru | gh_jid=8031833" are positives.

### Internshala
- **`S/internshala.txt`**: 118 unique listings as `title | company | location | (stipend) | posted | url`, with the count "118" on the last line. **The stipend column is empty for every row.**
  - The unsaved inline parser missed the stipend. The saved HTML does have it, in `<span class='stipend'>` with single quotes.
- **`S/is_data-science-internship.html`**, **`S/is_machine-learning-internship.html`**, **`S/is_work-from-home-artificial-intelligence-ai-internships.html`**, **`S/is_work-from-home-machine-learning-internships.html`**: raw listing pages with 50/51/50/51 cards.
  - That is 202 cards and **118 unique URLs**, a good dedupe fixture.
  - Every card carries a stipend span; 8/12/15/17 are "Unpaid".

### LinkedIn
- **`S/li.html`**: several LinkedIn guest search-result pages concatenated. It has 80 job cards with many duplicates.
- **`S/li_<jobId>.html`**: 14 LinkedIn guest job-posting fragments with a `top-card`, `show-more-less-html__markup` description and `description__job-criteria-text`. The ids map to:
  - 4461088583 GE HealthCare
  - 4461799463 Houlihan Lokey
  - 4465520182 SkillsCapital
  - 4468467368 Readyly
  - 4468561627 Coding Ninjas
  - 4468839939 Simple Energy
  - **4469130739 Abstrabit (bot-challenge page, obfuscated JS, no job data)**
  - 4469386225 Meril
  - 4469849859 pharma&
  - 4469911747 MetAntz
  - 4470151030 Linde (Kolkata)
  - 4471480007 CNH
  - 4471873227 BNP Paribas
  - 4472084536 eTeam

### TEEP pages
- **`/tmp/teep.html`** (14 KB): TEEP home page listing fields of study only. It has no programme data.
- **`/tmp/teep_eng.html`** (152 KB): the Engineering programme table, 437 rows (No., Program, School, Location, Period of Apply, `teep.studyintaiwan.org/program/<id>`). This makes a good table-to-JSON and date-window fixture: some periods have already ended, such as row 57 "2025/04/01-2025/06/30" and row 26 "…-2026/04/30".
  - **It does not contain "Chengchi", "NCCU", "Chiu", "MARS" or "recommend".** The closest row is #36 "AI, information retrieval, data mining — National Chung Cheng University, Chiayi, 2026/04/01-2026/12/31, program/1689".
  - The professor and lab named in `email.txt` cannot be verified from saved files; the detail page was not saved.

### Ground-truth labels, checked against the fixture files

The candidate is a 2nd-year student, so his graduation year is about 2029. That year is inferred; FACTS does not state it.

| Label | Verified? | Fixture | Exact supporting text |
|---|---|---|---|
| Linde AI Intern → ineligible (7th semester only) | ✅ | `S/li_4470151030.html` | "Eligibility: Currently enrolled in 7th semester of B.Tech." Also Kolkata/Mumbai, 6 months, uninterrupted. The page contains a recruiter email address (PII, redact before reuse). |
| Meril → ineligible (2026 pass-outs only) | ✅ | `S/li_4469386225.html` | "Graduation Year: 2026 pass-out candidates only." and "B.Tech/B.E. – 2026 batch graduates." Bangalore. |
| eTeam → ineligible (2026/2027 grads) | ✅ | `S/li_4472084536.html` | "2026/2027 graduates in CS, AI, Data Science or related fields. 2027 graduates require College NOC." Remote, 6 months, 3–11 PM IST. Stipend ₹10,000/month for the first 3 months, then ₹20,000 or ₹30,000 based on performance. |
| MetAntz → ineligible (2026/2027 grads) | ✅ | `S/li_4469911747.html` | "CS or IT graduate passing out in 2026 or 2027." Stipend 30000/month, 4–6 months. Its seniority metadata says "Mid-Senior level", a noisy-field trap. |
| Readyly → eligible | ✅ | `S/li_4468467368.html` | "Bachelor's degree (or pursuing)"; "₹25,000 per month"; "Duration: 6 months"; "20 hours per week (part-time)". **Conflict:** the criteria field says "Full-time". Skills are "one or more of" React/Node/Python, LLM APIs or AWS Lambda, and Python satisfies this. |
| pharma& → degree-eligible | ✅ (with caveat) | `S/li_4469849859.html` | "…or currently be studying towards a degree"; "Stipend : ₹15000 per month"; "On-site"; "6 months"; "work full-time and on-site from our Hyderabad office for the full six-month internship". **Caveat:** the "Candidates should have" list includes hands-on PyTorch/TensorFlow and an LLM API, both of which he lacks, so it is eligible on degree but has skill gaps. |
| Reducate INR 15,000 | ✅ | `S/is_machine-learning-internship.html`, `S/is_work-from-home-machine-learning-internships.html` | "₹ 15,000 /month", 6 Months, WFH; skills Python and SQL; "Job offer upto ₹ 12LPA post internship". The "founded 2019 by IIT BHU / IIM A alumni" detail in jobs.json is **not** in any saved file. |
| LogPhase INR 25,000–40,000; apply by 21 Oct 2026 | Stipend ✅; **deadline ❌ not in any saved file** | `S/is_work-from-home-machine-learning-internships.html`, `S/is_work-from-home-artificial-intelligence-ai-internships.html` | "₹ 25,000 - 40,000 /month", 6 Months, tag "International"; skills include SQL. The "21 Oct" deadline and the "1:30 PM - 10:30 PM IST" shift from jobs.json appear nowhere in the scratchpad; they came from an unsaved detail page. |
| Calyp INR 2,000–2,500 → below living cost | Stipend ✅ (the "below living cost" part is a judgement, not page text) | `S/is_machine-learning-internship.html`, `S/is_work-from-home-machine-learning-internships.html`, `S/is_work-from-home-artificial-intelligence-ai-internships.html` | "₹ 2,000 - 2,500 /month", 3 Months, part-time. **Title/content mismatch:** titled "AI Engineer" but the work is audio-clip collection and labelling. |

**Extra labels available in the fixtures**
- GE HealthCare (`S/li_4461088583.html`): "Currently pursuing a PhD" → ineligible.
- Houlihan Lokey (`S/li_4461799463.html`): "must either be in you final year of study or a recent graduate" → ineligible.
- SkillsCapital (`S/li_4465520182.html`): "ideally… Final-year student or recent graduate" → soft requirement, borderline.
- Abstrabit (`S/li_4469130739.html`) → blocked page, should return a parse failure.
- Simple Energy, CNH, BNP Paribas and Coding Ninjas state no explicit year or degree-stage limit.

**Best fixtures**
- Parse job page → JSON: the 13 non-blocked `li_*.html` files (plus the blocked page as a negative case), the four `is_*.html` pages (card to record), and `/tmp/teep_eng.html` (table rows).
- Eligibility check: Linde, Meril, eTeam, MetAntz, GE, Houlihan (ineligible); Readyly (eligible); pharma& (eligible with skill gaps); SkillsCapital (borderline).

---

## 8. Other reusable items and what was never saved

- **Reusable:**
  - `scan.py`, after fixing the regex: use `\bintern(s|ship)?\b`.
  - `build.py` HTML/CSS résumé template.
  - `FACTS` and `RULES` prompts.
  - `letters.py` as gold "corrected" outputs.
  - `jobs.json` as structured job records.
  - The book repo as ground truth for claim verification. Its code shows `>200`, `>=50`, `drop_duplicates`, the local fallback, and a brute-force kNN with `n_neighbors=6`.
- **Not saved to disk (only run as inline commands):**
  - the Internshala listing parser that produced `internshala.txt` (with the stipend bug)
  - the LinkedIn search and job-page fetch and parse code
  - the scan slug lists
  - the TEEP fetch and parse
  - the fpdf script that made `Prerit_Sangwan_Resume_compact.pdf`
  - whatever fetched the LogPhase detail page ("21 Oct" deadline, shift hours), the Reducate company background, and the NCCU/Prof. Chiu/MARS lab listing
- **Missing overall:** no application-status tracker and no submission logs. Nothing on disk shows that any application was actually sent.