"""Draft cover letters with a local MLX model. Every draft is fact-checked by Claude before use."""
import json
import pathlib

from mlx_lm import generate, load
from mlx_lm.sample_utils import make_sampler

HERE = pathlib.Path(__file__).parent
MODEL = "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-DWQ"

FACTS = """
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
"""

RULES = """
Write the letter body only, 170-230 words, plain text, 3-4 short paragraphs, then a sign-off:
"Best regards,\nPrerit Sangwan\nsangwanprerit40@gmail.com | LinkedIn: https://www.linkedin.com/in/prerit-sangwan-1b7572304 | GitHub: https://github.com/Preritsangwan17"
Start with "Dear Hiring Team," (or "Dear Selection Committee," for fellowships/research programmes).
Include the GitHub link of the most relevant project once in the body.
Be specific to the company using only the job details given. Plain, confident, humble tone. No clichés like "I am writing to express".
No invented facts. If the role asks for something he has not done, say he is eager to learn it; do not pretend.
"""


def prompt_for(job):
    return (
        f"{FACTS}\n\nJOB:\nCompany: {job['company']}\nRole: {job['role']}\nLocation/terms: {job['location']}\n"
        f"About the role: {job['about']}\nAngle to take: {job['angle']}\n\n{RULES}"
    )


def main():
    model, tokenizer = load(MODEL)
    sampler = make_sampler(temp=0.4, top_p=0.9)
    out_dir = HERE / "drafts"
    out_dir.mkdir(exist_ok=True)
    for job in json.loads((HERE / "jobs.json").read_text()):
        messages = [
            {"role": "system", "content": "You write honest, specific internship cover letters. You never invent facts."},
            {"role": "user", "content": prompt_for(job)},
        ]
        text = tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
        letter = generate(model, tokenizer, prompt=text, max_tokens=600, sampler=sampler)
        (out_dir / f"{job['id']}.txt").write_text(letter.strip() + "\n")
        print(f"drafted {job['id']} ({len(letter.split())} words)")


if __name__ == "__main__":
    main()
