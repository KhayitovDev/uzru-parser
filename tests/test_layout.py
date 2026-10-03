from uzru_parser.layout import mark_footnotes, mark_title_page, mark_toc, strip_page_furniture
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


def page_block(text: str, page: int, y: float, size: float = 11.0) -> RawBlock:
    return RawBlock(text=text, page=page, bbox=(50, y, 500, y + 12), font_size=size)


def test_footnote_at_page_foot_in_small_font_is_flagged() -> None:
    note = page_block("22 Банковское дело. Учебник для вузов. СПб: Питер", 2, 760, size=8)
    body_text = page_block("Oddiy matn bu yerda.", 2, 300)
    numbered_item = page_block("5 band bo‘yicha matn", 2, 300)
    mark_footnotes([note, body_text, numbered_item], {2: 842.0}, 11.0)
    assert (note.footnote, body_text.footnote, numbered_item.footnote) == (True, False, False)


def test_footnote_needs_the_foot_of_the_page() -> None:
    high = page_block("3 Manba nomi va yili", 2, 200, size=8)
    mark_footnotes([high], {2: 842.0}, 11.0)
    assert not high.footnote


def test_footnote_with_a_matching_reference_mark_is_flagged_at_body_size() -> None:
    text = RawBlock(
        text="Matn", page=2, bbox=(50, 300, 500, 312), font_size=11, footnote_refs=["8"]
    )
    note = page_block("8 A.Oʻlmasov. Iqtisodiyot nazariyasi. T.: Mehnat, 1995", 2, 760)
    mark_footnotes([text, note], {2: 842.0}, 11.0)
    assert note.footnote


def test_short_first_page_is_marked_as_title_page() -> None:
    blocks = [
        page_block("OʻZBEKISTON RESPUBLIKASI OLIY TAʼLIM VAZIRLIGI", 1, 80, size=16),
        page_block("TOSHKENT DAVLAT IQTISODIYOT UNIVERSITETI", 1, 120, size=16),
        page_block("BANK ISHI VA MOLIYA ASOSLARI", 1, 280, size=24),
        page_block("Matn " * 30, 2, 100),
    ]
    mark_title_page(blocks, page_count=240)
    assert [b.role for b in blocks] == ["title_page", "title_page", "title_page", None]


def test_text_heavy_or_single_page_documents_have_no_title_page() -> None:
    dense = [page_block("so‘z " * 60, 1, 100 + 20 * i) for i in range(4)]
    mark_title_page(dense, page_count=10)
    assert all(b.role is None for b in dense)
    short = [page_block(f"Qisqa {i}", 1, 100 + 20 * i) for i in range(4)]
    mark_title_page(short, page_count=2)
    assert all(b.role is None for b in short)


def test_contents_pages_are_marked_and_back_matter_follows() -> None:
    blocks = [page_block("Asosiy matn.", 100, 100)]
    blocks += [
        page_block("MUNDARIJA", 236, 80),
        page_block("1-MAVZU: KIRISH. (BANK ISHI VA MOLIYA ASOSLARI FANINING", 236, 110),
        page_block("PREDMETI). 1.1. Banklarning paydo boʻlish sabablari ……… 3", 236, 140),
        page_block("1.2. Pulning mohiyati va namoyon boʻlish shakllari ……… 6", 236, 170),
        page_block("2-MAVZU: PUL VA BANK ISHI ………… 17", 237, 100),
    ]
    blocks += [page_block("NASHRIYOT-MATBAA UYI. Bosishga ruxsat etildi.", 239, 100)]
    mark_toc(blocks, page_count=240)
    assert [b.role for b in blocks] == [None, "toc", "toc", "toc", "toc", "toc", "back_matter"]


def test_leader_lines_without_a_title_are_still_a_contents() -> None:
    blocks = [
        page_block(f"{n}-bob. Sarlavha ........ {n * 10}", 3, 100 + 20 * n) for n in range(1, 5)
    ]
    blocks.append(page_block("Oddiy gap.", 4, 100))
    mark_toc(blocks, page_count=200)
    assert [b.role for b in blocks] == ["toc"] * 4 + [None]


def test_contents_in_the_middle_leaves_the_rest_alone() -> None:
    blocks = [
        page_block("Mundarija", 2, 80),
        page_block("1-bob ........ 5", 2, 100),
        page_block("2-bob ........ 9", 2, 120),
        page_block("3-bob ........ 14", 2, 140),
        page_block("Birinchi bob matni.", 5, 100),
    ]
    mark_toc(blocks, page_count=200)
    assert [b.role for b in blocks] == ["toc", "toc", "toc", "toc", None]


def test_a_few_leader_lines_are_not_a_contents() -> None:
    blocks = [page_block("Narx ........ 5", 3, 100), page_block("Matn.", 3, 130)]
    mark_toc(blocks, page_count=10)
    assert all(b.role is None for b in blocks)


def test_page_numbers_in_a_separate_column_belong_to_the_contents() -> None:
    blocks = [
        page_block("MUNDARIJA", 236, 80),
        page_block("1-MAVZU: KIRISH", 236, 100),
        page_block("1.1. Banklarning paydo boʻlish sabablari ………", 236, 120),
        page_block("3", 236, 120),
        page_block("1.2. Pulning mohiyati ………", 236, 140),
        page_block("6", 236, 140),
        page_block("2-MAVZU: PUL VA BANK ISHI", 237, 100),
        page_block("2.1. Pul aylanmasi ………", 237, 120),
        page_block("17", 237, 120),
        page_block("Nashriyot maʼlumotlari", 239, 100),
    ]
    mark_toc(blocks, page_count=240)
    assert [b.role for b in blocks] == ["toc"] * 9 + ["back_matter"]
