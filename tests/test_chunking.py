import pytest
from uzru_parser import Block, BlockType, Chunker, Document, DocumentMetadata, chunk
from uzru_parser.chunking import _Run, _Unit
from uzru_parser.text import estimate_tokens


def make_doc(*blocks: Block) -> Document:
    return Document(metadata=DocumentMetadata(), pages=[], blocks=list(blocks), document_id="doc")


def para(text: str, page: int = 1) -> Block:
    return Block(type=BlockType.PARAGRAPH, text=text, page=page)


def head(text: str, level: int, page: int = 1) -> Block:
    return Block(type=BlockType.HEADING, text=text, page=page, level=level)


def sentences(n: int, prefix: str = "Предложение") -> str:
    return " ".join(f"{prefix} номер {i} описывает условия договора." for i in range(n))


def test_small_document_is_one_chunk() -> None:
    chunks = chunk(make_doc(head("1. ОБЩИЕ ПОЛОЖЕНИЯ", 1), para("Первый."), para("Второй.")))
    assert len(chunks) == 1
    assert chunks[0].text == "1. ОБЩИЕ ПОЛОЖЕНИЯ\n\nПервый.\n\nВторой."
    assert chunks[0].heading_path == ["1. ОБЩИЕ ПОЛОЖЕНИЯ"]
    assert (chunks[0].chunk_id, chunks[0].chunk_index) == ("doc-0000", 0)


def test_heading_hierarchy_in_path() -> None:
    doc = make_doc(
        head("1. UMUMIY QOIDALAR", 1),
        head("1.1. Asosiy tushunchalar", 2),
        para("Matn."),
        head("1.2. Maqsad", 2),
        para("Boshqa matn."),
        head("2. XIZMAT TARTIBI", 1),
        para("Uchinchi."),
    )
    paths = [c.heading_path for c in chunk(doc)]
    assert paths == [
        ["1. UMUMIY QOIDALAR", "1.1. Asosiy tushunchalar"],
        ["1. UMUMIY QOIDALAR", "1.2. Maqsad"],
        ["2. XIZMAT TARTIBI"],
    ]


def test_heading_starts_new_chunk() -> None:
    chunks = chunk(make_doc(para("Вступление."), head("1. РАЗДЕЛ", 1), para("Текст раздела.")))
    assert [c.text for c in chunks] == ["Вступление.", "1. РАЗДЕЛ\n\nТекст раздела."]
    assert chunks[0].heading_path == []


def test_blocks_pack_until_limit() -> None:
    blocks = [para(sentences(1)) for _ in range(6)]
    one = estimate_tokens(blocks[0].text)
    chunks = Chunker(max_tokens=one * 2 + 1, overlap=0).chunk(make_doc(*blocks))
    assert [c.text.count("\n\n") for c in chunks] == [1, 1, 1]
    assert all(c.token_count <= one * 2 + 1 for c in chunks)


def test_token_limit_respected_with_overlap() -> None:
    chunks = Chunker(max_tokens=60, overlap=15).chunk(make_doc(para(sentences(40))))
    assert len(chunks) > 3
    assert all(estimate_tokens(c.text) <= 60 for c in chunks)


def test_overlap_repeats_tail_of_previous_chunk() -> None:
    chunks = Chunker(max_tokens=60, overlap=15).chunk(make_doc(para(sentences(40))))
    for previous, current in zip(chunks, chunks[1:], strict=False):
        last_sentence = previous.text.split(". ")[-1].rstrip(".")
        assert last_sentence in current.text


def test_no_overlap_across_headings() -> None:
    doc = make_doc(head("A", 1), para("Первый абзац."), head("B", 1), para("Второй абзац."))
    chunks = Chunker(max_tokens=50, overlap=10).chunk(doc)
    assert "Первый абзац." not in chunks[1].text


def test_zero_overlap_gives_disjoint_chunks() -> None:
    text = sentences(30)
    chunks = Chunker(max_tokens=50, overlap=0).chunk(make_doc(para(text)))
    assert " ".join(c.text for c in chunks) == text


def test_very_long_paragraph_without_sentence_breaks_splits_by_words() -> None:
    text = " ".join(f"слово{i}" for i in range(500))
    chunks = Chunker(max_tokens=40, overlap=0).chunk(make_doc(para(text)))
    assert all(estimate_tokens(c.text) <= 40 for c in chunks)
    assert " ".join(c.text for c in chunks) == text


