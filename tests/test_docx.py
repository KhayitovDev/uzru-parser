from pathlib import Path

import docx
import pytest
from uzru_parser import BlockType, Parser, chunk, parse


@pytest.fixture
def contract(tmp_path: Path) -> Path:
    document = docx.Document()
    document.core_properties.title = "Договор"
    document.add_heading("1. ОБЩИЕ ПОЛОЖЕНИЯ", level=1)
    document.add_paragraph("Настоящий договор является основанием для оказания услуг.")
    document.add_heading("1.1. Основные понятия", level=2)
    document.add_paragraph("первый пункт", style="List Bullet")
    document.add_paragraph("второй пункт", style="List Bullet")
    table = document.add_table(rows=2, cols=2)
    for row, values in zip(table.rows, [("Услуга", "Цена"), ("Хлеб", "100")], strict=True):
        for cell, value in zip(row.cells, values, strict=True):
            cell.text = value
    document.add_paragraph("Текст после таблицы.")
    path = tmp_path / "contract.docx"
    document.save(path)
    return path


def test_structure_from_styles(contract: Path) -> None:
    result = parse(contract)
    assert [b.type for b in result.blocks] == [
        BlockType.HEADING,
        BlockType.PARAGRAPH,
        BlockType.HEADING,
        BlockType.LIST,
        BlockType.TABLE,
        BlockType.PARAGRAPH,
    ]
    assert [b.level for b in result.blocks if b.type is BlockType.HEADING] == [1, 2]
    assert result.blocks[3].extra["items"] == ["• первый пункт", "• второй пункт"]
    assert result.blocks[4].extra["rows"] == [["Услуга", "Цена"], ["Хлеб", "100"]]


def test_metadata_and_language(contract: Path) -> None:
    result = Parser().parse(contract)
    assert (result.metadata.format, result.metadata.title) == ("docx", "Договор")
    assert result.language.language == "ru"
    assert result.document_id


def test_chunking_keeps_heading_path(contract: Path) -> None:
    chunks = chunk(parse(contract))
    assert chunks[-1].heading_path == ["1. ОБЩИЕ ПОЛОЖЕНИЯ", "1.1. Основные понятия"]
    assert "Услуга | Цена" in chunks[-1].text


def test_uzbek_text_normalized(tmp_path: Path) -> None:
    document = docx.Document()
    document.add_heading("1. UMUMIY QOIDALAR", level=1)
    document.add_paragraph("O'zbekiston Respublikasi ma'lumot va xizmat uchun qoidalar.")
    document.add_heading("1. УМУМИЙ ҚОИДАЛАР", level=1)
    document.add_paragraph("Ўзбекистон Республикаси ўқувчилар учун ғамхўрлик ва маълумот.")
    path = tmp_path / "uz.docx"
    document.save(path)

    blocks = parse(path).blocks
    assert blocks[1].text.startswith("Oʻzbekiston") and "maʼlumot" in blocks[1].text
    assert blocks[1].language.locale == "uz-Latn"
    assert blocks[3].language.locale == "uz-Cyrl"


def test_unstyled_headings_use_heuristics(tmp_path: Path) -> None:
    document = docx.Document()
    for title in ("1. ОБЩИЕ ПОЛОЖЕНИЯ", "2. ПРЕДМЕТ ДОГОВОРА"):
        document.add_paragraph().add_run(title).bold = True
        document.add_paragraph("Текст раздела договора.")
    path = tmp_path / "plain.docx"
    document.save(path)
    assert [b.type for b in parse(path).blocks] == [
        BlockType.HEADING,
        BlockType.PARAGRAPH,
        BlockType.HEADING,
        BlockType.PARAGRAPH,
    ]


def test_lone_bold_numbered_line_in_docx_is_a_list_item(tmp_path: Path) -> None:
    document = docx.Document()
    document.add_paragraph("Talablar quyidagilardan iborat.")
    document.add_paragraph().add_run("4. Hujjatlarni oʻz vaqtida topshirish").bold = True
    path = tmp_path / "item.docx"
    document.save(path)
    assert [b.type for b in parse(path).blocks] == [BlockType.PARAGRAPH, BlockType.LIST]


def test_explicit_page_breaks_advance_pages(tmp_path: Path) -> None:
    document = docx.Document()
    document.add_paragraph("Первая страница.")
    document.add_page_break()
    document.add_paragraph("Вторая страница.")
    path = tmp_path / "pages.docx"
    document.save(path)

    result = parse(path)
    assert [b.page for b in result.blocks] == [1, 2]
    assert result.metadata.page_count == 2
    assert result.metadata.extra["pages_approximate"]


def test_docx_mixed_alphabet_words_are_fixed(tmp_path: Path) -> None:
    document = docx.Document()
    document.add_paragraph("Vаlyutа bozori va mа’lumot tizimi.")
    path = tmp_path / "mixed.docx"
    document.save(path)
    result = parse(path)
    assert result.blocks[0].text == "Valyuta bozori va maʼlumot tizimi."
    assert result.metadata.extra["mixed_script_words_fixed"] == 2
