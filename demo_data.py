"""Fake sessions for `--demo` mode (screenshots, trying the dashboard without real logs)."""
import random
import datetime

PROJECTS = {"my-webapp": 9, "blog-redesign": 6, "api-refactor": 5, "mobile-app": 4, "data-pipeline": 3, "docs-site": 2}
TITLES = ["Fix login redirect bug", "Refactor API routes", "Design new landing page", "Write unit tests",
          "Optimize SQL queries", "Add dark mode", "Update README", "Debug build failure",
          "Plan database schema", "Migrate to TypeScript", "Review pull request", "Setup CI pipeline"]
MODELS = ["Gemini 3.8 Flash (Low)", "Gemini 3.8 Pro (High)", "Claude Sonnet 5.5 (Low)", "GPT-OSS 120B"]


def demo_rows(transcripts, n=120, seed=7):
    """Return (id, title, last_modified, project, steps) rows and fill the server's fake transcripts."""
    rnd = random.Random(seed)
    now = datetime.datetime.now()
    names = [p for p, w in PROJECTS.items() for _ in range(w)]
    rows = []
    for i in range(n):
        cid = f"demo-{i:04d}"
        age_h = (i ** 1.6) * 0.5 + rnd.random()
        ts = (now - datetime.timedelta(hours=age_h)).strftime("%Y-%m-%dT%H:%M:%S")
        steps = rnd.randint(4, 140)
        rows.append((cid, rnd.choice(TITLES), ts, rnd.choice(names), steps))
        if i < 80:
            transcripts[cid] = {
                "in_tokens": steps * rnd.randint(500, 1400),
                "out_tokens": steps * rnd.randint(40, 200),
                "cache_tokens": steps * rnd.randint(3000, 12000),
                "tool_calls": steps // 2,
                "models": {rnd.choice(MODELS)},
            }
    return rows

