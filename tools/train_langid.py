"""Train the character n-gram language model used by src/langid.rs.

Offline tool: it is not part of the package and needs no extra dependencies.

Usage:
  python tools/train_langid.py --uz-ud uz_ut-ud-test.conllu --uz-stems CSV_DIR \
      --ru-ud ru_gsd-ud-train.conllu --en-ud en_ewt-ud-train.conllu \
      [--uz-books-lat lat.parquet --uz-books-cyr cyr.parquet] [-o src/data/langid.bin]

Classes: Uzbek Latin, Uzbek Cyrillic, Russian, other Latin (English). Uzbek Cyrillic text comes
from transliterating the Uzbek Latin text and, when given, the uz-books Cyrillic split (reading
it needs pyarrow). Sources and licences: THIRD_PARTY.md.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import re
import struct
import unicodedata
from collections import Counter
from pathlib import Path

CLASSES = ("uz_latn", "uz_cyrl", "ru", "other_latn")
MAX_ORDER = 4
TABLE_SIZE = 30_000
SMOOTHING = 0.5
HELD_OUT = 0.1
QUANT = 1000.0
MAGIC = b"UZLID1"

APOSTROPHES = "'’ʼʻ`‘´ʹ′"
WORD = re.compile(rf"[^\W\d_](?:[^\W\d_]|[{APOSTROPHES}])*")

LATIN_TO_CYRILLIC = [
    ("o'", "ў"), ("g'", "ғ"), ("sh", "ш"), ("ch", "ч"), ("yo", "ё"), ("yu", "ю"),
    ("ya", "я"), ("ye", "е"), ("ts", "ц"), ("a", "а"), ("b", "б"), ("d", "д"), ("e", "е"),
    ("f", "ф"), ("g", "г"), ("h", "ҳ"), ("i", "и"), ("j", "ж"), ("k", "к"), ("l", "л"),
    ("m", "м"), ("n", "н"), ("o", "о"), ("p", "п"), ("q", "қ"), ("r", "р"), ("s", "с"),
    ("t", "т"), ("u", "у"), ("v", "в"), ("x", "х"), ("y", "й"), ("z", "з"), ("'", "ъ"),
]  # fmt: skip
VOWELS = set("aeiouаеиоуўэяюё")


def fnv1a(text: str) -> int:
    value = 0x811C9DC5
    for byte in text.encode():
        value = ((value ^ byte) * 0x01000193) & 0xFFFFFFFF
    return value


def words(text: str) -> list[str]:
    """Feature words: lowercase letters with one apostrophe form; must match langid.rs."""
    text = unicodedata.normalize("NFC", text).lower()
    return [re.sub(f"[{APOSTROPHES}]", "'", w) for w in WORD.findall(text)]


def ngrams(word: str) -> list[str]:
    padded = f" {word} "
    grams = list(word)
    for order in range(2, MAX_ORDER + 1):
        grams.extend(padded[i : i + order] for i in range(len(padded) - order + 1))
    return grams


def to_cyrillic(text: str) -> str:
    """Uzbek Latin to Cyrillic: "e" is "э" at a word start, "ts" is "ц" only in "-tsiya"."""
    out: list[str] = []
    for word in re.split(r"(\W+)", unicodedata.normalize("NFC", text).lower()):
        word = re.sub(f"[{APOSTROPHES}]", "'", word)
        result, i = "", 0
        while i < len(word):
            if word[i] == "e" and (i == 0 or word[i - 1] in VOWELS):
                result, i = result + "э", i + 1
                continue
            for latin, cyrillic in LATIN_TO_CYRILLIC:
                if latin == "ts" and not word.startswith("tsiya", i):
                    continue
                if word.startswith(latin, i):
                    result, i = result + cyrillic, i + len(latin)
                    break
            else:
                result, i = result + word[i], i + 1
        out.append(result)
    return "".join(out)


def conllu_sentences(path: Path) -> list[str]:
    prefix = "# text = "
    with path.open(encoding="utf-8") as handle:
        return [line[len(prefix) :].strip() for line in handle if line.startswith(prefix)]


def stem_words(folder: Path) -> list[str]:
    found: list[str] = []
    for path in sorted(folder.rglob("*.csv")):
        with path.open(encoding="utf-8-sig") as handle:
            for row in csv.reader(handle):
                found.extend(w.strip() for cell in row for w in cell.split(",") if w.strip())
    return found


BOOK_CHARS = 4_000_000
MIN_BOOK_LINE = 40
RUSSIAN_ONLY = re.compile("[ыщЫЩ]")
LATIN = re.compile("[A-Za-z]")
CYRILLIC = re.compile("[\u0400-\u04ff]")


def book_lines(path: Path, cyrillic: bool) -> list[str]:
    """Clean lines of the first books in a uz-books Parquet file, up to ``BOOK_CHARS``. Lines
    with Russian-only letters or the other alphabet (OCR noise, quotes) are left out."""
    import pyarrow.parquet as pq

    lines: list[str] = []
    size = 0
    table = pq.ParquetFile(path).read_row_group(0, columns=["text"])
    for book in table.column("text").to_pylist():
        for line in book.split("\n"):
            line = line.strip()
            other = LATIN if cyrillic else CYRILLIC
            if len(line) < MIN_BOOK_LINE or other.search(line) or RUSSIAN_ONLY.search(line):
                continue
            lines.append(line)
            size += len(line)
            if size >= BOOK_CHARS:
                return lines
    return lines


def split(sentences: list[str], rng: random.Random) -> tuple[list[str], list[str]]:
    shuffled = sentences[:]
    rng.shuffle(shuffled)
    cut = max(1, int(len(shuffled) * HELD_OUT))
    return shuffled[cut:], shuffled[:cut]


def count(texts: list[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for text in texts:
        for word in words(text):
            counts.update(ngrams(word))
    return counts


class Model:
    def __init__(self, counts: dict[str, Counter[str]]) -> None:
        totals: Counter[str] = Counter()
        for c in counts.values():
            totals.update(c)
        kept = [g for g, _ in totals.most_common(TABLE_SIZE)]
        self.table: dict[str, list[float]] = {}
        self.floor: list[list[float]] = []
        vocab = [len({g for g in totals if len(g) == n}) for n in range(1, MAX_ORDER + 1)]
        mass = {
            cls: [
                sum(v for g, v in counts[cls].items() if len(g) == n)
                for n in range(1, MAX_ORDER + 1)
            ]
            for cls in CLASSES
        }
        for cls in CLASSES:
            self.floor.append(
                [
                    math.log(SMOOTHING / (mass[cls][n] + SMOOTHING * vocab[n]))
                    for n in range(MAX_ORDER)
                ]
            )
        for gram in kept:
            n = len(gram) - 1
            self.table[gram] = [
                math.log((counts[cls][gram] + SMOOTHING) / (mass[cls][n] + SMOOTHING * vocab[n]))
                for cls in CLASSES
            ]
        self.temperature = 1.0

    def logp(self, gram: str, cls: int) -> float:
        row = self.table.get(gram)
        return row[cls] if row else self.floor[cls][len(gram) - 1]

    def margin(self, text: str, a: int, b: int) -> float:
        """Mean log-likelihood ratio of class ``a`` over ``b`` per n-gram."""
        grams = [g for w in words(text) for g in ngrams(w)]
        if not grams:
            return 0.0
        return sum(self.logp(g, a) - self.logp(g, b) for g in grams) / len(grams)


def evaluate(model: Model, held: dict[str, list[str]]) -> None:
    pairs = {"uz_latn": 3, "other_latn": 0, "uz_cyrl": 2, "ru": 1}
    for max_words in (1, 2, 3, 5, 0):
        right = total = 0
        for cls, sentences in held.items():
            index = CLASSES.index(cls)
            other = pairs[cls]
            for sentence in sentences:
                tokens = sentence.split()
                pieces = (
                    [" ".join(tokens[i : i + max_words]) for i in range(0, len(tokens), max_words)]
                    if max_words
                    else [sentence]
                )
                for piece in pieces:
                    if not words(piece):
                        continue
                    total += 1
                    right += model.margin(piece, index, other) > 0
        label = f"{max_words} words" if max_words else "sentences"
        print(f"held-out accuracy, {label:>10}: {100 * right / total:.1f}% ({total})")


def write(model: Model, path: Path) -> None:
    entries = sorted((fnv1a(g), row) for g, row in model.table.items())
    with path.open("wb") as handle:
        handle.write(MAGIC)
        handle.write(struct.pack("<BBI", len(CLASSES), MAX_ORDER, len(entries)))
        for floors in model.floor:
            handle.write(struct.pack(f"<{MAX_ORDER}f", *floors))
        for key, row in entries:
            handle.write(struct.pack("<I", key))
            handle.write(struct.pack(f"<{len(CLASSES)}h", *(round(v * QUANT) for v in row)))
    print(f"wrote {path} ({path.stat().st_size // 1024} KB, {len(entries)} n-grams)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--uz-ud", type=Path, required=True)
    parser.add_argument("--uz-stems", type=Path, required=True)
    parser.add_argument("--ru-ud", type=Path, required=True)
    parser.add_argument("--en-ud", type=Path, required=True)
    parser.add_argument("--uz-books-lat", type=Path, help="uz-books Latin Parquet file")
    parser.add_argument("--uz-books-cyr", type=Path, help="uz-books Cyrillic Parquet file")
    parser.add_argument("-o", "--output", type=Path, default=Path("src/data/langid.bin"))
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    uz_train, uz_held = split(conllu_sentences(args.uz_ud), rng)
    ru_train, ru_held = split(conllu_sentences(args.ru_ud), rng)
    en_train, en_held = split(conllu_sentences(args.en_ud), rng)
    stems = stem_words(args.uz_stems)
    uz_text = uz_train + stems
    lat_books = book_lines(args.uz_books_lat, False) if args.uz_books_lat else []
    cyr_books = book_lines(args.uz_books_cyr, True) if args.uz_books_cyr else []
    counts = {
        "uz_latn": count(uz_text + lat_books),
        "uz_cyrl": count([to_cyrillic(t) for t in uz_text] + cyr_books),
        "ru": count(ru_train),
        "other_latn": count(en_train[: len(ru_train)]),
    }
    model = Model(counts)
    held = {
        "uz_latn": uz_held,
        "uz_cyrl": [to_cyrillic(t) for t in uz_held],
        "ru": ru_held[: 4 * len(uz_held)],
        "other_latn": en_held[: 4 * len(uz_held)],
    }
    evaluate(model, held)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write(model, args.output)


if __name__ == "__main__":
    main()