def test_list_splits_between_items() -> None:
    items = [f"{i}) пункт номер {i} договора" for i in range(1, 30)]
    block = Block(type=BlockType.LIST, text="\n".join(items), page=1)
    chunks = Chunker(max_tokens=40, overlap=0).chunk(make_doc(block))
    assert len(chunks) > 1
    assert "\n".join(c.text for c in chunks) == block.text


def test_table_rows_stay_whole() -> None:
    rows = [f"Строка {i} | значение {i} | итого {i}" for i in range(30)]
    block = Block(type=BlockType.TABLE, text="\n".join(rows), page=1)
    chunks = Chunker(max_tokens=40, overlap=0).chunk(make_doc(block))
    assert {line for c in chunks for line in c.text.split("\n")} == set(rows)


def test_small_table_is_not_split() -> None:
    block = Block(type=BlockType.TABLE, text="a | b\nc | d", page=1)
    assert [c.text for c in chunk(make_doc(block))] == ["a | b\nc | d"]


def test_empty_blocks_and_document() -> None:
    assert chunk(make_doc()) == []
    assert chunk(make_doc(para(""), para("   "))) == []


def test_page_range_and_language_metadata() -> None:
    doc = make_doc(para("Ushbu qoidalar xizmat tartibi va uchun.", 3), para("Ikkinchi qism.", 4))
    result = chunk(doc)[0]
    assert (result.page_start, result.page_end) == (3, 4)
    assert (result.language, result.script) == ("uz", "latin")
    assert result.to_dict()["heading_path"] == []


def test_custom_token_counter() -> None:
    chunks = Chunker(max_tokens=2, overlap=0, token_counter=lambda t: len(t.split())).chunk(
        make_doc(para("a b c d e"))
    )
    assert [c.text for c in chunks] == ["a b", "c d", "e"]


