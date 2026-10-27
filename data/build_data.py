"""Build the data/*.json files that the MCP server and llms.txt read.

Source of truth is the published site, so the connector always matches it:
  - index.html                     per-use-case queries, answer keys, what each API returned,
                                   scorecards, provider picks, metrics, friction log
  - README.md                      overall results, per-use-case summary, activation numbers
  - eval/grading/labels_*.csv      per-query accuracy (mean of 3 runs, 0-2) and short labels
  - img/*.png                      published charts

Run from the repo root after publishing a new run:  python3 data/build_data.py
"""
import csv
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data"
SITE = "https://psinglap.github.io/websearch-api-eval/"
REPO = "https://github.com/psinglap/websearch-api-eval"
AS_OF = "2026-10-08"
PROVIDERS = ["You.com", "Tavily", "Exa", "Parallel"]
USE_CASES = {
    "gtm": {"name": "GTM agent", "prefix": "G",
            "job": "Find fresh developer and company buying signals (issues, releases, funding, incidents) for a streaming-infra vendor."},
    "insurance": {"name": "Insurance agent", "prefix": "I",
                  "job": "Voice and claims agent for P&C insurers that must know live catastrophe status mid-call (500 ms latency budget)."},
    "finance": {"name": "Finance agent", "prefix": "F",
                "job": "Analyst agent that answers with exact, current numbers and a primary-source citation."},
}


def text(cell_html):
    t = re.sub(r"<br\s*/?>", " ", cell_html)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def links(cell_html):
    return [{"text": text(a), "url": html.unescape(h)}
            for h, a in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', cell_html, flags=re.S)]


def rows(table_html):
    out = []
    for tr in re.findall(r"<tr.*?</tr>", table_html, flags=re.S):
        out.append(re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, flags=re.S))
    return out


def md_table(md, header_start):
    """Return rows of the first markdown table whose header starts with header_start."""
    lines = md.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("| " + header_start):
            body = []
            for l in lines[i + 2:]:
                if not l.startswith("|"):
                    break
                body.append([c.strip() for c in l.strip().strip("|").split("|")])
            return body
    raise ValueError(f"table not found: {header_start}")


def clean_md(s):
    return re.sub(r"\*\*(.*?)\*\*", r"\1", s).replace("`", "")


page = (ROOT / "index.html").read_text()
readme = (ROOT / "README.md").read_text()
tables = re.findall(r"<table.*?</table>", page, flags=re.S)


def find_tables(first_header):
    return [t for t in tables if text(rows(t)[0][0]) == first_header]


q_tables = [t for t in find_tables("QID") if "Upstream task" in text(rows(t)[0][1])]
ret_tables = [t for t in find_tables("QID") if text(rows(t)[0][1]) == "You.com"]
score_tables = find_tables("Metric")
assert len(q_tables) == len(ret_tables) == len(score_tables) == 3

# ---- per-query scores (mean accuracy over 3 runs, 0-2) ----
scores = {}
for uc in USE_CASES:
    with open(ROOT / "eval" / "grading" / f"labels_{uc}.csv") as f:
        for r in csv.DictReader(f):
            scores.setdefault(r["qid"], {})[r["provider"]] = {
                "accuracy_0_2": float(r["mean"]), "returned_short": r["returned_short"], "answer_key_short": r["key_short"]}

# ---- questions ----
questions = []
for uc, qt, rt in zip(USE_CASES, q_tables, ret_tables):
    hdr = [text(c) for c in rows(qt)[0]]
    returned = {text(r[0]): [text(c) for c in r[1:]] for r in rows(rt)[1:]}
    for r in rows(qt)[1:]:
        d = dict(zip(hdr, r))
        qid = text(d["QID"])
        src_cell = d.get("Source + Wayback link", "")
        q = {
            "id": qid,
            "use_case": uc,
            "task": text(d["Upstream task given to the agent"]).strip('"'),
            "search_call": text(d["Search call the agent sends"]),
            "parameters": text(d["Params"]),
            "needs_back": text(d["What the agent needs back"]),
            "freshness": text(d["Freshness"]),
            "answer_key": text(d["Answer key"]),
            "answer_key_links": links(d["Answer key"]),
            "sources": links(src_cell),
            "results": {},
        }
        for p, ret in zip(PROVIDERS, returned.get(qid, [""] * 4)):
            s = scores.get(qid, {}).get(p, {})
            q["results"][p] = {"returned": ret, "accuracy_0_2": s.get("accuracy_0_2")}
        questions.append(q)
assert len(questions) == 30, len(questions)

# ---- per-use-case scorecards ----
scorecards = {}
for uc, st in zip(USE_CASES, score_tables):
    body = rows(st)[1:]
    scorecards[uc] = {
        "use_case": USE_CASES[uc]["name"],
        "agent_job": USE_CASES[uc]["job"],
        "metrics": [{"metric": text(r[0]), **{p: text(c) for p, c in zip(PROVIDERS, r[1:])}} for r in body],
    }

# ---- overall results (README "Results at a glance") ----
overall_rows = md_table(readme, "Metric (30 queries")
overall = [{"metric": clean_md(r[0]), **{p: clean_md(c) for p, c in zip(PROVIDERS, r[1:])}} for r in overall_rows]
headline = re.search(r"\*\*Headline:\*\* (.+)", readme).group(1)
picks = [{"if_your_agent": clean_md(r[0]), "pick": clean_md(r[1]), "why": clean_md(r[2])}
         for r in md_table(readme, "If your agent")]
by_uc = [{"use_case": clean_md(r[0]), "agent_job": r[1], **{p: clean_md(c) for p, c in zip(PROVIDERS, r[2:])}}
         for r in md_table(readme, "Use case | Agent job")]
