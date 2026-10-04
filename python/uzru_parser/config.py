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
#: A line reaching the right edge and spanning this share of the text width is running text,
#: never a figure label.
FULL_LINE_SHARE = 0.5
#: Share of one-line PyMuPDF blocks above which blocks are treated as lines, not paragraphs.
LINE_LEVEL_BLOCKS = 0.7
#: Widest gap, in font sizes, between the pieces of one justified line that the PDF stores as
#: separate lines because of its wide word spacing.
SPREAD_LINE_GAP = 8.0
#: Font sizes differing by at most this share are the same size (a bold run may report a
#: slightly different one).
SAME_SIZE_TOLERANCE = 0.05

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
#: A filled rectangle at most this many font sizes tall behind one row of text is line
#: shading, not a drawing.
SHADING_MAX_HEIGHT = 2.0
#: A drawing region whose lines are at least this share of long body lines holds running
#: text (a shaded or framed area), not a figure.
FIGURE_TEXT_SHARE = 0.6

# --- Headings -------------------------------------------------------------------------------

MAX_HEADING_CHARS = 160
#: Numbered chapter/article titles ("12-modda. ...") can be long.
MAX_KEYWORD_HEADING_CHARS = 300
MAX_HEADING_LINES = 3
#: Font size ratio (to the body size) that counts as "bigger".
LARGER_FONT_RATIO = 1.15
#: Share of bold characters for a block to count as bold.
BOLD_SHARE = 0.6
#: A first line this bold or more is bold throughout; below it, a bold run-in term can open
#: a plain paragraph.
RUN_IN_BOLD_SHARE = 0.95
#: Uppercase signal: at least this many letters, nearly all capitals.
MIN_UPPERCASE_LETTERS = 4
UPPERCASE_SHARE = 0.9
#: Headings must be mostly letters: share of letters among visible characters.
MIN_LETTER_SHARE = 0.5
#: Distinct signals (numbering, bigger font, bold, capitals, space above) a heading needs.
MIN_HEADING_SIGNALS = 2
#: DOCX: a paragraph at least this bold, of at most DOCX_SUBHEADING_WORDS words and without a
#: final full stop, followed by plain text, is a subheading.
DOCX_BOLD_HEADING_SHARE = 0.95
DOCX_SUBHEADING_WORDS = 15
#: DOCX: space above a paragraph this many times the body's marks it as set apart.
DOCX_SPACED_RATIO = 1.5
#: An unnumbered heading holds at least one word of this many letters; single letters and
#: short tokens (chart labels such as "B FAM") never make one.
HEADING_MIN_WORD_LETTERS = 4
#: Space above a block, in font sizes beyond the typical line gap, that sets it apart.
HEADING_SPACE_ABOVE = 0.8
MAX_LEVEL = 6
#: Wrapped heading continuation: longest second part and largest gap (in line heights).
MAX_CONTINUATION_CHARS = 100
CONTINUATION_GAP = 1.5
#: A title left open (ending with a comma or a joining word) may go on this many times
#: further down.
OPEN_TITLE_GAP_FACTOR = 2.0
#: Words that cannot end a title, so a heading ending with one goes on in the next line
#: (Uzbek Latin and Cyrillic, Russian, English). Optional: style and spacing work without it.
JOINING_WORDS: tuple[str, ...] = (
    "va",
    "hamda",
    "yoki",
    "bilan",
    "uchun",
    "ва",
    "ҳамда",
    "ёки",
    "билан",
    "учун",
    "и",
    "или",
    "в",
    "во",
    "на",
    "по",
    "для",
    "с",
    "со",
    "о",
    "об",
    "к",
    "от",
    "из",
    "and",
    "or",
    "of",
    "the",
    "for",
    "in",
    "on",
    "to",
    "with",
)
#: Short-title detection inside a block: last title line versus the longest line.
TITLE_LINE_RATIO = 0.75
MAX_TITLE_LINES = 3
#: A bookmark/contents title matches a block when the block holds this share of it.
TITLE_MATCH_SHARE = 0.6
#: "5-modda. Ushbu Qonun ... kuchga kiradi." is an untitled article and its text: the text is
#: split off when it ends like a clause (":" or ";") or with a full stop after more words
#: than a title has. Long titles without a full stop stay titles.
MAX_TITLE_WORDS = 8
#: Leading characters of two numbered titles compared to tell an outline entry from the
#: heading it announces.
OUTLINE_TITLE_CHARS = 40
#: A line with a math operator and fewer real words (4+ letters) than this is a formula.
FORMULA_MAX_WORDS = 2
#: Largest gap, in font sizes, between a caption and the table or figure below it.
CAPTION_GAP = 3.0
#: A fragment this short without a 3-letter word is formula or chart debris ("=", "p&").
DEBRIS_CHARS = 5
#: Largest gap, in font sizes, between a sentence and an inline formula on its row.
INLINE_FORMULA_GAP = 3.0
MAX_KEYWORD_MARKER_WORDS = 3
#: A short line in capitals ending with ".", ":" or ";" right after a paragraph that stops
#: mid-sentence is that sentence's end, not a heading.
MAX_SENTENCE_TAIL_WORDS = 6
#: A paragraph of at most this many words, starting with a small letter after text that
#: stops mid-sentence, is a broken-off fragment of that sentence ("tengdir.").
ORPHAN_WORDS = 2
#: Text inside a quotation (an amended law quoting new articles) holds no headings of the
#: document; a quotation still open after this many blocks is treated as a stray mark.
MAX_QUOTED_BLOCKS = 300

