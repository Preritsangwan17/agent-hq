"""A cover letter in Writer-output form (sentences + citations) that passes every deterministic gate for the mock
posting "Machine Learning Intern" at Mocktech. Used by the dry-run end-to-end tests."""
from __future__ import annotations

JOB_QUOTE = "As a Machine Learning Intern you will work on collaborative filtering and data pipelines in Python with pandas and scikit-learn."


def letter(org: str = "Mocktech") -> dict:
    return {"subject": None, "sentences": [
        {"text": "Dear Hiring Team,", "kind": "salutation", "fact_ids": [], "job_quote_ids": []},
        {"text": f"I am a second-year B.Tech student in Computer Science and Engineering (AI/ML specialisation) at "
                 f"Bennett University, and I am applying for the Machine Learning Intern role at {org}.",
         "kind": "motivation", "fact_ids": ["F-EDU-YEAR2"], "job_quote_ids": [], "paragraph": 0},
        {"text": "Your posting says the intern will work on collaborative filtering and data pipelines in Python "
                 "with pandas and scikit-learn.", "kind": "job_reference", "fact_ids": [], "job_quote_ids": ["J1"],
         "paragraph": 0},
        {"text": "I built an end-to-end book recommendation system that uses item-based collaborative filtering on "
                 "the Book-Crossing dataset of about 1.15 million ratings.",
         "kind": "claim", "fact_ids": ["F-BOOK-NAME", "F-BOOK-CF", "F-BOOK-DATA"], "job_quote_ids": [], "paragraph": 1},
        {"text": "After keeping users with more than 200 ratings and books with at least 50 ratings, I trained a "
                 "k-nearest-neighbours model on a SciPy sparse matrix that returns the 5 most similar books.",
         "kind": "claim", "fact_ids": ["F-BOOK-FILTER", "F-BOOK-KNN"], "job_quote_ids": [], "paragraph": 1},
        {"text": "I structured the code as a four-stage pipeline driven by a YAML config, with custom logging and "
                 "exception handling.", "kind": "claim", "fact_ids": ["F-BOOK-PIPELINE", "F-BOOK-LOGGING"],
         "job_quote_ids": [], "paragraph": 1},
        {"text": "Earlier, I trained a Random Forest classifier with 100 trees to predict customer churn on the IBM "
                 "Telco dataset of 7,043 customers.", "kind": "claim", "fact_ids": ["F-CHURN-RF", "F-CHURN-DATA"],
         "job_quote_ids": [], "paragraph": 2},
        {"text": "I have not done an internship yet, and both projects were built on my own, so I have not yet worked "
                 "in a shared codebase with code review.", "kind": "claim",
         "fact_ids": ["F-NO-INTERNSHIP", "F-SOLO"], "job_quote_ids": [], "paragraph": 2},
        {"text": "I am open to learning on the job and willing to relocate, and I would be glad to talk about how I "
                 "could help your team.", "kind": "closing", "fact_ids": ["F-LEARN", "F-RELOCATE"],
         "job_quote_ids": [], "paragraph": 3},
    ]}