act_rows = md_table(readme, "| Tavily | You.com")
activation = [{"metric": clean_md(r[0]), **{p: clean_md(c) for p, c in zip(["Tavily", "You.com", "Parallel", "Exa"], r[1:])}}
              for r in act_rows]

meta = {"as_of": AS_OF, "site": SITE, "repo": REPO,
        "note": "Snapshot of the published benchmark run on 2026-10-08. Not live data."}

results = {
    **meta,
    "headline": headline,
    "overall": {"basis": "30 queries x 3 repeats = 90 calls per API", "metrics": overall,
                "chart": SITE + "img/overall_scorecard.png"},
    "by_use_case_summary": {"basis": "Accuracy score (% of max) · search-only client latency p50", "rows": by_uc},
    "scorecards": scorecards,
    "which_api_for_which_agent": picks,
    "developer_activation": {"basis": "Sign-in to copied API key, from screen recordings", "metrics": activation,
                             "chart": SITE + "img/time_steps_activation.png"},
}

# ---- methodology ----
metric_rows = md_table(readme, "# | Metric")
methodology = {
    **meta,
    "summary": ("30 agent-style queries (10 each for GTM, insurance, finance). Every API gets the same search call and "
                "parameters (10 results, full content where supported, freshness window, domain filters where supported). "
                "Searches ran in promptfoo, 3 runs per query (90 calls per API); latency is client wall-clock around the HTTP "
                "request after a discarded warm-up call, with server-reported latency alongside. Answers were written and "
                "graded from each provider's saved top-5 results using the SimpleQA grader rubric and FreshQA strict rules; "
                "answer keys were captured live and archived to the Wayback Machine."),
    "metrics": [{"n": r[0], "metric": r[1], "how_measured": r[2], "standard": re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", r[3])}
                for r in metric_rows],
    "statistics": "With 10 queries per use case, results are reported per query ('won 7 of 10') rather than as percentage-point margins.",
    "limits": [l[2:] for l in readme.split("## Limits", 1)[1].split("##", 1)[0].strip().splitlines() if l.startswith("- ")],
    "files": {"metric_definitions": REPO + "/blob/main/eval/METRICS.md",
              "grading_rubric": REPO + "/blob/main/eval/grading/RUBRIC.md",
              "answer_keys": REPO + "/blob/main/eval/answer_keys.csv",
              "questions": REPO + "/blob/main/reports/Agent%20queries.md"},
}

# ---- how to run locally ----
run_locally = {
    **meta,
    "summary": "Nothing runs on a hosted server. Clone the repo and run the harness on your own machine with your own API keys.",
    "steps": [
        "git clone " + REPO + ".git && cd websearch-api-eval/eval",
        "./run.sh setup --playwright   # Python venv + requirements, promptfoo 0.124.0, Chromium",
        "cp .env.example .env          # add your own API keys; .env is git-ignored",
        "./run.sh smoke                # one call per provider to check keys",
        "./run.sh run gtm              # also: insurance, finance",
        "./run.sh analyze              # scorecards and charts into eval/out/",
    ],
    "keys_needed": ["YDC_API_KEY", "TAVILY_API_KEY", "EXA_API_KEY", "PARALLEL_API_KEY",
                    "FIRECRAWL_API_KEY and LINKUP_API_KEY (only for the six-provider configs)",
                    "SEC_USER_AGENT (your name and email, required by SEC EDGAR)"],
    "use_your_own_queries": "Edit reports/Agent queries.md and eval/answer_keys.csv, then rebuild tests with eval/tests/build_tests.py.",
    "docs": REPO + "/blob/main/eval/README.md",
}

# ---- charts ----
charts = [
    {"id": "overall_scorecard", "use_case": "all", "title": "Overall scorecard: 30 queries, 3 use cases, 4 search APIs",
     "caption": "Quality, freshness, reliability, speed and cost for each API, colored by rank on each row."},
    {"id": "gtm_key_metrics", "use_case": "gtm", "title": "GTM agent: key metrics",
     "caption": "Accuracy, freshness, latency and cost for the developer-signal agent."},
    {"id": "gtm_query_grid", "use_case": "gtm", "title": "GTM agent: per-query results",
     "caption": "What each API returned on G1-G10 and how it scored."},
    {"id": "insurance_key_metrics", "use_case": "insurance", "title": "Insurance agent: key metrics",
     "caption": "Accuracy, freshness, latency and cost for the voice and claims agent."},
    {"id": "insurance_query_grid", "use_case": "insurance", "title": "Insurance agent: per-query results",
     "caption": "What each API returned on I1-I10 and how it scored."},
    {"id": "finance_key_metrics", "use_case": "finance", "title": "Finance agent: key metrics",
     "caption": "Accuracy, freshness, latency and cost for the analyst agent."},
    {"id": "finance_query_grid", "use_case": "finance", "title": "Finance agent: per-query results",
     "caption": "What each API returned on F1-F10 and how it scored."},
    {"id": "time_steps_activation", "use_case": "setup", "title": "Time and steps to activation",
     "caption": "Seconds and steps from sign-in to a copied API key for each provider."},
    {"id": "activation_gates", "use_case": "setup", "title": "What stands between sign-in and the API key",
     "caption": "The screens and gates each provider puts before the first API key."},
]
for c in charts:
    assert (ROOT / "img" / f"{c['id']}.png").exists(), c["id"]
    c["image_url"] = SITE + f"img/{c['id']}.png"
    c["page"] = SITE

OUT.mkdir(exist_ok=True)
for name, obj in {"questions": {**meta, "questions": questions}, "results": results, "methodology": methodology,
                  "run_locally": run_locally, "charts": {**meta, "charts": charts}}.items():
    (OUT / f"{name}.json").write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n")
    print("wrote", f"data/{name}.json")
