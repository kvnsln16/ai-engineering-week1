from __future__ import annotations

import subprocess
import sys


SPACY_MODEL = "en_core_web_sm"
SBERT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def download_spacy() -> bool:
    print(f"\n[1/2] Downloading spaCy model: {SPACY_MODEL}")
    try:
        import spacy
    except ImportError:
        print("  ERROR: spaCy not installed. Run `pip install -r requirements.txt` first.")
        return False

    try:
        spacy.load(SPACY_MODEL)
        print(f"  Already installed: {SPACY_MODEL}")
        return True
    except OSError:
        pass

    result = subprocess.run(
        [sys.executable, "-m", "spacy", "download", SPACY_MODEL],
        check=False,
    )
    if result.returncode != 0:
        print(f"  ERROR: spaCy download failed with exit code {result.returncode}")
        return False

    print(f"  Installed: {SPACY_MODEL}")
    return True


def download_sbert() -> bool:
    print(f"\n[2/2] Downloading sentence-transformers model: {SBERT_MODEL}")
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("  ERROR: sentence-transformers not installed.")
        return False

    try:
        SentenceTransformer(SBERT_MODEL)
    except Exception as exc:
        print(f"  ERROR: model download failed: {exc}")
        return False

    print(f"  Cached: {SBERT_MODEL}")
    return True


def main() -> int:
    print("Downloading NLP models for the enrichment pipeline.")
    print("This is a one-time setup. ~100MB total.\n")

    ok_spacy = download_spacy()
    ok_sbert = download_sbert()

    print()
    if ok_spacy and ok_sbert:
        print("All models ready. You can now run `python run_orchestrator.py`.")
        return 0
    else:
        print("Setup incomplete — see errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
