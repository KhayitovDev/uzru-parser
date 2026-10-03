# uzru-parser

CPU-first document parser and chunker for **Russian** and **Uzbek** (Latin and Cyrillic)
documents, built for RAG. Python API on top of a small Rust core (PyO3 + maturin).
No GPU, no ML models, no network calls.

> Status: early development (v0.1.0). PDF parsing works; DOCX, structure detection and
> chunking are not implemented yet. No performance claims are made until benchmarks exist.

```python
from uzru_parser import parse

document = parse("contract.pdf")
print(document.language.locale, len(document.blocks))
```

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install maturin pytest ruff mypy pymupdf
maturin develop --release
pytest
cargo test
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the design.
