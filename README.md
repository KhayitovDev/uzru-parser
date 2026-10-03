# uzru-parser

CPU-first document parser and chunker for **Russian** and **Uzbek** (Latin and Cyrillic)
documents, built for RAG. Python API on top of a small Rust core (PyO3 + maturin).
No GPU, no ML models, no network calls.

> Status: early development (v0.1.0). PDF and DOCX parsing with heading, list and table
> detection, and structural chunking, work. Multi-column PDFs and OCR are not handled yet. No performance claims are made until benchmarks exist.

```python
from uzru_parser import Chunker, parse

document = parse("contract.pdf")  # or "contract.docx"
chunks = Chunker(max_tokens=600, overlap=80).chunk(document)
print(chunks[0].heading_path, chunks[0].page_start, chunks[0].text[:80])
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