# --- Columns and reading order --------------------------------------------------------------

#: A gutter between columns is at least this many font sizes wide; a column has at least
#: MIN_COLUMN_LINES lines, MIN_COLUMN_WIDTH font sizes of width, and this share of its lines
#: reach within COLUMN_RAGGED_SHARE of its width from its right edge (running text, not a
#: list of labels or a form).
COLUMN_GUTTER = 1.0
MIN_COLUMN_LINES = 3
MIN_COLUMN_WIDTH = 10.0
COLUMN_RAGGED_SHARE = 0.15
COLUMN_FULL_LINE_SHARE = 0.5
#: Lines wider than this share of the page's text width (titles above columns) are left out
#: when looking for gutters.
SPANNING_SHARE = 0.6
#: A filled box beside the main text with at least this many lines is read after the page.
SIDE_BOX_MIN_LINES = 2
#: When no gutter runs through a whole region, it is cut into horizontal bands at blank gaps
#: of at least this many font sizes (and at full-width lines) and each band is cut on its own.
XY_BAND_GAP = 1.5

# --- Style profile (PDF) ----------------------------------------------------------------------

#: A style at least this share of the body size counts as body size (bold, italic or capitals
#: then make it prominent); smaller styles are never heading styles.
PROFILE_SAME_SIZE = 0.95
#: A heading style holds at most this share of the document's characters (codes and
#: textbooks with a title on every article hold about 10%; body styles fail the short test)...
PROFILE_HEADING_MAX_SHARE = 0.2
#: ...is used for short headings (up to MAX_KEYWORD_HEADING_CHARS characters on at most
#: PROFILE_HEADING_MAX_LINES lines: titles wrap more in narrow columns) at least this share
#: of the time...
PROFILE_HEADING_SHORT_SHARE = 0.8
PROFILE_HEADING_MAX_LINES = 6
#: ...and is followed by body text, or by a heading of another style, at least this share of
#: the time (chart labels and other short styled fragments follow their own style instead).
PROFILE_HEADING_BEFORE_BODY = 0.5
#: Heading styles used fewer times than this in all (a lone document title) are ignored, so
#: the heading rules without a style profile apply.
PROFILE_MIN_HEADINGS = 3
#: A title split into several blocks has at least this many words on its first line
#: (stacked single words are chart or diagram labels).
MIN_WRAPPED_TITLE_WORDS = 2
#: A paragraph at least this long that ends a page with a word or a comma goes on onto the
#: next page even when that page starts with a capital (a name: "Oʻzbekiston Respublikasi").
MIN_UNFINISHED_CHARS = 60
#: A style only emphasised (bold, italic, capitals at body size) needs this many blocks to be
#: a heading style; a bigger style can be one with a single use (a short document's title).
PROFILE_MIN_EMPHASIS_BLOCKS = 2
#: A style smaller than the body with this share of its blocks in the footnote zone is the
#: footnote style.
PROFILE_FOOTNOTE_BOTTOM = 0.6

