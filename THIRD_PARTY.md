# Third-Party Notices

uzru-parser's source code is licensed under the MIT License (see `LICENSE`). This file lists
all third-party material the project contains, was built from, or depends on, with the
licence terms that apply. Full licence texts are in `LICENSES/`.

## Licence summary

| Part of the project | Licence |
|---|---|
| Source code (Python, Rust), tests and tools | MIT (`LICENSE`) |
| Data files `src/data/langid.bin` and `src/data/lexicon.txt` | CC BY-SA 4.0 (`src/data/LICENSE`), because they are adapted from CC BY-SA 4.0 sources |
| Portions adapted from third parties | Their own licences, listed below |

## 1. Bundled data files

### 1.1 Language model — `src/data/langid.bin`

Character n-gram statistics computed by `tools/train_langid.py`. No source text is included.

| Source | Authors | Licence | Use |
|---|---|---|---|
| [UD_Uzbek-UT](https://github.com/UniversalDependencies/UD_Uzbek-UT) | Arofat Akhundjanova, Luigi Talamo | CC BY-SA 4.0 | Uzbek sentences, also transliterated to Cyrillic |
| [UD_Russian-GSD](https://github.com/UniversalDependencies/UD_Russian-GSD) | Universal Dependencies contributors | CC BY-SA 4.0 | Russian sentences |
| [UD_English-EWT](https://github.com/UniversalDependencies/UD_English-EWT) | Universal Dependencies contributors | CC BY-SA 4.0 | English text (other Latin-script class) |
| [UzbekLemmaStems-POS-Dataset](https://github.com/MaksudSharipov/UzbekLemmaStems-POS-Dataset) | Maksud Sharipov | Apache-2.0 | Uzbek word list, also transliterated to Cyrillic |
| [tahrirchi/uz-books-v2](https://huggingface.co/datasets/tahrirchi/uz-books-v2) | Tahrirchi | MIT | Uzbek Latin and Cyrillic book text (first 4 million characters of one file per split) |

Changes made: sentences and words were lowercased, transliterated where noted, split into
1–4 character sequences, counted, smoothed, converted to quantized log-probabilities and
reduced to the 30,000 most frequent sequences.

### 1.2 Word list — `src/data/lexicon.txt`

Word stems produced by `tools/build_lexicon.py`.

| Source | Authors | Licence | Use |
|---|---|---|---|
| [tahrirchi/uz-books-v2](https://huggingface.co/datasets/tahrirchi/uz-books-v2) | Tahrirchi | MIT | Uzbek words seen at least 5 times in one Latin file |
| [UzbekLemmaStems-POS-Dataset](https://github.com/MaksudSharipov/UzbekLemmaStems-POS-Dataset) | Maksud Sharipov | Apache-2.0 | Uzbek stems and lemmas |
| [UD_Uzbek-UT](https://github.com/UniversalDependencies/UD_Uzbek-UT) | Arofat Akhundjanova, Luigi Talamo | CC BY-SA 4.0 | Uzbek word forms |
| [UD_Russian-GSD](https://github.com/UniversalDependencies/UD_Russian-GSD) | Universal Dependencies contributors | CC BY-SA 4.0 | Russian word forms and lemmas (proper nouns excluded) |

Changes made: words were lowercased, apostrophes unified, filtered, reduced to stems by
stripping endings, deduplicated and sorted.

## 2. Code and rules adapted from third parties

| Material | Where | Licence |
|---|---|---|
| [natasha/razdel](https://github.com/natasha/razdel): sentence segmentation method, rules, Russian abbreviation lists, unit test cases | `src/sentences.rs` | MIT (notice in section 6.1) |
| Unicode confusables data ([UTS #39](https://www.unicode.org/reports/tr39/), `confusables.txt`): Cyrillic–Latin look-alike pairs | `src/confusables.rs` | Unicode License v3 (`LICENSES/Unicode-3.0.txt`) |
| Adobe Symbol encoding to Unicode mapping ([Adobe Glyph List](https://github.com/adobe-type-tools/agl-aglfn)) | `src/symbols.rs` | BSD-3-Clause (notice in section 6.3) |

## 3. Rust libraries compiled into the extension module

All are used unmodified, as published on crates.io.

| Crate | Licence |
|---|---|
| pyo3, pyo3-ffi, pyo3-macros, pyo3-macros-backend, pyo3-build-config | MIT OR Apache-2.0 |
| unicode-normalization | MIT OR Apache-2.0 |
| tinyvec | Zlib OR Apache-2.0 OR MIT |
| libc, once_cell, portable-atomic, indoc, unindent, heck, rustversion, autocfg | MIT OR Apache-2.0 |
| memoffset | MIT |
| syn, quote, proc-macro2 (build time only) | MIT OR Apache-2.0 |
| unicode-ident (build time only) | (MIT OR Apache-2.0) AND Unicode-3.0 |
| target-lexicon (build time only) | Apache-2.0 WITH LLVM-exception |

## 4. Python runtime dependencies (installed separately, not bundled)

| Package | Licence | Note |
|---|---|---|
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) | **AGPL-3.0** or Artifex commercial licence | Used for PDF input. Distributing or offering a service built on uzru-parser together with PyMuPDF requires compliance with the AGPL-3.0 or a commercial licence from Artifex. |
| [python-docx](https://github.com/python-openxml/python-docx) | MIT | Used for DOCX input. |
| [lxml](https://github.com/lxml/lxml) (dependency of python-docx) | BSD-3-Clause | |

## 5. Development only (not distributed)

| Material | Licence | Use |
|---|---|---|
| [pyarrow](https://github.com/apache/arrow) | Apache-2.0 | Reading uz-books Parquet files in `tools/` |
| razdel evaluation corpora | see razdel | Measuring sentence splitting; not included |
| pytest, ruff, mypy, maturin | MIT / Apache-2.0 | Testing and building |
| [DejaVu Sans](https://dejavu-fonts.github.io/) fonts in `tests/fonts/` | Bitstream Vera licence (DejaVu changes public domain); notice in `tests/fonts/LICENSE` | Generating test PDFs the same way on every platform; not installed with the package |

Material reviewed and deliberately **not** used because of its licence: Uzbek and Russian
Hunspell dictionaries (GPL), Text-Hyphen-RU patterns (GPL-3.0), Pyphen dictionaries
(GPL/LGPL/MPL), PyMuPDF-Utilities and PyMuPDF4LLM code (AGPL-3.0), RusLawOD (CC BY-NC 4.0),
coppercitylabs/uzbek-tokenizers and murodbek/uz-text-classification (no licence stated).

## 6. Licence notices

### 6.1 razdel

```
MIT License

Copyright (c) 2017

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### 6.2 tahrirchi/uz-books-v2

The dataset card states `license: mit` and gives no separate copyright line.

```
MIT License

Copyright (c) Tahrirchi

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### 6.3 Adobe Glyph List

```
Copyright 2002-2019 Adobe (http://www.adobe.com/).

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

Redistributions of source code must retain the above copyright notice,
this list of conditions and the following disclaimer.

Redistributions in binary form must reproduce the above copyright
notice, this list of conditions and the following disclaimer in the
documentation and/or other materials provided with the distribution.

Neither the name of Adobe nor the names of its contributors may be
used to endorse or promote products derived from this software without
specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

### 6.4 UzbekLemmaStems-POS-Dataset

Licensed under the Apache License, Version 2.0 (`LICENSES/Apache-2.0.txt`). The repository
provides no NOTICE file. Changes are described in section 1.

### 6.5 Universal Dependencies treebanks

UD_Uzbek-UT, UD_Russian-GSD and UD_English-EWT are licensed under the Creative Commons
Attribution-ShareAlike 4.0 International licence (`LICENSES/CC-BY-SA-4.0.txt`,
https://creativecommons.org/licenses/by-sa/4.0/). The data files adapted from them are shared
under the same licence (`src/data/LICENSE`).

### 6.6 Unicode

The Cyrillic–Latin pairs in `src/confusables.rs` are taken from the Unicode confusables data,
licensed under the Unicode License v3 (`LICENSES/Unicode-3.0.txt`).
