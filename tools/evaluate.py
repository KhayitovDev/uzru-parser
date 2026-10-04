"""Quality evaluation of uzru-parser on a folder of real documents.

    python tools/evaluate.py CORPUS_DIR [--gold GOLD_DIR] [--out report.json]
    python tools/evaluate.py --compare old.json new.json
    python tools/evaluate.py CORPUS_DIR --draft-gold DIR   # outline drafts to correct by hand

Every file is parsed and chunked sequentially in one process (``max_tokens=600``,
``overlap=80``). The metrics need no annotation except the heading outline and the expected
tables, which come from ``<gold>/<file name>.json`` when present:

    {"headings": [["1-ILOVA", 1], ["1-bob. Umumiy qoidalar", 2], ...],
     "tables": [{"page": 24, "cols": 3}, {"page": 29, "page_end": 30, "cols": 4}]}

Gold heading texts are prefixes: a heading matches when one normalised text starts with the
other. Levels only order the outline (1 is the top), they are not compared literally.

Metrics:
* fidelity: share of the source's words (3+ letters) found in the blocks;
* order: share of adjacent word pairs of the prose output that are also near each other
  (within four words) in the source text stream; a moved line breaks two pairs;
* headings: precision / recall against the gold outline;
* paths: share of chunks whose heading path equals the gold path at the chunk's first block
  (or, when that block is a short intro, at the first heading after it; or the path the
  sections packed into the chunk share);
* tables: gold tables found with at least their columns and their page range;
* chunks: tiny or heading-only chunks, chunks ending with ":", table rows repeated in the next
  chunk, chunks labelled ``unknown`` in a ``uz``/``ru`` document, empty metadata;
* artifacts: punctuation-only blocks, leftover "word | word | word" fragments;
* time and peak Python memory (tracemalloc).
"""

from __future__ import annotations

import argparse
import json
import re
import time
import tracemalloc
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

from uzru_parser import Chunker, parse

APOSTROPHES = re.compile(r"[ʻʼ’‘'`´ʹ]")
WORD = re.compile(r"[^\W\d_]{3,}")
TOKEN = re.compile(r"\w+")
SEP = " | "
#: Blocks a gold heading's own heading may lie after a paragraph that repeats its text.
HEADING_WINDOW = 40
#: Words of text under a heading that may join its first subsection's chunk and path.
INTRO_WORDS = 40


# Cyrillic letters that look like Latin ones. Folded on both sides of every comparison, so a
# source that mixes them into Latin words ("miqdоriy") matches the parser's repaired text.
LOOKALIKES = str.maketrans("аеорсухкмтвніјѕ", "aeopcyxkmtbhijs")


def norm(text: str) -> str:
    text = unicodedata.normalize("NFC", text).casefold().translate(LOOKALIKES)
    text = APOSTROPHES.sub("", text)
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(text: str) -> list[str]:
    return TOKEN.findall(norm(text))


# ---------------------------------------------------------------- source text


def source_text(path: Path) -> list[str]:
    """The file's text in stream order, one string per page (PDF) or one in all (DOCX)."""
    if path.suffix.lower() == ".pdf":
        import pymupdf

        with pymupdf.open(path) as pdf:
            pages = [page.get_text("text", sort=False) for page in pdf]
        # A word broken at a line end is one word.
        return [re.sub(r"(\w)-\n(\w)", r"\1\2", page) for page in pages]
    from docx import Document
    from docx.oxml.ns import qn

    document = Document(str(path))
    fallback = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
    parts: list[str] = []
    for element in document.element.body.iterchildren():
        if element.tag not in (qn("w:p"), qn("w:tbl")):
            continue
        for paragraph in element.iter(qn("w:p")):
            # Each paragraph's own text once: a text box's paragraphs are paragraphs of their
            # own, and its older VML copy (mc:Fallback) repeats the drawing's.
            if any(a.tag == fallback for a in paragraph.iterancestors()):
                continue
            own = [t for t in paragraph.iter(qn("w:t")) if _owner(t) is paragraph]
            parts.append("".join(t.text or "" for t in own))
    return ["\n".join(parts)]


def _owner(node: Any) -> Any:
    """The innermost paragraph holding ``node``."""
    from docx.oxml.ns import qn

    return next((a for a in node.iterancestors() if a.tag == qn("w:p")), None)


