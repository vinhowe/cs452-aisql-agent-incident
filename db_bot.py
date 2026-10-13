"""Ask plain-English questions about the agent-incident database.

question -> LLM (with schema) -> SQL -> SQLite -> LLM -> plain-English answer
"""

import argparse
import json
import os
import sqlite3
from pathlib import Path
from time import time

from dotenv import load_dotenv
from openai import OpenAI

HERE = Path(__file__).parent
DB_PATH = HERE / "aidb.sqlite"
SETUP_SQL = (HERE / "setup.sql").read_text()
SETUP_DATA_SQL = (HERE / "setupData.sql").read_text()
RESPONSES_DIR = HERE / "responses"

load_dotenv(HERE / ".env")
MODEL = os.environ.get("MODEL", "openai/gpt-6-luna")
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)


def build_db():
    """Recreate the database from the setup scripts."""
    DB_PATH.unlink(missing_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("pragma foreign_keys = on")
    con.executescript(SETUP_SQL)
    con.executescript(SETUP_DATA_SQL)
    con.commit()
    con.close()


def run_sql(query):
    """Run model-written SQL on a read-only connection so it can't modify the data."""
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        cur = con.execute(query)
        columns = [d[0] for d in cur.description] if cur.description else []
        return columns, cur.fetchall()
    finally:
        con.close()


def ask_llm(content):
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": content}],
    )
    return response.choices[0].message.content


def extract_sql(text):
    """Pull the SQL out of a ```sql fenced block if the model used one."""
    if "```" in text:
        text = text.split("```", 1)[1]
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.split("```", 1)[0]
    return text.strip()


# ---------------------------------------------------------------------------
# Prompting strategies (zero-shot, single-domain, cross-domain), following
# https://arxiv.org/abs/2305.11853
# ---------------------------------------------------------------------------

SQL_ONLY = (
    "\nGive me a sqlite select statement that answers the question. "
    "Only respond with sqlite syntax. If there is an error do not explain it!"
)

SINGLE_DOMAIN_EXAMPLES = """
Question: Which agents read a message posted by 38148c?
SELECT DISTINCT reader.handle
FROM message m
JOIN agent author ON m.author_agent_id = author.agent_id
JOIN message_read r ON r.message_id = m.message_id
JOIN agent reader ON r.reader_agent_id = reader.agent_id
WHERE author.handle = '38148c';

Question: How many messages did agents of each model post?
SELECT mo.name, COUNT(*) AS messages_posted
FROM message m
JOIN agent a ON m.author_agent_id = a.agent_id
JOIN model mo ON a.model_id = mo.model_id
GROUP BY mo.name;
"""

# An example from a *different* database (the class's dog-show example), per the paper's cross-domain setup.
CROSS_DOMAIN_EXAMPLE = """
Here is an example from a different database:

create table person (person_id integer primary key, name varchar(20) not null);
create table phone (phone_id integer primary key, person_id integer not null, area_code int not null,
    number int not null, can_recieve_sms tinyint not null);

Question: Who doesn't have a way for us to text them?
SELECT p.person_id, p.name
FROM person p
LEFT JOIN phone ph ON p.person_id = ph.person_id AND ph.can_recieve_sms = 1
WHERE ph.phone_id IS NULL;

Now here is the database you will actually query:
"""

STRATEGIES = {
    "zero_shot": SETUP_SQL + SQL_ONLY,
    "single_domain_double_shot": SETUP_SQL + SINGLE_DOMAIN_EXAMPLES + SQL_ONLY,
    "cross_domain": CROSS_DOMAIN_EXAMPLE + SETUP_SQL + SQL_ONLY,
}

QUESTIONS = [
    "Which agent posted the first message on the board?",
    "Which agents were active when the mass shutdown happened, and what model was each running?",
    "Who sent the most assignments, and to which workstreams?",
    "Which messages were posted under a handle that doesn't match the agent who actually wrote them?",
    "Which tool calls were spoofed?",
    "Which workstreams had the most importance-weighted reads (sum of importance squared)?",
    "How many agents attacked Hugging Face?",
    "How many agents tampered with their transcripts?",
    "Did any agent alert humans about what was happening?",
    "What did the agents say about whether they accessed Hugging Face?",
]


def answer_prompt(question, sql, columns, rows):
    return (
        f'I asked a question about a database of AI agent activity: "{question}"\n'
        f"This SQL was run:\n{sql}\n"
        f"Columns: {columns}\n"
        f"Rows: {rows[:50]}\n"
        "Answer the question concisely in plain English using only these results. "
        "Do not give any other suggestions or chatter."
    )


def run_strategy(name, questions):
    print("#" * 72)
    print(f"Strategy: {name}  (model: {MODEL})")
    results = []
    for question in questions:
        print("~" * 72)
        print(f"Question: {question}")
        sql, columns, rows, answer, error = "", [], [], "", None
        try:
            sql = extract_sql(ask_llm(STRATEGIES[name] + "\nQuestion: " + question))
            print(f"SQL:\n{sql}")
            columns, rows = run_sql(sql)
            print(f"Rows: {rows}")
            answer = ask_llm(answer_prompt(question, sql, columns, rows))
            print(f"Answer: {answer}")
        except Exception as err:
            error = str(err)
            print(f"Error: {error}")
        results.append({
            "question": question,
            "sql": sql,
            "columns": columns,
            "rows": [list(r) for r in rows],
            "answer": answer,
            "error": error,
        })

    RESPONSES_DIR.mkdir(exist_ok=True)
    out = RESPONSES_DIR / f"response_{name}_{int(time())}.json"
    out.write_text(json.dumps(
        {"strategy": name, "model": MODEL, "prompt_prefix": STRATEGIES[name], "results": results},
        indent=2,
    ))
    print(f"Saved {out.name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", action="append", choices=STRATEGIES,
                        help="strategy to run (repeatable; default: all)")
    parser.add_argument("--question", action="append",
                        help="question to ask (repeatable; default: the built-in list)")
    args = parser.parse_args()

    build_db()
    for name in args.strategy or STRATEGIES:
        run_strategy(name, args.question or QUESTIONS)


if __name__ == "__main__":
    main()
