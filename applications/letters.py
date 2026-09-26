"""Final cover letters: local-model drafts, fact-checked and corrected against the verified fact sheet."""

SIGN = (
    "Best regards,\nPrerit Sangwan\nsangwanprerit40@gmail.com | "
    "LinkedIn: https://www.linkedin.com/in/prerit-sangwan-1b7572304 | GitHub: https://github.com/Preritsangwan17"
)
BOOK = "https://github.com/Preritsangwan17/End-to-End-Book-Recommendation-System"
CHURN = "https://github.com/Preritsangwan17/Churn-ml-model-project"

LETTERS = {
    "01-readyly": f"""Dear Hiring Team,

I'm a 2nd-year B.Tech student in Computer Science and Engineering (AI/ML specialisation) at Bennett University, and I'd like to apply for the Product Engineer Intern role on your AI agentic systems team.

My strongest project is an End-to-End Book Recommendation System ({BOOK}). I built it as a four-stage Python pipeline (ingestion, validation, transformation, training) driven by a YAML config, with custom logging and error handling, plus a Streamlit app that retrains the model and shows five recommendations with cover images. It taught me to structure code so a whole workflow can be rerun end to end, which I expect matters just as much for agent pipelines.

I have not yet built with LLM APIs or agent frameworks. I'm keen to learn them on real product work: prototyping agent behaviour, finding failure cases and improving reliability are exactly the skills I want to build next.

Thank you for considering my application.

{SIGN}
""",
    "02-logphase": f"""Dear Hiring Team,

I'm a 2nd-year B.Tech Computer Science (AI/ML) student at Bennett University, applying for the Machine Learning Intern role. Cleaning and structuring messy data is the part of machine learning I have spent the most time on, which is why this role appeals to me.

In my End-to-End Book Recommendation System ({BOOK}), I merged the Book-Crossing ratings and books tables (1.15 million ratings), removed duplicate user-title pairs, and kept users with 200+ ratings and books with 50+ ratings, leaving a 742-book by 888-user matrix. The code runs as a four-stage Python pipeline with YAML config, logging and error handling, so each step can be rerun and checked. In a separate churn project I prepared the IBM Telco dataset (one-hot encoding, tenure binning) for a Random Forest classifier.

I haven't worked with knowledge graphs or LLMs yet. Your posting says that's fine, and I'm keen to learn how extracted business data is linked and deduplicated at scale.

Thank you for your time.

{SIGN}
""",
    "03-reducate": f"""Dear Hiring Team,

I'm a 2nd-year B.Tech Computer Science (AI/ML) student at Bennett University, applying for the Data Science Intern role at Reducate.ai.

My Telco Customer Churn Prediction project ({CHURN}) is a classic business data science problem: I cleaned the IBM Telco dataset (7,043 customers, down to 7,032 rows), one-hot encoded the categorical fields, grouped tenure into 12-month bins to get 50 features, and trained a Random Forest classifier to predict churn. My Book Recommendation System ({BOOK}) gave me deeper pandas practice: merging tables, filtering 1.15 million ratings and building a user-item matrix for a k-nearest-neighbours model, inside a YAML-configured Python pipeline with logging.

I work in Python, pandas, NumPy and scikit-learn. I haven't used SQL in a project yet and would be glad to pick it up quickly on the job.

Thank you for considering my application.

{SIGN}
""",
    "04-outlier": f"""Profile summary (paste into Outlier's application where asked):

I'm a 2nd-year B.Tech Computer Science (AI/ML) student at Bennett University, India. I write Python in all my projects, mainly with pandas, NumPy and scikit-learn. My most complete project is an End-to-End Book Recommendation System ({BOOK}): a four-stage pipeline with YAML config, logging and error handling, a k-nearest-neighbours model on a sparse matrix, and a Streamlit front end. I'm comfortable reading unfamiliar code, explaining why a solution works or fails, and writing clearly in English. I'm new to AI evaluation work and keen to learn it.
""",
    "05-stripe": f"""Dear Hiring Team,

I'm a 2nd-year B.Tech Computer Science (AI/ML) student at Bennett University, applying for the Software Engineer Intern role in Bengaluru. Stripe's intern projects on the Payments Foundation Model and fraud controls are where my interest in machine learning meets software engineering, and I'd like to learn how ML is built into systems that businesses depend on.

My End-to-End Book Recommendation System ({BOOK}) is where I've practised writing structured code: a four-stage pipeline (ingestion, validation, transformation, training) driven by a YAML config, with custom logging and exception handling, and ingestion that falls back to local data when a download fails. It trains a k-nearest-neighbours model on 1.15 million ratings filtered to a sparse 742-by-888 matrix and shows recommendations in a Streamlit app.

I haven't done an internship yet, and my projects so far are solo, so working in a real codebase with code reviews is exactly what I want to learn. I'd bring care, curiosity and a willingness to ask good questions.

Thank you for your consideration.

{SIGN}
""",
    "06-pharmaand": f"""Dear Hiring Team,

I'm a 2nd-year B.Tech Computer Science (AI/ML) student at Bennett University, applying for the AI & Machine Learning Intern role in Hyderabad. Your posting asks for projects candidates can explain in detail; here are mine.

End-to-End Book Recommendation System ({BOOK}): item-based collaborative filtering on the Book-Crossing dataset. I filtered 1.15 million ratings to users with 200+ ratings and books with 50+ ratings (a 742-book by 888-user matrix), trained a k-nearest-neighbours model on a sparse matrix, and built a four-stage pipeline with YAML config, logging and error handling, plus a Streamlit app that shows five recommendations.

Telco Customer Churn Prediction ({CHURN}): I prepared the IBM Telco dataset with one-hot encoding and 12-month tenure bins (50 features) and trained a Random Forest classifier.

I haven't yet used PyTorch, TensorFlow or LLM APIs; I'm learning them and would welcome the chance to do so on real problems. I'm willing to relocate to Hyderabad.

Thank you for your time.

{SIGN}
""",
    "07-nccu-teep": f"""Subject: TEEP internship enquiry (recommender systems) - Prerit Sangwan, B.Tech CSE, India

Dear Professor Chiu,

I'm Prerit Sangwan, a 2nd-year B.Tech Computer Science and Engineering student (AI/ML specialisation) at Bennett University, India. I found your MARS lab's listing on the TEEP portal and was drawn to its work on recommender systems and retrieval.

I recently built an item-based collaborative-filtering book recommender on the Book-Crossing dataset ({BOOK}). Filtering 1.15 million ratings down to a usable 742-book by 888-user matrix showed me how much sparsity limits simple recommenders, and I'd like to learn how a research lab tackles it.

Would you consider me for a TEEP internship in your lab? Could you let me know whether positions are open and for which periods? My resume is attached.

Thank you for your time.

{SIGN}
""",
    "08-mlh": f"""Dear MLH Fellowship Team,

I'm a 2nd-year B.Tech Computer Science (AI/ML) student at Bennett University in India. I want to join the MLH Fellowship to learn how software is built collaboratively: so far I've built two machine learning projects on my own, and I've never worked in a shared codebase with code review.

My most complete project is an End-to-End Book Recommendation System ({BOOK}): a four-stage Python pipeline with YAML config, logging and error handling, a k-nearest-neighbours model trained on a sparse user-item matrix, and a Streamlit app. Building it taught me to keep code modular so each stage can be rerun and debugged on its own, which I hope carries over to contributing to open source.

I use Python, pandas, scikit-learn, Git and GitHub, and I'm ready to learn whatever stack my project needs.

Thank you for considering me.

{SIGN}
""",
    "09-srfp": f"""Research interests: recommender systems and learning from sparse data (about 220 words; the form asks for 150-250)

My main interest is how machine learning systems can make good predictions when data is sparse. I became curious about this while building an item-based collaborative-filtering book recommender ({BOOK}) on the Book-Crossing dataset. The dataset has 1.15 million ratings across 271,000 books, but after keeping only users with at least 200 ratings and books with at least 50 ratings, only 742 books and 888 users remained. A simple k-nearest-neighbours model worked on that dense core, yet most books could not be recommended at all.

That leaves questions I would like to study under a research guide: how to recommend items with few or no ratings (the cold-start problem), how to measure recommendation quality fairly, and when content features or learned embeddings help more than rating similarity alone. More broadly, I am interested in machine learning methods that stay reliable with incomplete, noisy real-world data.

I have practical experience with Python, pandas, NumPy, scikit-learn and SciPy sparse matrices, and I have built a reproducible four-stage data pipeline. I am a second-year B.Tech student in Computer Science and Engineering (AI/ML specialisation) at Bennett University and would value the chance to learn research methods in a working lab.
""",
    "10-epfl": f"""Dear Summer@EPFL Selection Committee,

I am a second-year B.Tech student in Computer Science and Engineering (AI/ML specialisation) at Bennett University, India, and I am applying to Summer@EPFL 2027 to gain my first research experience in machine learning.

My interest in research comes from a project that raised more questions than it answered. I built an item-based collaborative-filtering recommender on the Book-Crossing dataset ({BOOK}). To make a k-nearest-neighbours model usable, I kept only users with 200+ ratings and books with 50+ ratings, shrinking 1.15 million ratings on 271,000 books to a 742-book by 888-user matrix. The model works on that dense core, but it cannot recommend the vast majority of books. I want to learn how researchers approach sparsity, cold start and evaluation, rather than filtering the problem away.

Building the project also gave me habits I would bring to a lab: a four-stage pipeline configured through YAML, with logging and error handling so runs can be repeated, plus a Streamlit interface for inspecting results. I also trained a Random Forest churn classifier on the IBM Telco dataset.

I have not yet worked in a research group or used deep learning frameworks, and that is exactly why a structured summer at EPFL would matter to me: working with a supervisor on a real problem, learning to read papers critically and to design careful experiments. I would be glad to work on recommender systems, data mining or any machine learning project where I can contribute and learn.

Thank you for considering my application.

Sincerely,
Prerit Sangwan
sangwanprerit40@gmail.com | GitHub: https://github.com/Preritsangwan17
""",
}
