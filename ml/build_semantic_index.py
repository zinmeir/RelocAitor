"""
build_semantic_index.py — Download the embedding model and embed the search corpus.

    python -m ml.build_semantic_index --download   # first time (needs internet, ~90 MB)
    python -m ml.build_semantic_index              # re-embed after editing visas.json or the prototypes
    python -m ml.build_semantic_index --check      # fail if the index is out of date (CI)
    python -m ml.build_semantic_index --model-only # just fetch the model (deploys: the index is committed)

Writes ml/semantic_index.json (committed). The model itself goes to
ml/models/ (git-ignored) and is needed at runtime to embed the user's prompt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ml import semantic                                              # noqa: E402
from ml.data.semantic_concepts import FACTOR_PROTOTYPES, VISA_PROTOTYPES   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
HF = "https://huggingface.co/{repo}/resolve/main/{path}"
# (repo, path in repo, local file name). First source that works wins.
SOURCES = [
    [("sentence-transformers/all-MiniLM-L6-v2", "onnx/model.onnx", "model.onnx"),
     ("Xenova/all-MiniLM-L6-v2", "onnx/model.onnx", "model.onnx")],
    [("sentence-transformers/all-MiniLM-L6-v2", "vocab.txt", "vocab.txt"),
     ("Xenova/all-MiniLM-L6-v2", "vocab.txt", "vocab.txt")],
]
TYPE_LABEL = {"skilled": "Skilled worker", "nomad": "Digital nomad / remote work", "investor": "Investor / golden",
              "study": "Student", "startup": "Startup founder", "family": "Family / partner",
              "passive": "Retirement / passive income"}


def corpus() -> list:
    """Every text that gets a vector, in a fixed order."""
    items = []
    for key, texts in FACTOR_PROTOTYPES.items():
        items += [{"kind": "factor", "key": key, "text": t} for t in texts]
    for key, texts in VISA_PROTOTYPES.items():
        items += [{"kind": "visa_type", "key": key, "text": t} for t in texts]
    visas = json.loads((ROOT / "data/visas.json").read_text(encoding="utf-8"))
    names = {}
    import pandas as pd
    for r in pd.read_csv(ROOT / "data/countries.csv").itertuples(index=False):
        names[r.country_code] = r.country_name
    for code in sorted(visas):
        for v in visas[code]["visas"]:
            text = (f"{v['name']}. {TYPE_LABEL.get(v['type'], v['type'])} visa in {names.get(code, code)}. "
                    f"{v.get('summary', '')}").strip()
            items.append({"kind": "visa", "country": code, "name": v["name"], "type": v["type"], "text": text})
    return items


def corpus_hash(items: list) -> str:
    return hashlib.sha256(json.dumps([i["text"] for i in items], ensure_ascii=False).encode()).hexdigest()[:16]


def download(model_dir: Path = semantic.MODEL_DIR) -> None:
    model_dir.mkdir(parents=True, exist_ok=True)
    for options in SOURCES:
        last = None
        for repo, path, local in options:
            target = model_dir / local
            if target.exists() and target.stat().st_size > 0:
                break
            url = HF.format(repo=repo, path=path)
            try:
                print(f"Downloading {url} …")
                tmp = target.with_suffix(target.suffix + ".part")
                urllib.request.urlretrieve(url, tmp)
                tmp.rename(target)
                break
            except Exception as err:          # try the next mirror
                last = err
        else:
            raise SystemExit(f"Could not download {options[0][2]}: {last}")
    for f in sorted(model_dir.iterdir()):
        digest = hashlib.sha256(f.read_bytes()).hexdigest()[:16]
        print(f"  {f.name}: {f.stat().st_size / 1e6:.1f} MB, sha256 {digest}…")


def build() -> dict:
    semantic.reset_caches()
    enc = semantic.encoder()
    if enc is None:
        raise SystemExit("Model not found. Run: python -m ml.build_semantic_index --download")
    items = corpus()
    vecs = []
    for i in range(0, len(items), 32):
        vecs.append(enc.embed([it["text"] for it in items[i:i + 32]]))
    import numpy as np
    V = np.vstack(vecs)
    return {"model": semantic.MODEL_NAME, "corpus_hash": corpus_hash(items),
            "items": items, "vectors": semantic.quantize(V)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--model-only", action="store_true")
    args = ap.parse_args(argv)
    if args.check:
        if not semantic.INDEX_PATH.exists():
            print("No semantic index (optional). Run: python -m ml.build_semantic_index --download")
            return 0
        stored = json.loads(semantic.INDEX_PATH.read_text(encoding="utf-8"))
        if stored["corpus_hash"] != corpus_hash(corpus()):
            print("semantic_index.json is out of date: run python -m ml.build_semantic_index")
            return 1
        print("semantic_index.json is up to date")
        return 0
    if args.model_only:
        download()
        return 0
    if args.download:
        download()
    index = build()
    semantic.INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {semantic.INDEX_PATH.name}: {len(index['items'])} vectors "
          f"({semantic.INDEX_PATH.stat().st_size / 1e3:.0f} KB)")
    semantic.reset_caches()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
