"""Build small tagged PDFs (structure tree + marked content) for tests.

A document is a tree of :class:`Tag` elements whose leaves are :class:`Text` pieces placed on
pages. Every text piece is drawn as its own marked-content sequence with an MCID; the structure
tree points at those MCIDs, the way word processors write accessible PDFs. ``Artifact`` and
``Untagged`` pieces are drawn but stay outside the tree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pymupdf
from helpers import bold_font, cyrillic_font


@dataclass
class Text:
    text: str
    page: int = 0
    y: float = 100.0
    x: float = 72.0
    size: float = 11.0
    bold: bool = False


@dataclass
class Artifact(Text):
    """Page furniture marked as an artifact: drawn, never in the structure tree."""


@dataclass
class Untagged(Text):
    """Text drawn without any marked content."""


@dataclass
class Tag:
    name: str
    children: list[Tag | Text] = field(default_factory=list)
    attributes: str = ""  # extra dictionary entries, e.g. "/A <</O /Table /ColSpan 2>>"


def _leaves(node: Tag) -> list[Text]:
    out: list[Text] = []
    for child in node.children:
        out.extend(_leaves(child) if isinstance(child, Tag) else [child])
    return out


def write_tagged_pdf(
    path: Path,
    root: list[Tag],
    extra: list[Text] = (),  # type: ignore[assignment]
    draw_order: list[Text] | None = None,
    role_map: dict[str, str] | None = None,
    marked: bool = True,
    pages: int | None = None,
) -> Path:
    """Write ``root`` (children of the Document element) and the ``extra`` artifacts or
    untagged pieces. Pieces are drawn in ``draw_order`` (default: tree order, then extra)."""
    document = Tag("Document", list(root))
    leaves = _leaves(document)
    order = draw_order or [*leaves, *extra]
    page_count = pages or 1 + max(piece.page for piece in order)

    pdf = pymupdf.open()
    for _ in range(page_count):
        page = pdf.new_page()
        page.insert_font(fontname="F0", fontfile=cyrillic_font())
        page.insert_font(fontname="F1", fontfile=bold_font())

    mcid: dict[int, int] = {}  # id(piece) -> MCID on its page
    next_mcid: dict[int, int] = {}
    for piece in order:
        page = pdf[piece.page]
        page.insert_text(
            (piece.x, piece.y),
            piece.text,
            fontname="F1" if piece.bold else "F0",
            fontsize=piece.size,
        )
        xref = page.get_contents()[-1]
        data = pdf.xref_stream(xref)
        if isinstance(piece, Artifact):
            data = b"/Artifact <</Type /Pagination>> BDC\n" + data + b"\nEMC\n"
        elif not isinstance(piece, Untagged):
            number = next_mcid.get(piece.page, 0)
            next_mcid[piece.page] = number + 1
            mcid[id(piece)] = number
            data = b"/Span <</MCID %d>> BDC\n" % number + data + b"\nEMC\n"
        pdf.update_stream(xref, data)

    tree_root = pdf.get_new_xref()
    xrefs: dict[int, int] = {}  # id(Tag) -> xref
    parents: dict[tuple[int, int], int] = {}  # (page, MCID) -> xref of the owning element

    def allocate(node: Tag) -> None:
        xrefs[id(node)] = pdf.get_new_xref()
        for child in node.children:
            if isinstance(child, Tag):
                allocate(child)

    def write(node: Tag, parent: int) -> None:
        xref = xrefs[id(node)]
        kids: list[str] = []
        first_page: int | None = None
        for child in node.children:
            if isinstance(child, Tag):
                kids.append(f"{xrefs[id(child)]} 0 R")
                write(child, xref)
                continue
            if first_page is None:
                first_page = child.page
            number = mcid[id(child)]
            parents[(child.page, number)] = xref
            if child.page == first_page:
                kids.append(str(number))
            else:
                page_xref = pdf[child.page].xref
                kids.append(f"<</Type /MCR /Pg {page_xref} 0 R /MCID {number}>>")
        page_entry = f"/Pg {pdf[first_page].xref} 0 R " if first_page is not None else ""
        pdf.update_object(
            xref,
            f"<</Type /StructElem /S /{node.name} /P {parent} 0 R {page_entry}"
            f"/K [{' '.join(kids)}] {node.attributes}>>",
        )

    allocate(document)
    write(document, tree_root)

    nums: list[str] = []
    for number in range(page_count):
        count = next_mcid.get(number, 0)
        if not count:
            continue
        pdf.xref_set_key(pdf[number].xref, "StructParents", str(number))
        owners = [f"{parents[(number, m)]} 0 R" for m in range(count)]
        nums.append(f"{number} [{' '.join(owners)}]")
    parent_tree = pdf.get_new_xref()
    pdf.update_object(parent_tree, f"<</Nums [{' '.join(nums)}]>>")
    roles = ""
    if role_map:
        roles = "/RoleMap <<" + " ".join(f"/{k} /{v}" for k, v in role_map.items()) + ">>"
    pdf.update_object(
        tree_root,
        f"<</Type /StructTreeRoot /K {xrefs[id(document)]} 0 R /ParentTree {parent_tree} 0 R "
        f"/ParentTreeNextKey {page_count} {roles}>>",
    )
    catalog = pdf.pdf_catalog()
    pdf.xref_set_key(catalog, "StructTreeRoot", f"{tree_root} 0 R")
    if marked:
        pdf.xref_set_key(catalog, "MarkInfo", "<</Marked true>>")
    pdf.save(path)
    pdf.close()
    return path
