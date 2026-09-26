"""Build a tailored resume PDF and a cover letter file per application (headless Chrome renders the PDFs)."""
import html
import pathlib
import subprocess

from letters import LETTERS

HERE = pathlib.Path(__file__).parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

BOOK = """<div class="proj"><div class="ph"><b><a href="https://github.com/Preritsangwan17/End-to-End-Book-Recommendation-System">End-to-End Book Recommendation System</a></b><span>Jun 2026</span></div>
<div class="tech">Python, pandas, scikit-learn, SciPy, Streamlit</div><ul>
<li>Built an item-based collaborative-filtering recommender on the Book-Crossing dataset (1.15M ratings, 271K books).</li>
<li>Reduced sparsity by keeping users with 200+ ratings and books with 50+ ratings, giving a 742-book by 888-user rating matrix.</li>
<li>Trained a k-nearest-neighbours model (scikit-learn, sparse CSR input) that returns the 5 most similar books.</li>
<li>Structured the code as a 4-stage pipeline (ingestion, validation, transformation, training) driven by a YAML config, with custom logging and exception handling; ingestion falls back to local data if the download fails.</li>
<li>Built a Streamlit app that retrains the model and shows 5 recommendations with cover images; prototyped a cosine-similarity version in Jupyter first.</li></ul></div>"""

CHURN = """<div class="proj"><div class="ph"><b><a href="https://github.com/Preritsangwan17/Churn-ml-model-project">Telco Customer Churn Prediction</a></b><span>Jan 2026</span></div>
<div class="tech">Python, pandas, scikit-learn</div><ul>
<li>Prepared the IBM Telco Customer Churn dataset (7,043 customers, cleaned to 7,032): one-hot encoded categorical fields and binned tenure into 12-month groups, giving 50 features.</li>
<li>Trained a Random Forest classifier (100 trees) to predict churn and saved the model for reuse.</li></ul></div>"""

SKILLS_DEFAULT = [
    ("Language", "Python"),
    ("ML and data", "scikit-learn (k-NN, Random Forest), pandas, NumPy, SciPy sparse matrices, collaborative filtering, cosine similarity, one-hot encoding, feature binning"),
    ("Tools", "Streamlit, Jupyter, Git and GitHub, YAML-configured modular pipelines, logging and exception handling"),
]

# Tailoring: a one-line summary (true, drawn from the fact sheet) and project order per application.
TAILOR = {
    "00-base": ("2nd-year Computer Science (AI/ML) student who builds end-to-end machine learning projects in Python.", ["book", "churn"]),
    "01-readyly": ("2nd-year Computer Science (AI/ML) student who builds complete Python workflows, from data pipeline to user-facing app; keen to learn LLM agents on real product work.", ["book", "churn"]),
    "02-logphase": ("2nd-year Computer Science (AI/ML) student focused on data cleaning, deduplication and reproducible Python pipelines.", ["book", "churn"]),
    "03-reducate": ("2nd-year Computer Science (AI/ML) student with hands-on data science projects in classification and recommendation using pandas and scikit-learn.", ["churn", "book"]),
    "04-outlier": ("2nd-year Computer Science (AI/ML) student who writes structured Python in every project.", ["book", "churn"]),
    "05-stripe": ("2nd-year Computer Science (AI/ML) student who writes modular, config-driven Python with logging and error handling; interested in ML inside real systems.", ["book", "churn"]),
    "06-pharmaand": ("2nd-year Computer Science (AI/ML) student with two ML projects I can walk through in detail: a collaborative-filtering recommender and a churn classifier.", ["book", "churn"]),
    "07-nccu-teep": ("2nd-year Computer Science (AI/ML) student interested in recommender systems, retrieval and learning from sparse data.", ["book", "churn"]),
    "08-mlh": ("2nd-year Computer Science (AI/ML) student ready to move from solo projects to collaborative open-source work.", ["book", "churn"]),
    "09-srfp": ("2nd-year Computer Science (AI/ML) student interested in research on recommender systems and learning from sparse data.", ["book", "churn"]),
    "10-epfl": ("2nd-year Computer Science (AI/ML) student seeking first research experience in recommender systems and sparse data.", ["book", "churn"]),
}

CSS = """
@page { size: A4; margin: 14mm 15mm; }
body { font-family: -apple-system, 'Helvetica Neue', Arial, sans-serif; font-size: 10.3pt; color: #111; line-height: 1.38; }
h1 { font-size: 20pt; margin: 0 0 2px; letter-spacing: 0.2px; }
.contact { font-size: 9.4pt; color: #333; margin-bottom: 8px; }
.contact a, .proj a { color: #0b4f9c; text-decoration: none; }
.summary { margin: 6px 0 4px; }
h2 { font-size: 10.5pt; text-transform: uppercase; letter-spacing: 1px; border-bottom: 1px solid #999; padding-bottom: 2px; margin: 12px 0 5px; }
.ph { display: flex; justify-content: space-between; }
.ph span { color: #444; font-size: 9.4pt; }
.ph span:last-child { white-space: nowrap; padding-left: 12px; }
.tech { font-style: italic; color: #444; font-size: 9.4pt; }
ul { margin: 3px 0 7px 16px; padding: 0; } li { margin-bottom: 2px; }
.sk b { display: inline-block; min-width: 88px; }
"""


def resume_html(summary, order):
    projects = "".join(BOOK if p == "book" else CHURN for p in order)
    skills = "".join(f'<div class="sk"><b>{k}:</b> {v}</div>' for k, v in SKILLS_DEFAULT)
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Prerit Sangwan - Resume</title><style>{CSS}</style></head><body>
<h1>Prerit Sangwan</h1>
<div class="contact">sangwanprerit40@gmail.com &middot; <a href="https://www.linkedin.com/in/prerit-sangwan-1b7572304">linkedin.com/in/prerit-sangwan-1b7572304</a> &middot; <a href="https://github.com/Preritsangwan17">github.com/Preritsangwan17</a> &middot; Indian citizen &middot; Open to relocation</div>
<div class="summary">{html.escape(summary)}</div>
<h2>Education</h2>
<div class="ph"><span style="color:#111;font-size:10.3pt"><b>Bennett University</b>, India &mdash; B.Tech, Computer Science and Engineering (AI/ML specialisation)</span><span>2nd year, in progress</span></div>
<h2>Projects</h2>{projects}
<h2>Skills</h2>{skills}
</body></html>"""


def main():
    for key, (summary, order) in TAILOR.items():
        folder = HERE / key
        folder.mkdir(exist_ok=True)
        page = folder / "resume.html"
        page.write_text(resume_html(summary, order))
        pdf = folder / "Prerit_Sangwan_Resume.pdf"
        subprocess.run(
            [CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
             f"--print-to-pdf={pdf}", page.as_uri()],
            check=True, capture_output=True,
        )
        if key in LETTERS:
            name = "email.txt" if key == "07-nccu-teep" else (
                "research_statement.txt" if key == "09-srfp" else (
                    "profile_summary.txt" if key == "04-outlier" else "cover_letter.txt"))
            (folder / name).write_text(LETTERS[key])
        print("built", key)


if __name__ == "__main__":
    main()