# ---------------------------------------------------------------- metrics


def fidelity(source: list[str], blocks: list[dict[str, Any]]) -> float:
    wanted = Counter(w for page in source for w in WORD.findall(norm(page)))
    found = Counter(w for block in blocks for w in WORD.findall(norm(block["text"])))
    total = sum(wanted.values())
    return sum(min(n, found[w]) for w, n in wanted.items()) / total if total else 1.0


def order(source: list[str], blocks: list[dict[str, Any]]) -> tuple[float, int]:
    near: set[tuple[str, str]] = set()
    stream = [w for page in source for w in tokens(page)]
    for i, word in enumerate(stream):
        for j in range(i + 1, min(i + 5, len(stream))):
            near.add((word, stream[j]))
    good = bad = 0
    for block in blocks:
        if block["type"] == "table" or block["extra"].get("role") in ("figure", "formula"):
            continue
        words = tokens(block["text"].replace(SEP, " "))
        for a, b in zip(words, words[1:], strict=False):
            if (a, b) in near:
                good += 1
            else:
                bad += 1
    return (good / (good + bad) if good + bad else 1.0), bad


def match(gold: str, text: str) -> bool:
    """``text`` is the gold heading: it starts with it ("1-ILOVA. Title" for the gold
    "1-ILOVA") or is a cut-off start of it."""
    g, t = norm(gold)[:120], norm(text)[:300]
    if not g or not t:
        return False
    return t.startswith(g) or (len(t) >= 6 and g.startswith(t))


def optional(entry: list[Any]) -> bool:
    return len(entry) > 2 and entry[2] == "opt"


def heading_scores(gold: list[list[Any]], blocks: list[dict[str, Any]]) -> dict[str, Any]:
    found = [b for b in blocks if b["type"] == "heading"]
    required = [g for g in gold if not optional(g)]
    matched_gold = [any(match(g[0], h["text"]) for h in found) for g in required]
    counted = [h for h in found if not any(optional(g) and match(g[0], h["text"]) for g in gold)]
    matched_found = [any(match(g[0], h["text"]) for g in required) for h in counted]
    return {
        "recall": sum(matched_gold) / len(required) if required else None,
        "precision": sum(matched_found) / len(counted) if counted else None,
        "missed": [g[0][:60] for g, ok in zip(required, matched_gold, strict=True) if not ok][:12],
        "false": [h["text"][:70] for h, ok in zip(counted, matched_found, strict=True) if not ok][
            :12
        ],
    }


def gold_positions(
    gold: list[list[Any]], blocks: list[dict[str, Any]]
) -> list[tuple[int, str, int]]:
    """(block index, text, level) of each required gold heading, found in order among all
    blocks."""
    out: list[tuple[int, str, int]] = []
    start = 0
    for entry in gold:
        if optional(entry):
            continue
        text, level = entry[0], entry[1]

        # A heading block first; a paragraph with the same text (a plan entry, a missed
        # heading) only when no heading has it.
        def first(types: tuple[str, ...], start: int = start, text: str = text) -> int | None:
            return next(
                (
                    index
                    for index in range(start, len(blocks))
                    if blocks[index]["type"] in types
                    and blocks[index]["extra"].get("role") not in ("toc", "back_matter")
                    and match(text, blocks[index]["text"])
                ),
                None,
            )

        anywhere = first(("heading", "paragraph", "list"))
        heading = first(("heading",))
        # A heading a little further on wins over a paragraph with the same text right
        # before it (a plan entry); a far-away one is another section's.
        if heading is not None and (anywhere is None or heading - anywhere <= HEADING_WINDOW):
            found: int | None = heading
        else:
            found = anywhere
        if found is not None:
            out.append((found, text, level))
            start = found + 1
    return out


