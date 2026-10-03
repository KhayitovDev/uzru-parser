"""Build the word list used by src/lexicon.rs (real-word checks for joins).

Offline tool, not part of the package. Reading uz-books needs pyarrow.

Usage:
  python tools/build_lexicon.py --uz-ud uz_ut-ud-test.conllu --uz-stems CSV_DIR \\
      --uz-books-lat lat.parquet --ru-ud ru_gsd-ud-train.conllu [-o src/data/lexicon.txt]

Words are stored as stems: endings from the lists in the file header are stripped repeatedly
(Uzbek) or once (Russian) while at least ``MIN_STEM`` letters remain. src/lexicon.rs reads
the same lists and strips words the same way before looking them up. Uzbek is stored in Latin;
Uzbek Cyrillic words are transliterated before lookup. Sources: THIRD_PARTY.md.
"""

from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from collections import Counter
from pathlib import Path

MIN_STEM = 4
UZ_ROUNDS = 3
RU_ROUNDS = 1
#: uz-books is OCR text: a word must occur this often to be trusted.
MIN_BOOK_COUNT = 5
BOOK_CHARS = 60_000_000

UZ_ENDINGS = (
    "lar ning ni ga da dan dagi gacha im ing i si imiz ingiz miz di gan ib moq ish moqda adi "
    "ydi yapti lik"
).split()
RU_ENDINGS = (
    "ами ями ого его ому ему ыми ими ых их ую юю ая яя ое ее ые ие ой ей ий ый ом ем ам ям ах ях "
    "ов ев ть ться тся ет ют ут ит ат ят ешь ишь ал ала ало али ил ила ило или ла ло ли а я о е ы "
    "и у ю ь й"
).split()

APOSTROPHES = "'’ʼʻ`‘´ʹ′"
WORD = re.compile(rf"[^\W\d_](?:[^\W\d_]|[{APOSTROPHES}])*")
LATIN_WORD = re.compile(r"[a-z']+")
RUSSIAN_WORD = re.compile(r"[а-яё]+")
VOWEL = re.compile("[aeiou]")


def normalize(word: str) -> str:
    word = unicodedata.normalize("NFC", word).lower()
    return re.sub(f"[{APOSTROPHES}]", "'", word).strip("'")


def stem(word: str, endings: list[str], rounds: int) -> str:
    """Strip the longest listed ending, up to ``rounds`` times; must match lexicon.rs."""
    ordered = sorted(endings, key=len, reverse=True)
    for _ in range(rounds):
        for ending in ordered:
            if word.endswith(ending) and len(word) - len(ending) >= MIN_STEM:
                word = word[: -len(ending)]
                break
        else:
            break
    return word


def uz_words(args: argparse.Namespace) -> set[str]:
    found: set[str] = set()
    for line in args.uz_ud.open(encoding="utf-8"):
        if line.startswith("# text = "):
            found.update(normalize(w) for w in WORD.findall(line[9:]))
    for path in sorted(args.uz_stems.rglob("*.csv")):
        with path.open(encoding="utf-8-sig") as handle:
            for row in csv.reader(handle):
                for cell in row:
                    found.update(normalize(w) for w in cell.split(",") if w.strip())
    if args.uz_books_lat:
        import pyarrow.parquet as pq

        counts: Counter[str] = Counter()
        size = 0
        file = pq.ParquetFile(args.uz_books_lat)
        for group in range(file.num_row_groups):
            for book in file.read_row_group(group, columns=["text"]).column("text").to_pylist():
                counts.update(normalize(w) for w in WORD.findall(book))
                size += len(book)
            if size >= BOOK_CHARS:
                break
        found.update(w for w, n in counts.items() if n >= MIN_BOOK_COUNT)
    return {w for w in found if LATIN_WORD.fullmatch(w) and VOWEL.search(w)}


def ru_words(path: Path) -> set[str]:
    found: set[str] = set()
    for line in path.open(encoding="utf-8"):
        cells = line.split("\t")
        if len(cells) > 3 and cells[0].isdigit() and cells[3] != "PROPN":
            found.update(normalize(cells[1]).replace("ё", "е") for _ in [0])
            found.add(normalize(cells[2]).replace("ё", "е"))
    return {w for w in found if RUSSIAN_WORD.fullmatch(w)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--uz-ud", type=Path, required=True)
    parser.add_argument("--uz-stems", type=Path, required=True)
    parser.add_argument("--uz-books-lat", type=Path)
    parser.add_argument("--ru-ud", type=Path, required=True)
    parser.add_argument("-o", "--output", type=Path, default=Path("src/data/lexicon.txt"))
    args = parser.parse_args()

    uz = sorted({stem(w, UZ_ENDINGS, UZ_ROUNDS) for w in uz_words(args)})
    ru = sorted({stem(w, RU_ENDINGS, RU_ROUNDS) for w in ru_words(args.ru_ud)})
    with args.output.open("w", encoding="utf-8") as out:
        out.write(f"#min-stem {MIN_STEM}\n")
        out.write(f"#uz-endings {UZ_ROUNDS} {' '.join(UZ_ENDINGS)}\n")
        out.write(f"#ru-endings {RU_ROUNDS} {' '.join(RU_ENDINGS)}\n")
        out.write("#uz\n" + "\n".join(uz) + "\n#ru\n" + "\n".join(ru) + "\n")
    size = args.output.stat().st_size // 1024
    print(f"wrote {args.output} ({size} KB): {len(uz)} Uzbek stems, {len(ru)} Russian stems")


if __name__ == "__main__":
    main()
