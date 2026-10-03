"""Every tunable threshold and word list of the parser, in one place.

Most decisions use the document's own statistics (most common font size, typical line gap,
page edges); the numbers below scale those statistics. Values given "in font sizes" are
multiplied by the body font size of the document being parsed.
"""

from __future__ import annotations

# --- Word lists (Uzbek Latin, Uzbek Cyrillic, Russian, English) ---------------------------

#: Chapter/section words with their rank (1 = largest unit). A word only counts together
#: with a number ("3-MAVZU", "II-BOB", "Глава 5"), and still needs heading layout.
#: Apostrophes are ignored when matching ("boʻlim" == "bolim").
HEADING_KEYWORDS: tuple[tuple[str, int], ...] = (
    ("qism", 1),
    ("boʻlim", 1),
    ("mavzu", 1),
    ("ilova", 1),
    ("bob", 2),
    ("modda", 4),
    ("қисм", 1),
    ("бўлим", 1),
    ("мавзу", 1),
    ("илова", 1),
    ("боб", 2),
    ("модда", 4),
    ("часть", 1),
    ("раздел", 1),
    ("тема", 1),
    ("приложение", 1),
    ("глава", 2),
    ("параграф", 3),
    ("статья", 4),
    ("part", 1),
    ("chapter", 2),
)

#: Titles of a table of contents.
TOC_TITLES: tuple[str, ...] = (
    "mundarija",
    "mundarijasi",
    "tarkib",
    "мундарижа",
    "оглавление",
    "содержание",
    "contents",
    "table of contents",
)

#: Words that introduce a topic plan ("Reja:" followed by numbered items).
PLAN_WORDS: tuple[str, ...] = ("reja", "режа", "план")

# --- Paragraph rebuilding (PDF) -------------------------------------------------------------

#: Extra vertical gap, in font sizes, allowed above the document's typical line gap before
#: two lines are treated as separate paragraphs.
PARAGRAPH_GAP_SLACK = 0.5
#: Left-edge difference, in font sizes, still treated as the same column.
PARAGRAPH_ALIGN_TOLERANCE = 0.6
#: Largest first-line indent, in font sizes.
PARAGRAPH_MAX_INDENT = 4.0
#: A line ending this many font sizes before the right edge is "short": it can end a paragraph.
PARAGRAPH_SHORT_LINE = 4.0
#: Share of one-line PyMuPDF blocks above which blocks are treated as lines, not paragraphs.
LINE_LEVEL_BLOCKS = 0.7

# --- Figures --------------------------------------------------------------------------------

#: A text fragment this short (words / characters) inside a drawing can be a figure label.
FIGURE_LABEL_WORDS = 6
FIGURE_LABEL_CHARS = 60
#: Drawings closer than this many font sizes belong to the same figure.
FIGURE_MERGE_GAP = 2.0
#: Labels may sit this many font sizes outside a drawing (axis labels, legends).
FIGURE_LABEL_MARGIN = 1.5
#: Labels needed to call a region (or a run of short lines without drawings) a figure.
FIGURE_MIN_LABELS = 2
FIGURE_MIN_LABELS_WITHOUT_DRAWING = 4
#: Labels of a figure without drawings have at most this many words.
FIGURE_FREE_LABEL_WORDS = 3

# --- Headings -------------------------------------------------------------------------------

MAX_HEADING_CHARS = 160
#: Numbered chapter/article titles ("12-modda. ...") can be long.
MAX_KEYWORD_HEADING_CHARS = 300
MAX_HEADING_LINES = 3
#: Font size ratio (to the body size) that counts as "bigger".
LARGER_FONT_RATIO = 1.15
#: Share of bold characters for a block to count as bold.
BOLD_SHARE = 0.6
#: Uppercase signal: at least this many letters, nearly all capitals.
MIN_UPPERCASE_LETTERS = 4
UPPERCASE_SHARE = 0.9
#: Headings must be mostly letters: share of letters among visible characters.
MIN_LETTER_SHARE = 0.5
#: Distinct signals (numbering, bigger font, bold, capitals, space above) a heading needs.
MIN_HEADING_SIGNALS = 2
#: Space above a block, in font sizes beyond the typical line gap, that sets it apart.
HEADING_SPACE_ABOVE = 0.8
MAX_LEVEL = 6
#: Wrapped heading continuation: longest second part and largest gap (in line heights).
MAX_CONTINUATION_CHARS = 100
CONTINUATION_GAP = 1.5
#: Short-title detection inside a block: last title line versus the longest line.
TITLE_LINE_RATIO = 0.75
MAX_TITLE_LINES = 3
#: A bookmark/contents title matches a block when the block holds this share of it.
TITLE_MATCH_SHARE = 0.6

# --- Page furniture, footnotes, title page, contents ----------------------------------------

#: Top and bottom page band (share of height) for running headers and footers.
MARGIN_BAND = 0.1
#: Share of pages a margin text must repeat on to be page furniture.
MIN_REPEAT_SHARE = 0.5
#: Footnotes start below this share of the page height, in a font this much smaller.
FOOTNOTE_ZONE = 0.75
FOOTNOTE_SIZE_RATIO = 0.92
TITLE_PAGE_MAX_WORDS = 80
TITLE_PAGE_MIN_BLOCKS = 3
TITLE_PAGE_MIN_PAGES = 3
#: Contents: share of a page's lines (or of its blocks, when long titles wrap over several
#: lines) that must look like entries, and minimum entries.
TOC_LINE_SHARE = 0.4
TOC_BLOCK_SHARE = 0.5
TOC_MIN_ENTRIES = 3
#: Share of page-number pairs that must not decrease on a contents page.
TOC_ASCENDING_SHARE = 0.8
#: Untitled contents are only looked for in this share of pages at each end of the book.
TOC_EDGE_SHARE = 0.2
#: A contents starting after this share of the pages makes what follows back matter.
BACK_MATTER_START = 0.85

# --- Tables ---------------------------------------------------------------------------------

MIN_TABLE_ROWS = 2
MIN_TABLE_COLUMNS = 2
#: Share of rows with two or more filled cells for a ruled grid to be a table.
MIN_MULTI_CELL_ROWS = 0.3
#: Share of rows continuing a sentence from the row above that marks running text.
RUNNING_TEXT_ROWS = 0.5
#: Rows at the top that can be one header split over several lines.
HEADER_ROWS = 3
#: Only pages with this many vector paths are searched for tables (find_tables is slow).
MIN_RULING_PATHS = 4

# --- Language and chunks --------------------------------------------------------------------

#: Blocks with fewer words take the language of their neighbours when their own is unknown.
SHORT_BLOCK_WORDS = 5
#: Chunks below this many tokens are merged into a neighbour under the same heading.
MIN_CHUNK_TOKENS = 50