def chunk_starts(blocks: list[dict[str, Any]], chunks: list[dict[str, Any]]) -> dict[int, int]:
    """Chunk index -> index of the first block whose opening text the chunk holds."""
    starts: dict[int, int] = {}
    current = 0
    for index, block in enumerate(blocks):
        # The path describes the chunk's body: its first body block decides it, not the
        # headings above it.
        if block["type"] in ("footnote", "heading") or block["extra"].get("role") in (
            "title_page",
            "toc",
            "back_matter",
        ):
            continue
        key = norm(block["text"].split("\n")[0])[:40]
        if len(key) < 8:
            continue
        table = block["type"] == "table" or SEP in block["text"]  # a table or figure row
        for k in range(current, min(current + 4, len(chunks))):
            # A paragraph's opening is not a table cell that happens to say the same.
            lines = chunks[k]["text"].split("\n")
            if any(key in norm(line) and (table or SEP not in line) for line in lines):
                current = k
                starts.setdefault(k, index)
                break
    return starts


def gold_path(positions: list[tuple[int, str, int]], upto: int) -> list[str]:
    """The gold heading path in force at block ``upto``."""
    stack: list[tuple[int, str]] = []
    for index, text, level in positions:
        if index > upto:
            break
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, text))
    return [text for _, text in stack]


def path_accuracy(
    gold: list[list[Any]], blocks: list[dict[str, Any]], chunks: list[dict[str, Any]]
) -> tuple[float | None, list[str]]:
    positions = gold_positions(gold, blocks)
    if not positions:
        return None, []
    starts = chunk_starts(blocks, chunks)
    ok = total = 0
    wrong: list[str] = []
    for k, chunk in enumerate(chunks):
        if k not in starts:
            continue
        expected = gold_path(positions, starts[k])
        accepted = [expected]
        # A short intro under a heading travels with the heading's first subsection and may
        # carry that subsection's path.
        following = next((p for p in positions if p[0] > starts[k]), None)
        if following is not None:
            intro = sum(
                len(b["text"].split())
                for b in blocks[starts[k] : following[0]]
                if b["type"] != "heading"
            )
            inside = norm(blocks[following[0]]["text"])[:40] in norm(chunk["text"])
            if intro < INTRO_WORDS and inside:
                accepted.append(gold_path(positions, following[0]))
        # A chunk that packs several small sections carries what they share.
        end = min((starts[j] for j in starts if j > k), default=len(blocks))
        shared = expected
        for index, text, _ in positions:
            if starts[k] < index < end and norm(text)[:40] in norm(chunk["text"]):
                path = gold_path(positions, index)
                length = 0
                while length < min(len(shared), len(path)) and shared[length] == path[length]:
                    length += 1
                shared = shared[:length]
        accepted.append(shared)
        # Optional gold headings (a separate appendix title, a bold lead-in) may or may not
        # be in the path.
        got = [
            g
            for g in chunk["heading_path"]
            if not any(optional(e) and match(e[0], g) for e in gold)
        ]
        total += 1
        if any(
            len(path) == len(got) and all(match(e, g) for e, g in zip(path, got, strict=True))
            for path in accepted
        ):
            ok += 1
        elif len(wrong) < 6:
            wrong.append(f"C{k}: got {[g[:30] for g in got]} want {[e[:30] for e in expected]}")
    return (ok / total if total else None), wrong


def table_scores(gold: list[dict[str, Any]], blocks: list[dict[str, Any]]) -> dict[str, Any]:
    tables = [b for b in blocks if b["type"] == "table"]

    def columns(block: dict[str, Any]) -> int:
        rows = block["extra"].get("rows")
        if rows:
            return max(len(row) for row in rows)
        return max(len(line.split(SEP)) for line in block["text"].split("\n"))

    found = 0
    missing: list[str] = []
    for want in gold:
        first, last = want["page"], want.get("page_end", want["page"])
        ok = any(
            t["page"] <= first
            and t["extra"].get("page_end", t["page"]) >= last
            and columns(t) >= want["cols"]
            for t in tables
        )
        found += ok
        if not ok:
            missing.append(f"p{first}-{last} cols={want['cols']}")
    return {"found": found, "expected": len(gold), "missing": missing, "blocks": len(tables)}


