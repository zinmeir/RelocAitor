"""
The standalone build (preview/) re-implements the API in JavaScript. This test
sends ~200 requests (143 natural-language prompts plus random score/insights
requests) through both implementations and requires identical answers.
Skipped automatically when Node.js isn't installed.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from relocaitor.visas import journey
from relocaitor.web.app import app, meta
from ml.prompt_model import serving_payload
from relocaitor.datasets import _provenance, load_countries
from relocaitor import paths

ROOT = paths.ROOT
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="Node.js not installed")
def test_javascript_port_matches_python(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    data = {
        "countries": load_countries().to_dict(orient="records"),
        "visas": json.loads((ROOT / "data/visas.json").read_text(encoding="utf-8")),
        "meta": meta(),
        "lexicon": json.loads((ROOT / "data/search_lexicon.json").read_text(encoding="utf-8")),
        "occupations": journey.occupations(),
        "rules": json.loads((ROOT / "data/rules.json").read_text(encoding="utf-8")),
        "cities": journey.cities_meta()["cities"],
        "provenance": _provenance(),
        "prompt_model": serving_payload(),
    }
    inputs = json.loads((ROOT / "tests/parity/parity_inputs.json").read_text(encoding="utf-8"))
    requests = [("/api/search", {"prompt": p}) for p in inputs["prompts"]] + \
               [tuple(x) for x in inputs["others"]] + [("/api/search", {})]

    client = app.test_client()
    cases = []
    for path, body in requests:
        r = client.post(path, json=body)
        cases.append({"path": path, "body": body, "status": r.status_code, "json": r.get_json()})

    # Preference-learning sessions: simulated users answer 8 questions each; every step is a case.
    tastes = [{"climate": 1, "cost": 1}, {"salary": 1, "job": 1, "english": 0.5}, {"safety": 1, "healthcare": 1, "pr": 0.7}]
    for taste in tastes:
        answers = []
        for step in range(9):
            body = {"answers": list(answers)}
            r = client.post("/api/preferences", json=body)
            d = r.get_json()
            cases.append({"path": "/api/preferences", "body": body, "status": r.status_code, "json": d})
            if d["done"]:
                break
            q = d["question"]
            u = {side: sum(q[side]["values"][k] * v for k, v in taste.items()) for side in ("a", "b")}
            choice = "skip" if step == 3 else ("a" if u["a"] >= u["b"] else "b")
            answers.append({"a": q["a"]["name"], "b": q["b"]["name"], "choice": choice})

    (tmp_path / "data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "cases.json").write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    out = subprocess.run([NODE, str(ROOT / "preview/parity.js"), str(tmp_path / "data.json"),
                          str(tmp_path / "cases.json")], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    result = json.loads(out.stdout)
    assert result["total"] == len(cases)
    assert result["failures"] == [], json.dumps(result["failures"][:3], indent=1)