# --- Tagged PDFs ------------------------------------------------------------------------------

#: The structure tree is trusted only when its elements hold at least this share of the text:
#: page headers, footers and page numbers are artifacts outside the tree and rarely reach a
#: tenth of a page, so much less tagged text means the tags miss content.
TAGGED_MIN_COVERAGE = 0.8
#: An element with more lines than this is not a paragraph; when such elements hold more than
#: TAGGED_MAX_LONG_SHARE of the tagged text, the tags wrap whole pages and are not used.
TAGGED_LONG_UNIT_LINES = 40
TAGGED_MAX_LONG_SHARE = 0.5
#: Elements read in structure order may go back up the same column (a side box, a note);
#: when more than this share of neighbouring elements does, the tag order is not reading order.
TAGGED_MAX_BACKWARD_SHARE = 0.2
#: Speed guard (PyMuPDF issue 5125): MuPDF looks up every marked-content id of a page in the
#: parent tree, and searches the whole list when an id is not at its own position. Pages with
#: more ids than TAGGED_CHECK_PAGE_MCIDS have TAGGED_MCID_SAMPLE ids checked; pages with more
#: than TAGGED_MAX_PAGE_MCIDS, or failing the check, make the parser drop the tree.
TAGGED_CHECK_PAGE_MCIDS = 200
TAGGED_MCID_SAMPLE = 20
TAGGED_MAX_PAGE_MCIDS = 3000
#: Deepest parent-tree level followed (a sane tree has two or three).
TAGGED_MAX_TREE_DEPTH = 16
#: A text block in the margin band caught inside a tagged element is page furniture when a
#: gap of this many of its line heights separates it from the element's other lines.
TAGGED_MARGIN_GAP = 1.5

# --- Page confidence (PDF) --------------------------------------------------------------------

#: A check costing at least this much confidence is listed among the page's issues.
CONFIDENCE_ISSUE = 0.3
#: Share of a page's lines standing beside another line across a gutter within one reading
#: region (columns read as one) that costs all confidence.
CONFIDENCE_SIDE_SHARE = 0.3
#: Tables scoring at least this (see ``tables.table_score``) cost nothing.
CONFIDENCE_TABLE_SCORE = 0.6
#: Prominent short blocks outside the heading styles that cost all confidence.
CONFIDENCE_HEADING_CONFLICTS = 3
#: Lines of at most this many characters are very short; above CONFIDENCE_SHORT_SHARE of the
#: page they cost confidence (chart labels, formula pieces).
CONFIDENCE_SHORT_LINE_CHARS = 5
CONFIDENCE_SHORT_SHARE = 0.4
#: With at least CONFIDENCE_MIN_WORDS words of 4+ letters, a share of words unknown to the
#: Uzbek and Russian lexicons above CONFIDENCE_UNKNOWN_SHARE costs confidence (good text
#: stays well below it; a broken encoding knows none).
CONFIDENCE_MIN_WORDS = 20
CONFIDENCE_UNKNOWN_SHARE = 0.5
#: Words looked up per page (an even sample of longer pages).
CONFIDENCE_SAMPLE_WORDS = 60
#: Pages below this confidence are where the optional layout model may correct the rules.
LOW_PAGE_CONFIDENCE = 0.6

# --- Optional layout model (PDF) ---------------------------------------------------------------