def chunk_scores(
    document: dict[str, Any], chunks: list[dict[str, Any]], max_tokens: int
) -> dict[str, Any]:
    doc_language = document["language"]["language"]
    tiny = heading_only = colon = repeated_rows = unknown = empty_meta = 0
    for i, chunk in enumerate(chunks):
        text = chunk["text"]
        body = text
        for title in chunk["heading_path"]:
            body = body.replace(title, "", 1)
        body_words = len(WORD.findall(body))
        question = bool(chunk["heading_path"]) and chunk["heading_path"][-1].rstrip().endswith("?")
        # A short question-and-answer chunk is a complete unit, not a fragment.
        if len(chunks) > 1 and chunk["token_count"] < 0.1 * max_tokens and not question:
            tiny += 1
        if chunk["heading_path"] and body_words < 4:
            heading_only += 1
        if text.rstrip().endswith(":"):
            colon += 1
        if i + 1 < len(chunks):
            rows = {line for line in text.split("\n") if SEP in line}
            following = set(chunks[i + 1]["text"].split("\n"))
            # A table's header repeated on purpose at the top of the next chunk is no
            # duplicate.
            headers = {
                SEP.join(" ".join(cell.split()) for cell in row if cell.strip())
                for table in chunks[i + 1].get("metadata", {}).get("tables", [])
                for row in table.get("header", [])
            }
            repeated_rows += len((rows & following) - headers)
        words = WORD.findall(text)
        if doc_language in ("uz", "ru") and chunk["language"] == "unknown" and len(words) >= 20:
            unknown += 1
        if not chunk.get("metadata"):
            empty_meta += 1
    sizes = sorted(c["token_count"] for c in chunks) or [0]
    return {
        "count": len(chunks),
        "median_tokens": sizes[len(sizes) // 2],
        "tiny": tiny,
        "heading_only": heading_only,
        "end_colon": colon,
        "repeated_table_rows": repeated_rows,
        "unknown_language": unknown,
        "empty_metadata": empty_meta,
    }


def artifact_scores(blocks: list[dict[str, Any]]) -> dict[str, int]:
    punct = sum(1 for b in blocks if b["text"].strip() and not re.search(r"\w", b["text"]))
    stretched = sum(
        1
        for b in blocks
        if b["type"] in ("paragraph", "list")
        and len(b["text"].split(SEP)) >= 3
        and all(len(p.split()) == 1 for p in b["text"].split(SEP))
    )
    splits = 0
    body = [
        b
        for b in blocks
        if b["type"] in ("paragraph", "list")
        and b["extra"].get("role") not in ("figure", "formula")
    ]
    for a, b in zip(body, body[1:], strict=False):
        if (
            b["text"][:1].islower()
            and a["text"].rstrip()[-1:] not in ".!?:;"
            and b["page"] - a["page"] <= 1
        ):
            splits += 1
    return {
        "punctuation_blocks": punct,
        "stretched_fragments": stretched,
        "mid_sentence_splits": splits,
    }


# ---------------------------------------------------------------- driver


def evaluate_file(
    path: Path, gold_dir: Path | None, max_tokens: int, overlap: int
) -> dict[str, Any]:
    gold: dict[str, Any] = {}
    if gold_dir is not None and (gold_dir / f"{path.name}.json").exists():
        gold = json.loads((gold_dir / f"{path.name}.json").read_text(encoding="utf-8"))
    tracemalloc.start()
    started = time.perf_counter()
    document = parse(path)
    chunks_obj = Chunker(max_tokens=max_tokens, overlap=overlap).chunk(document)
    seconds = time.perf_counter() - started
    peak = tracemalloc.get_traced_memory()[1] / 2**20
    tracemalloc.stop()
    doc = document.to_dict()
    blocks = doc["blocks"]
    chunks = [c.to_dict() for c in chunks_obj]
    source = source_text(path)
    order_share, order_breaks = order(source, blocks)
    result: dict[str, Any] = {
        "file": path.name,
        "seconds": round(seconds, 2),
        "peak_mb": round(peak, 1),
        "pages": len(doc["pages"]),
        "blocks": len(blocks),
        "route": doc["metadata"]["extra"].get("pdf_route"),
        "language": doc["language"]["language"],
        "fidelity": round(fidelity(source, blocks), 4),
        "order": round(order_share, 4),
        "order_breaks": order_breaks,
        "chunks": chunk_scores(doc, chunks, max_tokens),
        "artifacts": artifact_scores(blocks),
    }
    if gold.get("headings"):
        result["headings"] = heading_scores(gold["headings"], blocks)
        accuracy, wrong = path_accuracy(gold["headings"], blocks, chunks)
        result["paths"] = round(accuracy, 4) if accuracy is not None else None
        result["path_errors"] = wrong
    if gold.get("tables"):
        result["tables"] = table_scores(gold["tables"], blocks)
    return result


def summary_line(r: dict[str, Any]) -> str:
    h = r.get("headings", {})
    t = r.get("tables", {})
    c, a = r["chunks"], r["artifacts"]
    fmt = lambda v: "  -  " if v is None else f"{v:.2f}"  # noqa: E731
    return (
        f"{r['file'][:28]:28} {r['seconds']:6.2f}s {r['peak_mb']:6.1f}MB "
        f"fid={r['fidelity']:.3f} ord={r['order']:.3f}({r['order_breaks']:3}) "
        f"hR={fmt(h.get('recall'))} hP={fmt(h.get('precision'))} path={fmt(r.get('paths'))} "
        f"tab={t.get('found', '-')}/{t.get('expected', '-')} "
        f"chunks={c['count']:3} tiny={c['tiny']:2} hOnly={c['heading_only']:2} "
        f"rowDup={c['repeated_table_rows']:3} unk={c['unknown_language']:2} "
        f"punct={a['punctuation_blocks']:2} stretch={a['stretched_fragments']:2} "
        f"split={a['mid_sentence_splits']:3}"
    )


def draft_gold(path: Path, out: Path) -> None:
    document = parse(path)
    headings = [[b.text[:80], b.level or 1] for b in document.blocks if b.type.value == "heading"]
    target = out / f"{path.name}.json"
    target.write_text(
        json.dumps({"headings": headings, "tables": []}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print("draft", target)


def compare(old_path: Path, new_path: Path) -> None:
    old = {r["file"]: r for r in json.loads(old_path.read_text(encoding="utf-8"))}
    new = {r["file"]: r for r in json.loads(new_path.read_text(encoding="utf-8"))}
    keys = [
        ("fidelity", lambda r: r["fidelity"]),
        ("order", lambda r: r["order"]),
        ("h.recall", lambda r: r.get("headings", {}).get("recall")),
        ("h.precision", lambda r: r.get("headings", {}).get("precision")),
        ("paths", lambda r: r.get("paths")),
        ("tables", lambda r: r.get("tables", {}).get("found")),
        ("tiny", lambda r: r["chunks"]["tiny"]),
        ("heading_only", lambda r: r["chunks"]["heading_only"]),
        ("row_dup", lambda r: r["chunks"]["repeated_table_rows"]),
        ("unknown", lambda r: r["chunks"]["unknown_language"]),
        ("punct", lambda r: r["artifacts"]["punctuation_blocks"]),
        ("stretched", lambda r: r["artifacts"]["stretched_fragments"]),
        ("splits", lambda r: r["artifacts"]["mid_sentence_splits"]),
        ("seconds", lambda r: r["seconds"]),
        ("peak_mb", lambda r: r["peak_mb"]),
    ]
    for name in sorted(set(old) | set(new)):
        if name not in old or name not in new:
            continue
        diffs = []
        for key, get in keys:
            a, b = get(old[name]), get(new[name])
            if a != b:
                diffs.append(f"{key} {a}→{b}")
        print(f"{name[:30]:30} " + ("; ".join(diffs) if diffs else "no change"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("corpus", nargs="?", type=Path)
    parser.add_argument("--gold", type=Path, default=Path(__file__).with_name("gold"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--max-tokens", type=int, default=600)
    parser.add_argument("--overlap", type=int, default=80)
    parser.add_argument("--compare", nargs=2, type=Path)
    parser.add_argument("--draft-gold", type=Path)
    args = parser.parse_args()
    if args.compare:
        compare(*args.compare)
        return
    if args.corpus is None or not args.corpus.is_dir():
        print("corpus folder not found; nothing to evaluate")
        return
    files = sorted(p for p in args.corpus.iterdir() if p.suffix.lower() in (".pdf", ".docx"))
    if args.draft_gold:
        args.draft_gold.mkdir(parents=True, exist_ok=True)
        for path in files:
            draft_gold(path, args.draft_gold)
        return
    results = []
    for path in files:
        result = evaluate_file(path, args.gold, args.max_tokens, args.overlap)
        results.append(result)
        print(summary_line(result), flush=True)
    if args.out:
        args.out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
