import os
import tempfile

# Tests send thousands of requests from one address: switch the per-client rate limit off (the limiter has
# its own test), and keep any accounts the tests create out of the repository's instance/ folder.
os.environ.setdefault("RELOC_RATE_LIMIT", "0")
os.environ.setdefault("RELOC_DB", os.path.join(tempfile.mkdtemp(prefix="reloc-test-"), "test.db"))

import os
import sys
from pathlib import Path

# The sentence-embedding model is optional and, once downloaded, would change what prompts
# mean. Keep the ordinary test suite deterministic: tests that need embeddings inject a stub
# encoder (tests/semantic_stub.py) or load the real model explicitly (tests/test_semantic.py).
os.environ.setdefault("RELOC_SEMANTIC", "0")
# Tests run against a frozen 66-country snapshot of the generated dataset, so fetching data for more
# countries (python -m pipeline fetch && build) never changes what they expect. tests/test_world.py
# checks the live dataset with rules that hold for any number of countries.
os.environ.setdefault("RELOC_DATASET_DIR", str(Path(__file__).resolve().parent / "fixtures" / "dataset"))

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import app as flask_app  # noqa: E402
from factors import DEFAULT_WEIGHTS  # noqa: E402


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


@pytest.fixture
def weights():
    return dict(DEFAULT_WEIGHTS)
