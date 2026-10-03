from uzru_parser.layout import strip_page_furniture
from uzru_parser.structure import RawBlock

HEIGHTS = {1: 800.0, 2: 800.0, 3: 800.0}


def block(text: str, page: int, y: float) -> RawBlock:
    return RawBlock(text=text, page=page, bbox=(50, y, 300, y + 10))


def test_page_numbers_removed_in_margins_only() -> None:
    blocks = [block("12", 1, 20), block("Страница 3 из 10", 1, 780), block("12", 1, 400)]
    kept, removed = strip_page_furniture(blocks, HEIGHTS)
    assert [b.text for b in kept] == ["12"] and removed == 2
    assert kept[0].bbox is not None and kept[0].bbox[1] == 400


def test_repeated_header_with_changing_number_removed() -> None:
    blocks = [block(f"Договор № 15, стр. {n}", n, 20) for n in (1, 2, 3)]
    blocks.append(block("Текст", 1, 300))
    kept, removed = strip_page_furniture(blocks, HEIGHTS)
    assert [b.text for b in kept] == ["Текст"] and removed == 3


def test_unique_margin_text_kept() -> None:
    blocks = [block("Приложение 1", 1, 20), block("Подпись директора", 3, 780)]
    kept, removed = strip_page_furniture(blocks, HEIGHTS)
    assert len(kept) == 2 and removed == 0


def test_tables_and_missing_geometry_untouched() -> None:
    table = RawBlock(text="", page=1, bbox=(0, 20, 100, 30), rows=[["1", "2"]])
    no_bbox = RawBlock(text="5", page=1)
    kept, removed = strip_page_furniture([table, no_bbox], HEIGHTS)
    assert len(kept) == 2 and removed == 0