#: Model regions below this score are ignored.
LAYOUT_MIN_SCORE = 0.5
#: Header and footer regions count only in this top and bottom share of the page.
LAYOUT_FURNITURE_BAND = 0.15
#: A line just outside the model's text regions joins the nearest one within this many of
#: its own heights.
LAYOUT_NEAREST_LINES = 3.0
#: A block in a formula region with at most this many words of 4+ letters is a formula.
LAYOUT_FORMULA_WORDS = 3

# --- Scanned pages ----------------------------------------------------------------------------

#: A page needs OCR when it has images and less text than this...
MIN_TEXT_CHARS = 25
#: ...or when images cover this share of it and its text is a stamp or a page number.
SCAN_IMAGE_COVER = 0.5
SCAN_MAX_TEXT_CHARS = 200

# --- Page furniture, footnotes, title page, contents ----------------------------------------

#: Top and bottom page band (share of height) for running headers and footers.
MARGIN_BAND = 0.1
#: Share of pages a margin text must repeat on to be page furniture.
MIN_REPEAT_SHARE = 0.5
#: Books print other running headers on even and odd pages: a margin text on this share of
#: the even (or the odd) pages is furniture too.
PARITY_REPEAT_SHARE = 0.4
#: A running chapter header changes with the chapter: a margin text on at least this many
#: consecutive pages, at the same height (within FURNITURE_Y_TOLERANCE of the page height)
#: and in the same size (within SAME_SIZE_TOLERANCE), is furniture.
FURNITURE_RUN_PAGES = 3
FURNITURE_Y_TOLERANCE = 0.01
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
#: The line above a contents run with at most this many words is its title.
TOC_TITLE_WORDS = 3
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
#: Only pages with this many horizontal and this many vertical table rules are searched for
#: ruled tables (find_tables is slow): stroked paths, or filled bars at most RULE_THICKNESS
#: points thick. Wider filled boxes are backgrounds (browsers draw one behind each
#: highlighted line) and would frame fake cells.
MIN_RULING_PATHS = 2
RULE_THICKNESS = 2.0
#: Tolerance, as a share of the table's height, when matching its ruling lines to its edges.
TABLE_RULE_SLACK = 0.01
#: Tables without ruling lines are looked for where at least this many consecutive rows split
#: into cells at the same places, cells at least TABLE_CELL_GAP font sizes apart.
TEXT_TABLE_MIN_ROWS = 3
TABLE_CELL_GAP = 2.0
#: Table scores (see ``pdf.table_score``, at most 1): a ruled table scoring below
#: TABLE_WEAK_SCORE gets a second reading by text alignment, which replaces it only when it
#: scores TABLE_SCORE_MARGIN higher; a table found by alignment alone needs
#: TEXT_TABLE_MIN_SCORE.
TABLE_WEAK_SCORE = 0.3
TABLE_SCORE_MARGIN = 0.1
TEXT_TABLE_MIN_SCORE = 0.5

# --- Language and chunks --------------------------------------------------------------------

#: Blocks take their neighbours' language when unsure: blocks with fewer words than
#: SHORT_BLOCK_WORDS without a language or below SHORT_LANGUAGE_CONFIDENCE, and any block below
#: LOW_LANGUAGE_CONFIDENCE (detector confidence runs from 0.5, undecided, to 1).
SHORT_BLOCK_WORDS = 5
SHORT_LANGUAGE_CONFIDENCE = 0.9
LOW_LANGUAGE_CONFIDENCE = 0.7
#: Blocks of at most this many words below TINY_LANGUAGE_CONFIDENCE follow their neighbours'
#: language when both neighbours agree: loanwords shared by Uzbek and Russian ("Лизинг",
#: "Эквайринг") score up to about 0.97, words of one language alone higher.
TINY_BLOCK_WORDS = 2
TINY_LANGUAGE_CONFIDENCE = 0.98
#: Chunks below this many tokens are merged into a neighbour under the same heading.
MIN_CHUNK_TOKENS = 50
#: A short paragraph ending with ":" (and a short title line before it) introduces what
#: follows and moves with it to the next chunk.
LEAD_IN_TOKENS = 60
