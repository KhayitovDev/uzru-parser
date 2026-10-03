from pathlib import Path

from uzru_parser import Block, BlockType, Page
from uzru_parser.assemble import assemble_document
from uzru_parser.models import LanguageInfo


def block(text: str, language: str, script: str = "latin", **extra: object) -> Block:
    return Block(
        type=BlockType.PARAGRAPH,
        text=text,
        page=1,
        language=LanguageInfo(language, script, 1.0),
        extra=dict(extra),
    )


def assemble(blocks: list[Block]):
    return assemble_document(Path("book.pdf"), "pdf", [Page(number=1)], blocks)


def test_confidence_is_the_length_weighted_share_of_the_winning_language() -> None:
    document = assemble(
        [block("u" * 900, "uz"), block("r" * 100, "ru", "cyrillic"), block("12", "unknown", "none")]
    )
    assert (document.language.language, document.language.script) == ("uz", "latin")
    assert round(document.language.confidence, 2) == 0.9


def test_unknown_fragments_do_not_lower_the_confidence() -> None:
    blocks = [block("u" * 500, "uz")] + [block("x", "unknown", "none") for _ in range(200)]
    assert assemble(blocks).language.confidence == 1.0


def test_footnotes_and_roles_do_not_vote() -> None:
    footnote = Block(
        type=BlockType.FOOTNOTE,
        text="Банковское дело " * 40,
        page=1,
        language=LanguageInfo("ru", "cyrillic", 1.0),
    )
    toc = block("m" * 400, "ru", "cyrillic", role="toc")
    document = assemble([block("u" * 100, "uz"), footnote, toc])
    assert (document.language.language, document.language.confidence) == ("uz", 1.0)


def test_text_without_any_known_block_falls_back_to_whole_text_detection() -> None:
    document = assemble(
        [block("Circular imports and meaning reasoning about modules", "unknown", "latin")]
    )
    assert document.language.language == "unknown"