@pytest.mark.parametrize(("max_tokens", "overlap"), [(0, 0), (10, 10), (10, -1)])
def test_invalid_configuration(max_tokens: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        Chunker(max_tokens=max_tokens, overlap=overlap)


def with_role(block: Block, role: str) -> Block:
    block.extra["role"] = role
    return block


def test_contents_and_back_matter_stay_out_of_chunks() -> None:
    doc = make_doc(
        para("Asosiy matn."),
        with_role(para("MUNDARIJA"), "toc"),
        with_role(para("1-MAVZU ........ 3"), "toc"),
        with_role(para("Nashriyot maʼlumotlari"), "back_matter"),
    )
    assert [c.text for c in chunk(doc)] == ["Asosiy matn."]
    kept = Chunker(skip_roles=()).chunk(doc)
    assert "MUNDARIJA" in kept[0].text


def test_title_page_stays_in_the_document_but_out_of_chunks() -> None:
    doc = make_doc(
        with_role(para("TOSHKENT DAVLAT IQTISODIYOT UNIVERSITETI"), "title_page"),
        head("1-MAVZU: KIRISH", 1),
        para("Matn."),
    )
    chunks = chunk(doc)
    assert [c.text for c in chunks] == ["1-MAVZU: KIRISH\n\nMatn."]
    assert chunks[0].heading_path == ["1-MAVZU: KIRISH"]
    assert doc.blocks[0].text == "TOSHKENT DAVLAT IQTISODIYOT UNIVERSITETI"


def test_topic_heading_starts_a_new_chunk_even_after_a_small_chunk() -> None:
    doc = make_doc(
        head("1-MAVZU: KIRISH", 1),
        para("Qisqa."),
        head("2-MAVZU: PUL", 1),
        head("2.1. Pul aylanmasi", 2),
        para("Matn."),
        head("3-MAVZU: BANK", 1),
        para("Bank matni."),
    )
    chunks = chunk(doc)
    assert [c.heading_path for c in chunks] == [
        ["1-MAVZU: KIRISH"],
        ["2-MAVZU: PUL", "2.1. Pul aylanmasi"],
        ["3-MAVZU: BANK"],
    ]


def test_new_topic_drops_the_previous_topics_subheadings_from_the_path() -> None:
    doc = make_doc(
        head("2-MAVZU: PUL", 1),
        head("2.1. Pul aylanmasi", 2),
        para("Matn."),
        head("4-MAVZU: RISKLAR", 1),
        para("Boshqa matn."),
    )
    assert chunk(doc)[-1].heading_path == ["4-MAVZU: RISKLAR"]


def test_a_heading_is_never_left_alone_in_a_chunk() -> None:
    chunks = chunk(make_doc(head("A bob", 2), head("B bob", 2), para("Matn.")))
    assert [c.text for c in chunks] == ["A bob\n\nB bob\n\nMatn."]
    assert chunks[0].heading_path == ["B bob"]


def test_trailing_heading_without_text_joins_the_previous_chunk() -> None:
    chunks = chunk(make_doc(head("A", 1), para("Matn."), head("B", 1)))
    assert [c.text for c in chunks] == ["A\n\nMatn.\n\nB"]


def test_tiny_chunk_merges_into_the_previous_one_under_the_same_heading() -> None:
    long_text = sentences(6)
    doc = make_doc(
        head("A", 1), para(long_text), para("Qisqa xulosa."), head("B", 1), para(long_text)
    )
    chunks = Chunker(max_tokens=estimate_tokens(long_text) + 10, overlap=0).chunk(doc)
    assert [c.heading_path for c in chunks] == [["A"], ["B"]]
    assert chunks[0].text.endswith("Qisqa xulosa.")


def test_tiny_chunk_does_not_merge_across_headings() -> None:
    chunks = chunk(make_doc(head("A", 1), para("Bir."), head("B", 1), para("Ikki.")))
    assert [c.heading_path for c in chunks] == [["A"], ["B"]]


def test_deep_heading_stays_inline_after_a_tiny_body() -> None:
    doc = make_doc(
        head("1. Bob", 1),
        head("1.1. Qism", 2),
        head("1.1.1. Band", 3),
        para("Qisqa."),
        head("1.1.2. Band", 3),
        para("Yana qisqa."),
    )
    chunks = chunk(doc)
    assert len(chunks) == 1
    assert chunks[0].heading_path == ["1. Bob", "1.1. Qism"]


def test_deep_heading_starts_a_chunk_after_a_substantial_body() -> None:
    doc = make_doc(
        head("1.1.1. Band", 3), para(sentences(8)), head("1.1.2. Band", 3), para("Matn.")
    )
    assert [c.heading_path for c in chunk(doc)] == [["1.1.1. Band"], ["1.1.2. Band"]]


def test_figure_text_never_forms_its_own_chunk() -> None:
    figure = with_role(para("Risklar | Kredit | Foiz"), "figure")
    doc = make_doc(head("A", 1), para(sentences(3)), figure, head("B", 1), figure, para("Matn."))
    chunks = chunk(doc)
    assert len(chunks) == 2
    assert all(c.text.replace("Risklar | Kredit | Foiz", "").strip() for c in chunks)


def test_footnotes_stay_out_of_the_text_and_go_to_metadata() -> None:
    note = Block(type=BlockType.FOOTNOTE, text="2 Manba nomi, 1995", page=1)
    doc = make_doc(para("Birinchi qism"), note, para("ikkinchi qism."))
    result = chunk(doc)
    assert "Manba" not in result[0].text
    assert result[0].metadata["footnotes"] == ["2 Manba nomi, 1995"]


def test_joined_paragraph_reports_both_pages() -> None:
    joined = para("Sahifalar oshib ketgan gap.", page=49)
    joined.extra["page_end"] = 50
    result = chunk(make_doc(joined))[0]
    assert (result.page_start, result.page_end) == (49, 50)


def test_table_chunks_have_no_double_spaces() -> None:
    table = Block(type=BlockType.TABLE, text="a | b\nc | d", page=1)
    assert "  " not in chunk(make_doc(table))[0].text


def test_chunks_do_not_split_inside_abbreviations_or_initials() -> None:
    sentence = "Работы Л. В. Щербы, т. е. его статьи, изданы в 1957 г. в Москве."
    text = " ".join([sentence] * 40)
    chunks = Chunker(max_tokens=60, overlap=0).chunk(make_doc(para(text)))
    assert len(chunks) > 1
    for piece in chunks:
        assert piece.text.startswith("Работы") and piece.text.endswith("Москве.")


def items(n: int) -> Block:
    text = "\n".join(f"• пункт номер {i} описывает условия договора;" for i in range(n))
    return Block(type=BlockType.LIST, text=text, page=1)


def test_lead_in_line_moves_with_the_list_it_introduces() -> None:
    doc = make_doc(
        head("1. ОБЩИЕ ПОЛОЖЕНИЯ", 1),
        para(sentences(6)),
        para("Ограничения предложений"),
        para("Отображаемые в приложении предложения:"),
        items(6),
    )
    chunks = Chunker(max_tokens=100, overlap=0).chunk(doc)
    assert len(chunks) == 2
    assert chunks[0].text.endswith("договора.")
    assert chunks[1].text.startswith("Ограничения предложений\n\nОтображаемые в приложении")


def test_lead_in_stays_when_the_list_fits() -> None:
    doc = make_doc(head("1. ОБЩИЕ ПОЛОЖЕНИЯ", 1), para("Проверьте:"), items(2))
    assert [c.text for c in chunk(doc)] == ["1. ОБЩИЕ ПОЛОЖЕНИЯ\n\nПроверьте:\n\n" + items(2).text]


def test_lead_in_alone_after_a_heading_is_not_moved() -> None:
    doc = make_doc(head("1. ОБЩИЕ ПОЛОЖЕНИЯ", 1), para("Проверьте:"), items(12))
    chunks = Chunker(max_tokens=100, overlap=0).chunk(doc)
    assert chunks[0].text.startswith("1. ОБЩИЕ ПОЛОЖЕНИЯ\n\nПроверьте:\n\n• пункт номер 0")


def test_formula_blocks_never_form_a_chunk_of_their_own() -> None:
    formula = Block(type=BlockType.PARAGRAPH, text="= p& 0 G &", page=1, extra={"role": "formula"})
    doc = make_doc(
        head("1. ОБЩИЕ ПОЛОЖЕНИЯ", 1),
        para(sentences(6)),
        formula,
        head("2. ПРАВА", 1),
        para("Текст."),
    )
    chunks = Chunker(max_tokens=100, overlap=0).chunk(doc)
    assert all(c.text.strip() != formula.text for c in chunks)


def test_overlap_reaches_back_to_the_lead_in_of_a_list() -> None:
    doc = make_doc(
        head("1. ОБЩИЕ ПОЛОЖЕНИЯ", 1),
        para(sentences(8)),
        para("Для этого используются инструменты:"),
        items(2),
        para(sentences(8, "Продолжение")),
    )
    chunks = Chunker(max_tokens=150, overlap=60).chunk(doc)
    for current in chunks[1:]:
        assert not current.text.startswith("•")


def test_overlap_without_room_for_the_lead_in_starts_after_the_list() -> None:
    tail = [
        _Unit("• пункт один;", 4, 1, BlockType.LIST),
        _Unit("Текст после списка.", 5, 1, BlockType.PARAGRAPH),
    ]
    body = [
        _Unit("Длинное вступление к списку, которое не помещается:", 30, 1, BlockType.PARAGRAPH),
        *tail,
    ]
    assert [u.text for u in _Run._complete_list_start(list(tail), body, 1, 10)] == [
        "Текст после списка."
    ]
    assert [u.text for u in _Run._complete_list_start(list(tail), body, 1, 40)][0].endswith(":")


def table(rows: list[list[str]], page: int = 1, spans: list[dict[str, int]] | None = None) -> Block:
    block = Block(
        type=BlockType.TABLE,
        text="\n".join(" | ".join(c for c in row if c) for row in rows),
        page=page,
    )
    block.extra["rows"] = rows
    if spans:
        block.extra["spans"] = spans
    return block


LONG_CELL = (
    "Bojxona organlari tovarlarni rasmiylashtirishda zamonaviy usullarni keng qoʻllaydi va "
    "nazorat qiladi."
)
PESTICIDES = [["T/r", "Nomlanishi", "Konsentratsiya (mg/kg)"]] + [
    [f"{i}.", f"Pestitsid nomi {i} (Pesticide {i})", f"{i},15"] for i in range(1, 90)
]


def test_a_long_table_repeats_its_header_and_never_repeats_rows() -> None:
    chunks = Chunker(max_tokens=200, overlap=40).chunk(make_doc(table(PESTICIDES)))
    assert len(chunks) > 2
    header = "T/r | Nomlanishi | Konsentratsiya (mg/kg)"
    assert all(c.text.startswith(header) for c in chunks)
    rows = [line for c in chunks for line in c.text.split("\n") if line != header]
    assert len(rows) == len(set(rows)) == 89  # every row once, none cut
    assert all(c.token_count <= 200 for c in chunks)
    assert chunks[0].metadata["tables"][0]["continued"] is False
    assert all(c.metadata["tables"][0]["continued"] for c in chunks[1:])
    assert sum(len(c.metadata["tables"][0]["rows"]) for c in chunks) == 89
    assert all(c.metadata["content_type"] == "table" for c in chunks)


def test_overlap_after_a_table_does_not_repeat_its_rows() -> None:
    doc = make_doc(table(PESTICIDES[:20]), para(sentences(40)))
    chunks = Chunker(max_tokens=200, overlap=60).chunk(doc)
    header = "T/r | Nomlanishi | Konsentratsiya (mg/kg)"  # repeated on purpose
    for previous, following in zip(chunks, chunks[1:], strict=False):
        rows = {line for line in previous.text.split("\n") if " | " in line} - {header}
        assert not rows & set(following.text.split("\n"))


@pytest.mark.parametrize(
    ("rows", "spans", "expected"),
    [
        ([["T/r", "Nomi", "Qiymati"], ["1.", "Rux", "23,0"], ["2.", "Mis", "3,0"]], [], 1),
        # a unit line above the header belongs to it
        ([["", "", "(mlrd soʻm)"], ["Manba", "2026-yil", "Jami"], ["Budjet", "40", "109"]], [], 2),
        # a header merged over two columns heads a second header row
        (
            [["Nomi", "Hududlar", ""], ["Nomi", "toza", "ifloslangan"], ["Ichak", "1 – 9", "10"]],
            [{"row": 0, "col": 1, "rows": 1, "cols": 2}],
            2,
        ),
        # numbered items and stray quotes are data
        ([["1.", "Rux", "23,0"], ["2.", "Mis", "3,0"], ["3.", "Kobalt", "5,0"]], [], 0),
        ([["“", "", ""], ["33.", "Undirilishi", "2026-yil"], ["", "", "”."]], [], 0),
        # long sentences are data
        ([[LONG_CELL, "x"], ["a", "b"]], [], 0),
    ],
)
def test_header_rows(rows: list[list[str]], spans: list[dict[str, int]], expected: int) -> None:
    from uzru_parser.chunking import header_row_count

    assert header_row_count(rows, spans) == expected


def test_a_chunk_without_a_language_of_its_own_takes_the_documents() -> None:
    from uzru_parser import LanguageInfo

    names = table(
        [["T/r", "Nomi", "TREK"]] + [[f"{i}.", f"Pyriproxyfen-{i}", "1,15"] for i in range(30)]
    )
    doc = make_doc(head("12-ILOVA", 1), names)
    doc.language = LanguageInfo("uz", "latin", 1.0)
    doc.metadata.title = "Tuproqning sanitariya qoidalari"
    chunks = Chunker(max_tokens=600, overlap=0).chunk(doc)
    assert chunks[0].language == "uz"
    assert chunks[0].metadata["language_source"] == "document"
    assert chunks[0].metadata["is_appendix"] is True
    assert chunks[0].metadata["source_title"] == "Tuproqning sanitariya qoidalari"


def test_a_russian_document_does_not_lend_its_language_to_latin_text() -> None:
    from uzru_parser import LanguageInfo

    doc = make_doc(table([["Pesticide", "Dose"], ["Pyriproxyfen", "1,15"], ["Diazinon", "1,15"]]))
    doc.language = LanguageInfo("ru", "cyrillic", 1.0)
    chunks = chunk(doc)
    assert chunks[0].language != "ru"
    assert chunks[0].metadata["language_source"] == "chunk"


def test_a_short_intro_travels_with_the_first_subsection() -> None:
    doc = make_doc(
        head("1-ILOVA", 1),
        para("Vazirlar Mahkamasining 2026-yil 4-sentabrdagi 464-son qaroriga"),
        head("1-bob. Umumiy qoidalar", 2),
        para(sentences(20)),
        head("2-bob. Yakuniy qoidalar", 2),
        para(sentences(20)),
    )
    chunks = Chunker(max_tokens=600, overlap=0).chunk(doc)
    assert chunks[0].text.startswith("1-ILOVA")
    assert "Umumiy qoidalar" in chunks[0].text
    assert chunks[0].heading_path == ["1-ILOVA", "1-bob. Umumiy qoidalar"]
    assert chunks[1].heading_path == ["1-ILOVA", "2-bob. Yakuniy qoidalar"]
