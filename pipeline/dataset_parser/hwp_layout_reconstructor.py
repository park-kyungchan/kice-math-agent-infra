"""
hwp_layout_reconstructor.py

Reconstructs 2D math layout (fractions, radicals, integral/sigma limits,
superscript/subscript, extensible delimiters) from per-character PDF
coordinates into linear LaTeX, for KICE/CSAT math PDFs typeset in HWP.

Background: PyMuPDF's page.get_text("blocks") (used by the previous
pdf_segmenter.py) discards per-character coordinates, orphaning fraction
numerators/denominators, integral/sigma limits, radical extents and
multiline delimiters onto their own lines. PyMuPDF is also not installable
in this sandbox. This module uses pdfminer.six, which exposes per-character
bounding boxes, to recover the 2D structure and re-linearize it.

The HWP equation font (HyhwpEQ) maps its glyphs into the Unicode Private
Use Area; hwp_pua_map.json (verified, 80 entries, 0 residual PUA) is
applied here at the character-decode stage, before any geometric
reasoning, so every downstream character is a real Unicode character.

RECURSIVE RESOLUTION (v2). Every construct resolver (fraction/radical bar,
big-operator limits, extensible delimiters) collects a LOCAL candidate
glyph subset for its body (numerator, denominator, radicand, limit,
delimiter body). That subset is now resolved through the FULL resolver
pipeline recursively (reduce_item_pool, scoped to just that subset) BEFORE
being flattened to text -- so a subscript/superscript or nested construct
living inside a fraction/sum/radical body is itself resolved, not baked in
as bare adjacent characters. This replaces the v1 design, which linearized
raw glyph .text values directly and only ran generic subscript/superscript
resolution once, at the very end, on the top-level pool -- silently
destroying any sub/superscript that had already been swept into a
construct body (v1's dominant, corpus-wide defect).

CONFIDENCE DERIVATION (v2, documented per-signal so 1.0 is a real claim,
not a default). An item's confidence is the MINIMUM over all of the
following mechanically-derived signals (round to 3 decimals); 1.0 means
none of these signals fired:
  1. Per-construct-token confidence, set at the point of resolution:
     - fraction: 1.0 if both numerator and denominator are non-empty,
       else 0.45 (an unpaired bar means one side genuinely had nothing
       there -- almost always a resolution failure, not a real 0-content
       math construct).
     - radical: 1.0 if the radicand is non-empty, else 0.5.
     - overline / vector (\\overline / \\vec): 1.0 if the base text is
       non-empty, else 0.4.
     - big operator (\\int / \\sum): 1.0 normally; capped at 0.6 if this
       operator sat close enough to ANOTHER big operator on the same row
       that their raw (unbounded) limit-search windows would have
       overlapped -- i.e. a mechanically detected limit-assignment
       ambiguity (see resolve_bigops_once's window bounding), even though
       the bounding logic now assigns each operator's limits correctly.
     - multiline brace / bracket: 0.75 (brace) / 0.55 (bracket) if the
       body is non-empty, else 0.4 (brace) / 0.35 (bracket) -- an empty
       required body is exactly the "content-free \\left\\{ \\right."
       defect the v1 pass criterion could not see.
  2. Any of the above bodies (numerator/denominator/radicand/limit/
     delimiter body) that, AFTER full local recursive resolution, still
     contains an unconsumed small (sub/superscript-sized) equation-font
     glyph caps that token's confidence at 0.5 -- a direct, mechanical
     "this body still has an unresolved subscript/superscript in it"
     signal, independent of whether the body is non-empty.
  3. Item-level, computed once over the final zone after ALL resolution:
     - any leftover small (sub/superscript-sized) equation-font glyph
       anywhere in the item's final text (never attached to anything,
       never consumed into any construct) caps item confidence at 0.5.
     - residual_pua > 0 (an unmapped PUA codepoint) forces confidence to
       0.0 (unchanged from v1 -- a real decode failure).
A 1.0 therefore means: every construct token in the item resolved with a
non-empty required body, no operator sat in a contested multi-operator
row, and no small equation-font glyph was left unattached anywhere in the
item. It is not a claim that the LaTeX is a byte-perfect transcription --
only that none of the specific, mechanically-checkable defect classes
found by the independent verifier are present.

Public entry point (drop-in replacement matching the previous
pdf_segmenter.extract_pdf_questions contract):

    extract_pdf_questions(pdf_path: str) -> list[dict]
        each dict: {page, column, item_number, rect, header_text, text,
                    confidence, constructs, residual_pua}

`rect` is emitted in PyMuPDF-style top-down page coordinates (origin
top-left, y increasing downward) for compatibility with image_cropper.py,
even though this module itself works internally in pdfminer's bottom-up
coordinate system (origin bottom-left, y increasing upward).
"""

import json
import os
import re
from collections import Counter

from pdfminer.high_level import extract_pages
from pdfminer.layout import LTChar

# ---------------------------------------------------------------------------
# PUA map loading
# ---------------------------------------------------------------------------

_THIS_DIR = os.path.abspath(os.path.dirname(__file__))
_PUA_MAP_PATH = os.path.join(_THIS_DIR, "hwp_pua_map.json")

_BAR_CHAR = "―"          # ― (U+2015 HORIZONTAL BAR) -- decoded value of U+E06D
_RADICAL_CHAR = "√"      # √
_INTEGRAL_CHAR = "∫"     # ∫
_SIGMA_CHAR = "Σ"        # Σ
_ARROW_CHAR = "→"        # → -- vector-notation arrowhead riding a vinculum
_BRACE_CHARS = {"⎧", "⎨", "⎩", "⎪"}   # ⎧ ⎨ ⎩ ⎪
_BRACKET_LEFT_CHARS = {"⎡", "⎣"}                # ⎡ ⎣
_BRACKET_RIGHT_CHARS = {"⎤", "⎦"}               # ⎤ ⎦
_BRACKET_CHARS = _BRACKET_LEFT_CHARS | _BRACKET_RIGHT_CHARS

HEADER_RE = re.compile(r'^\s*(\d{1,2})\.\s*')
GROUP_RE = re.compile(r'^\s*\[(\d{1,2})~(\d{1,2})\]')

# Any not-yet-resolved glyph carrying one of these special roles must
# never be silently swept up as plain "content" by ANOTHER construct's
# region scan (e.g. a wide outer fraction bar's x-range legitimately
# overlaps a narrower nested radical's x-range when the radical is that
# fraction's numerator -- \frac{\sqrt{3}}{2}). Such glyphs are excluded
# from numerator/denominator/radicand/limit/body candidate searches and
# only ever consumed through their own dedicated resolution path.
#
# NOTE: _ARROW_CHAR ("→") is deliberately NOT in this set. Unlike the
# others, it is not purely structural -- it is legitimate ordinary
# content in its own right (e.g. "lim_{x→1}"), and must flow through the
# normal candidate/resolve_subsup pipeline in that role. It is ONLY
# special-cased, via a narrow, geometry-gated search local to
# resolve_bars_once's overline/vector branch, when it rides directly on
# a vinculum (a vector-notation arrowhead, e.g. \vec{a}) -- see there.
_SPECIAL_ROLE_CHARS = ({_BAR_CHAR, _RADICAL_CHAR, _INTEGRAL_CHAR, _SIGMA_CHAR}
                        | _BRACE_CHARS | _BRACKET_CHARS)


def _is_unresolved_special(o):
    return o["kind"] == "glyph" and o["text"] in _SPECIAL_ROLE_CHARS


def _load_pua_map(path=_PUA_MAP_PATH):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    out = {}
    for key, entry in data["map"].items():
        cp = int(key.replace("U+", ""), 16)
        out[cp] = entry["char"]
    return out


_PUA_MAP = _load_pua_map()


def _decode_char(ch):
    """Apply the verified PUA map to a single extracted character."""
    if len(ch) != 1:
        return ch
    cp = ord(ch)
    if 0xE000 <= cp <= 0xF8FF:
        return _PUA_MAP.get(cp, ch)
    return ch


def _is_pua(ch):
    return len(ch) == 1 and 0xE000 <= ord(ch) <= 0xF8FF


# ---------------------------------------------------------------------------
# Glyph extraction
# ---------------------------------------------------------------------------

def _walk_chars(obj, out):
    if isinstance(obj, LTChar):
        out.append(obj)
    elif hasattr(obj, "__iter__"):
        for child in obj:
            _walk_chars(child, out)


def _extract_page_glyphs(page):
    """Return a list of glyph dicts for one pdfminer LTPage, decoded."""
    raw = []
    _walk_chars(page, raw)
    glyphs = []
    for c in raw:
        txt = c.get_text()
        if txt == "":
            continue
        decoded = _decode_char(txt)
        glyphs.append({
            "text": decoded,
            "orig": txt,
            "x0": c.x0, "x1": c.x1, "y0": c.y0, "y1": c.y1,
            "size": c.size,
            "fontname": c.fontname or "",
            "is_eq": "HyhwpEQ" in (c.fontname or ""),
            "kind": "glyph",
            "residual_pua": 1 if _is_pua(decoded) else 0,
        })
    return glyphs


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _cx(o):
    return (o["x0"] + o["x1"]) / 2.0


def _cy(o):
    return (o["y0"] + o["y1"]) / 2.0


def _row_y(o):
    return o.get("row_y", o["y0"])


def cluster_rows(objs, tol=4.5):
    """Cluster objects into visual rows by baseline (row_y) proximity.
    Range-based (chaining) membership: a candidate joins a row if its
    row_y is within tol of the row's CURRENT [ymin, ymax] extent (which
    grows as members join), not just of the single first object placed
    into it. A fixed single-anchor comparison was found to reject a
    legitimate same-line construct (e.g. a small inline fraction) purely
    because an unrelated slightly-higher member (e.g. a segment overline)
    happened to be inserted into that row first, even though the
    fraction's own y was within tol of the row's other, closer members."""
    items = sorted(objs, key=lambda o: (-_row_y(o), o["x0"]))
    rows = []
    for o in items:
        placed = False
        for r in rows:
            if r["ymin"] - tol <= _row_y(o) <= r["ymax"] + tol:
                r["objs"].append(o)
                r["ymin"] = min(r["ymin"], _row_y(o))
                r["ymax"] = max(r["ymax"], _row_y(o))
                placed = True
                break
        if not placed:
            rows.append({"ymin": _row_y(o), "ymax": _row_y(o), "objs": [o]})
    for r in rows:
        r["objs"].sort(key=lambda o: o["x0"])
        r["y"] = (r["ymin"] + r["ymax"]) / 2.0
    rows.sort(key=lambda r: -r["y"])
    return rows


def _obj_out_text(o):
    return o["text"] + o.get("sub_suffix", "") + o.get("sup_suffix", "")


def linearize(objs):
    """Left-to-right concatenation of an unordered glyph/token set."""
    return "".join(_obj_out_text(o) for o in sorted(objs, key=lambda o: o["x0"]))


def row_text(row):
    return "".join(_obj_out_text(o) for o in row["objs"])


# ---------------------------------------------------------------------------
# Shared helpers for recursive body resolution + honest confidence
# ---------------------------------------------------------------------------

def _compute_body_size(pool):
    """Dominant (mode) glyph size, used as the sub/superscript threshold
    (anything under 0.85x this is 'small'). Restricted to glyphs > 9pt
    first (equation operators/body text) so a pool dominated by small
    limit/subscript glyphs doesn't drag its own threshold down; falls
    back to all glyph sizes if nothing clears that bar (e.g. a pool
    consisting entirely of small candidates, as some unit tests use)."""
    sizes = [round(o["size"], 1) for o in pool if o["kind"] == "glyph" and o.get("size", 0) > 9]
    if not sizes:
        sizes = [round(o["size"], 1) for o in pool if o["kind"] == "glyph"]
    return Counter(sizes).most_common(1)[0][0] if sizes else 11.0


def _chain_expand(base_objs, pool, blocked_ids, body_size, side=None):
    """Grow a construct-body candidate set (numerator/denominator/
    radicand/...) by chaining in adjacent small (sub/superscript-sized)
    glyphs that sit immediately x-right of something ALREADY in the set,
    even if they fall just outside the construct's own flat vertical-
    reach window. A raised exponent on a fraction's numerator base letter
    (e.g. x^2 as the numerator of x^2/8) can sit far enough above the
    bar that a simple distance-from-bar window misses it by a hair, even
    though it is unambiguously attached to that base letter by x-
    adjacency -- the same signal resolve_subsup itself uses to chain
    compound superscripts. Bounded two ways: only SMALL glyphs chain in
    (a body-sized glyph -- ordinary text -- always stops the chain), and
    if `side` is given as (mid_y, above) the candidate must stay on the
    SAME side of mid_y as the base set. The side check matters: without
    it, a numerator glyph sitting close in x to a DIFFERENT term's
    denominator base letter (e.g. the "+1" of a numerator's "a_{k+1}"
    sitting almost directly above a denominator's unrelated "a") chains
    across the bar's own numerator/denominator divide -- confirmed as a
    real corpus regression (202109_MATH_DIF_07's denominator briefly
    absorbing the numerator's own "+1" as a bogus superscript)."""
    if not base_objs:
        return base_objs
    included_ids = {id(o) for o in base_objs} | set(blocked_ids)
    result = list(base_objs)
    changed = True
    while changed:
        changed = False
        for o in pool:
            if id(o) in included_ids:
                continue
            if o["kind"] != "glyph" or _is_unresolved_special(o):
                continue
            if o.get("size", body_size) >= 0.85 * body_size:
                continue
            if side is not None:
                mid_y, above = side
                if above and not (_cy(o) > mid_y):
                    continue
                if not above and not (_cy(o) <= mid_y):
                    continue
            for h in result:
                gap = o["x0"] - h["x1"]
                if -1.0 <= gap <= 4.0 and abs(_cy(o) - _cy(h)) < 15.0:
                    result.append(o)
                    included_ids.add(id(o))
                    changed = True
                    break
    return result


def _has_unresolved_subsup(resolved_objs, body_size):
    """True iff a small (sub/superscript-sized) equation-font glyph
    survives, unconsumed, in an already fully-locally-resolved body --
    the mechanical 'this body still has a broken subscript in it' check
    used to force confidence down (module docstring, signal 2)."""
    return any(
        o["kind"] == "glyph" and o.get("is_eq") and o.get("size", body_size) < 0.85 * body_size
        for o in resolved_objs
    )


def _resolve_and_check(candidates, body_size):
    """Recursively resolve a construct-body candidate subset through the
    FULL resolver pipeline (reduce_item_pool, scoped to just this subset)
    and report whether it still contains an unresolved sub/superscript."""
    if not candidates:
        return [], False
    resolved, _ = reduce_item_pool(list(candidates), body_size=body_size)
    return resolved, _has_unresolved_subsup(resolved, body_size)


# ---------------------------------------------------------------------------
# Construct resolution (bars -> fraction/radical/overline/vector,
# big-operator limits, extensible delimiters, generic superscript/
# subscript)
# ---------------------------------------------------------------------------

def _merge_bar_spans(bar_glyphs, y_tol=1.5, x_gap=2.2):
    """Merge adjacent same-row '―' glyphs into one bar span (a single wide
    bar can be drawn as several repeated bar glyphs abutting each other).
    Two bugs previously lived here: (1) grouping glyphs into a rounded
    y0/y_tol bucket before comparing could split two bars that are
    genuinely on the same line into different buckets purely from
    straddling a rounding boundary (e.g. y0=1022.07 vs 1022.37), and (2)
    the x-adjacency test `g.x0 - grp[-1].x1 <= x_gap` has no LOWER bound,
    so it is trivially satisfied by any glyph sitting far to the left of
    an existing group's rightmost piece too -- together these merged
    every "―" on an "AB=AC=8√5, BC=16" style line (4 unrelated overlines/
    vinculum, incidentally 0.3pt apart in y0) into one nonsensical span.
    Fixed by sorting directly on raw y0 (no bucketing) and requiring the
    gap to be small AND non-negative (immediately touching, left-to-right)."""
    groups = []
    for g in sorted(bar_glyphs, key=lambda o: (o["y0"], o["x0"])):
        placed = False
        for grp in groups:
            if abs(grp[-1]["y0"] - g["y0"]) <= y_tol and 0 <= g["x0"] - grp[-1]["x1"] <= x_gap:
                grp.append(g)
                placed = True
                break
        if not placed:
            groups.append([g])
    spans = []
    for grp in groups:
        spans.append({
            "pieces": grp,
            "x0": min(p["x0"] for p in grp),
            "x1": max(p["x1"] for p in grp),
            "y0": min(p["y0"] for p in grp),
            "y1": max(p["y1"] for p in grp),
        })
    return spans


def resolve_bars_once(pool, x_tol=1.8, body_size=None):
    bar_glyphs = [o for o in pool if o["kind"] == "glyph" and o["text"] == _BAR_CHAR]
    if not bar_glyphs:
        return pool, False, set()

    if body_size is None:
        body_size = _compute_body_size(pool)

    # local mutable copy: newly-resolved tokens (e.g. an inner \sqrt{})
    # are appended here immediately, in-loop, so a subsequent (wider)
    # span processed within this SAME call can pick them up as its own
    # numerator/denominator -- new_tokens is not held back to the end.
    pool = list(pool)

    spans = _merge_bar_spans(bar_glyphs)
    spans.sort(key=lambda s: s["x1"] - s["x0"])  # narrow (likely nested/inner) first
    for s in spans:
        s["mid_y"] = (s["y0"] + s["y1"]) / 2.0

    consumed_ids = set()
    constructs = set()
    changed = False

    def _nearest_bar_ok(o, this_span, x_tol=1.8):
        """Nearest-bar assignment: exclude a candidate glyph from this
        span's numerator/denominator/radicand if it sits closer (in y) to
        a DIFFERENT, still-PENDING bar's mid_y -- prevents a wide outer
        fraction's own denominator/numerator content from bleeding into a
        narrower nested construct (e.g. \\sqrt{...} used as that
        fraction's own numerator) whose x-range legitimately overlaps the
        outer bar's. Already-resolved spans are excluded from this
        comparison: their bar glyph is gone from the pool, and the
        resulting token (e.g. the \\sqrt{} itself) is legitimately what a
        still-pending outer span's numerator/denominator search is meant
        to pick up next -- it must not keep losing to the span it came
        from. A candidate "other" span only counts as a rival if o also
        falls within ITS x-range -- two unrelated bars that happen to
        share a similar height elsewhere on the same line (e.g. a tiny
        exponent fraction and a same-row but far-off radical) must not
        steal each other's numerator/denominator purely on a y-coincidence."""
        d_this = abs(_cy(o) - this_span["mid_y"])
        for other in spans:
            if other is this_span:
                continue
            other_ids = {id(p) for p in other["pieces"]}
            if other_ids & consumed_ids:
                continue  # already resolved into a token; no longer competes
            if not (other["x0"] - x_tol <= _cx(o) <= other["x1"] + x_tol):
                continue  # not even in the rival span's own x-window
            if abs(_cy(o) - other["mid_y"]) < d_this:
                return False
        return True

    for span in spans:
        span_ids = {id(p) for p in span["pieces"]}
        if span_ids & consumed_ids:
            continue
        mid_y = span["mid_y"]

        # radical? preceding √ glyph immediately to the left, vertically overlapping
        radical_glyph = None
        for o in pool:
            if id(o) in consumed_ids or o is None:
                continue
            if o["kind"] == "glyph" and o["text"] == _RADICAL_CHAR:
                if -1.0 <= span["x0"] - o["x1"] <= 6.0 and o["y1"] >= span["y0"] - 1.0 and o["y0"] <= span["y1"] + 1.0:
                    if radical_glyph is None or o["x1"] > radical_glyph["x1"]:
                        radical_glyph = o

        # Radicand sits close to the vinculum -- same order of magnitude
        # as a fraction's numerator/denominator distance from its bar, not
        # the more generous 2.5x-height reach originally used here, which
        # was found to reach clean into the NEXT physical line down when
        # a radical's x-position coincidentally lined up with content
        # there (e.g. "\sqrt{5위}" absorbing "위" from "...위의 점 P" on
        # the following line).
        max_reach = max(14.0, 1.3 * (span["y1"] - span["y0"]))

        if radical_glyph is not None:
            radicand_raw = [
                o for o in pool
                if id(o) not in consumed_ids and id(o) != id(radical_glyph)
                and id(o) not in span_ids and not _is_unresolved_special(o)
                and span["x0"] - x_tol <= _cx(o) <= span["x1"] + x_tol
                and abs(_cy(o) - mid_y) <= max_reach
                and _nearest_bar_ok(o, span)
            ]
            # radical index (e.g. the small "3" of a cube root ∛), sitting
            # small and raised just above/left of the radical glyph itself
            index_glyph = None
            for o in pool:
                if id(o) in consumed_ids or id(o) == id(radical_glyph) or id(o) in span_ids:
                    continue
                if o is None:
                    continue
                rad_cy = (radical_glyph["y0"] + radical_glyph["y1"]) / 2.0
                if (o["size"] <= 0.7 * radical_glyph["size"]
                        and radical_glyph["x0"] - 8.0 <= o["x0"] <= radical_glyph["x0"] + 8.0
                        and _cy(o) > rad_cy
                        and abs(_cy(o) - rad_cy) <= 15.0):
                    if index_glyph is None or o["x1"] > index_glyph["x1"]:
                        index_glyph = o

            radicand = _chain_expand(radicand_raw, pool,
                                      consumed_ids | span_ids | {id(radical_glyph)}
                                      | ({id(index_glyph)} if index_glyph is not None else set()),
                                      body_size)
            radicand_resolved, rad_defect = _resolve_and_check(radicand, body_size)
            radicand_text = linearize(radicand_resolved)
            if index_glyph is not None:
                sqrt_text = "\\sqrt[%s]{%s}" % (index_glyph["text"], radicand_text)
                extra_ids = {id(index_glyph)}
                x0 = min(radical_glyph["x0"], index_glyph["x0"])
                y0 = min([radical_glyph["y0"], span["y0"], index_glyph["y0"]] + [o["y0"] for o in radicand])
                y1 = max([radical_glyph["y1"], span["y1"], index_glyph["y1"]] + [o["y1"] for o in radicand])
            else:
                sqrt_text = "\\sqrt{%s}" % radicand_text
                extra_ids = set()
                x0 = radical_glyph["x0"]
                y0 = min([radical_glyph["y0"], span["y0"]] + [o["y0"] for o in radicand])
                y1 = max([radical_glyph["y1"], span["y1"]] + [o["y1"] for o in radicand])
            conf = 1.0 if radicand else 0.5
            if rad_defect:
                conf = min(conf, 0.5)
            token = {
                "text": sqrt_text,
                "x0": x0, "x1": span["x1"],
                "y0": y0, "y1": y1,
                "size": radical_glyph["size"],
                "kind": "sqrt",
                "row_y": radical_glyph["y0"],
                "confidence": conf,
            }
            consumed_ids |= span_ids | {id(radical_glyph)} | {id(o) for o in radicand} | extra_ids
            pool.append(token)
            constructs.add("radical")
            changed = True
            continue

        # otherwise: fraction (or, if nothing sits above the bar at all,
        # an \overline{}/\vec{} -- HWP renders segment-name overlines,
        # e.g. \overline{AB}, and vector notation, e.g. \vec{a}, with the
        # same extensible bar glyph; a vector additionally carries a "→"
        # arrowhead glyph riding directly on the vinculum itself, at the
        # SAME height as the bar (not above or below it like real
        # numerator/denominator content), which must be recognized and
        # excluded from the base text rather than swept in as if it were
        # ordinary denominator content (turning "a" into the nonsensical
        # "a→").
        # Numerator/denominator sit close to the bar (typically well
        # under half a line height away); a tighter reach than the
        # radicand's is used here so a plain 1-line fraction's search
        # doesn't sweep in unrelated content one or two lines below.
        frac_reach = max(14.0, 1.3 * (span["y1"] - span["y0"]))
        numerator_raw = [
            o for o in pool
            if id(o) not in consumed_ids and id(o) not in span_ids and not _is_unresolved_special(o)
            and span["x0"] - x_tol <= _cx(o) <= span["x1"] + x_tol
            and _cy(o) > mid_y
            and abs(_cy(o) - mid_y) <= frac_reach
            and _nearest_bar_ok(o, span)
        ]
        denominator_raw = [
            o for o in pool
            if id(o) not in consumed_ids and id(o) not in span_ids and not _is_unresolved_special(o)
            and span["x0"] - x_tol <= _cx(o) <= span["x1"] + x_tol
            and _cy(o) <= mid_y
            and abs(_cy(o) - mid_y) <= frac_reach
            and _nearest_bar_ok(o, span)
        ]
        blocked = consumed_ids | span_ids
        numerator = _chain_expand(numerator_raw, pool, blocked, body_size, side=(mid_y, True))
        denominator = _chain_expand(denominator_raw, pool, blocked, body_size, side=(mid_y, False))

        if not numerator and denominator:
            # overline / vector branch. Look for a "→" arrowhead riding
            # the vinculum itself -- overlapping the BAR's own y-range
            # (not the base letter's, which sits clearly below the bar).
            # "→" is ordinary content everywhere else (e.g. "lim_{x→1}"),
            # so it is NOT filtered out of `denominator` upstream; it is
            # only pulled out narrowly, right here, when its geometry
            # says it is riding the vinculum rather than being real base
            # text -- the same way the radical index glyph is searched
            # for explicitly rather than via a blanket exclusion.
            arrow_glyph = None
            for o in denominator:
                if o["kind"] == "glyph" and o["text"] == _ARROW_CHAR:
                    if not (o["y1"] < span["y0"] - 1.0 or o["y0"] > span["y1"] + 1.0):
                        arrow_glyph = o
                        break
            if arrow_glyph is not None:
                denominator = [o for o in denominator if o is not arrow_glyph]
            denom_resolved, den_defect = _resolve_and_check(denominator, body_size)
            over_text = linearize(denom_resolved)
            macro = "\\vec" if arrow_glyph is not None else "\\overline"
            conf = 1.0 if over_text else 0.4
            if den_defect:
                conf = min(conf, 0.5)
            extra_ids = {id(arrow_glyph)} if arrow_glyph is not None else set()
            token = {
                "text": "%s{%s}" % (macro, over_text),
                "x0": span["x0"], "x1": span["x1"],
                "y0": min([span["y0"]] + [o["y0"] for o in denominator]),
                "y1": max([span["y1"]] + [o["y1"] for o in denominator]),
                "size": max((o["size"] for o in denominator), default=span["y1"] - span["y0"]),
                "kind": "overline",
                # Anchor to the BASE letter's own row (its y0), not the
                # bar's -- the vinculum is drawn a few pt above its base
                # letter's baseline, and using the bar's own y0 as row_y
                # sorted the whole token into its own row a full line
                # above the sentence it is actually inline with (e.g.
                # \overline{a} hoisted above "23. 두 벡터 a=...").
                "row_y": min(o["y0"] for o in denominator),
                "confidence": conf,
            }
            consumed_ids |= span_ids | {id(o) for o in denominator} | extra_ids
            pool.append(token)
            constructs.add("overline")
            changed = True
            continue

        numerator_resolved, num_defect = _resolve_and_check(numerator, body_size)
        denominator_resolved, den_defect = _resolve_and_check(denominator, body_size)
        num_text = linearize(numerator_resolved)
        den_text = linearize(denominator_resolved)
        conf = 1.0 if (numerator and denominator) else 0.45
        if num_defect or den_defect:
            conf = min(conf, 0.5)
        token = {
            "text": "\\frac{%s}{%s}" % (num_text, den_text),
            "x0": span["x0"], "x1": span["x1"],
            "y0": min([span["y0"]] + [o["y0"] for o in numerator + denominator]),
            "y1": max([span["y1"]] + [o["y1"] for o in numerator + denominator]),
            "size": max((o["size"] for o in numerator + denominator), default=span["y1"] - span["y0"]),
            "kind": "frac",
            "row_y": span["y0"],
            "confidence": conf,
        }
        consumed_ids |= span_ids | {id(o) for o in numerator} | {id(o) for o in denominator}
        pool.append(token)
        constructs.add("fraction")
        changed = True

    if not changed:
        return pool, False, set()

    new_pool = [o for o in pool if id(o) not in consumed_ids]
    return new_pool, True, constructs


def resolve_bigops_once(pool, body_size=None):
    op_glyphs = [o for o in pool if o["kind"] == "glyph" and o["text"] in (_INTEGRAL_CHAR, _SIGMA_CHAR)]
    if not op_glyphs:
        return pool, False, set()

    if body_size is None:
        body_size = _compute_body_size(pool)

    def _bounded_window(op):
        """Clip this operator's raw limit-search window at the midpoint
        to any OTHER big operator sharing its row, so one operator can
        never reach into a neighboring operator's own limit glyphs (or
        duplicate them) when two operators sit close together on the same
        line (e.g. "\\sum_{k=1}^{12}a_k + \\sum_{k=1}^{5}a_{2k+1}"). Also
        reports whether clipping actually changed the window (a
        mechanical "this row had contested/ambiguous operator territory"
        signal used to keep confidence honest, module docstring)."""
        opwidth = op["x1"] - op["x0"]
        win_x0 = op["x0"] - 0.6 * opwidth
        win_x1 = op["x1"] + 2.5 * opwidth
        op_cy = _cy(op)
        ambiguous = False
        for other in op_glyphs:
            if other is op:
                continue
            if abs(_cy(other) - op_cy) > max(20.0, 1.5 * (op["y1"] - op["y0"])):
                continue  # not the same row
            if other["x0"] >= op["x0"]:
                mid = (op["x1"] + other["x0"]) / 2.0
                if mid < win_x1:
                    win_x1 = mid
                    ambiguous = True
            else:
                mid = (op["x0"] + other["x1"]) / 2.0
                if mid > win_x0:
                    win_x0 = mid
                    ambiguous = True
        return win_x0, win_x1, ambiguous

    def _bounded_reach(op, max_reach):
        """Cap this operator's vertical limit-search reach at half the
        y-distance to any OTHER same-column big operator, regardless of
        whether they count as "same row" for _bounded_window above.
        Distinct bug from the same-row case: in a multi-branch piecewise
        (e.g. two \\int_0^x branches stacked as separate rows of the SAME
        brace), each branch's own integral is tall (~20pt) and its plain
        max_reach (2.5x operator width, easily 30+pt) can reach clean
        past its own branch boundary into the NEXT branch's integral and
        steal ITS upper limit -- confirmed as a real regression
        (202206_MATH_DIF_14's first \\int_0^x branch absorbing the second
        branch's own "x" upper limit). Gated on rough x-overlap so it
        only fires between operators plausibly stacked in the same
        column/branch, not any two operators anywhere on the page."""
        op_cy = _cy(op)
        capped = max_reach
        ambiguous = False
        for other in op_glyphs:
            if other is op:
                continue
            if abs(other["x0"] - op["x0"]) > 60.0 and abs(other["x1"] - op["x1"]) > 60.0:
                continue
            dy = abs(_cy(other) - op_cy)
            if dy <= 0:
                continue
            half = dy / 2.0
            if half < capped:
                capped = half
                ambiguous = True
        return capped, ambiguous

    anchor_cache = {}

    def _touches_body_anchor(o, this_op):
        """A small candidate glyph that sits immediately (within ~3pt)
        right of a body-sized glyph is a subscript of THAT glyph (e.g.
        the "k" in "a_k" immediately following the summand's "a"), not a
        limit of THIS operator -- \\sum_{k=1}^{5}(2a_k+b_k) was absorbing
        the first "a"'s own "_k" into Sigma's own limits before this
        check existed. Two refinements over the original single-hop
        version: (1) the anchor search is restricted to glyphs at or
        after THIS operator's own right edge (h.x0 >= op.x1) -- content
        printed BEFORE the operator (unrelated preceding text, a
        previous operator's own summand, a trailing space) can never be
        "the summand this op's limit-glyph is a subscript of", and
        treating it as one wrongly excluded the operator's OWN rightful
        limit character purely because some unrelated body-sized glyph
        happened to sit within 3pt to its left; (2) the check chains
        transitively through small glyphs (mirroring resolve_subsup's own
        compound-superscript chaining), so a multi-glyph subscript like
        "2k+1" in a_{2k+1} is recognized as belonging to its anchor "a"
        as a whole, not just its first character."""
        if id(o) in anchor_cache:
            return anchor_cache[id(o)]
        anchor_cache[id(o)] = False  # cycle guard while resolving
        best_h = None
        best_gap = None
        for h in pool:
            if h is o or h is this_op:
                continue
            if h["x0"] < this_op["x1"] - 1.0:
                continue
            gap = o["x0"] - h["x1"]
            if -1.0 <= gap <= 3.0 and abs(_cy(o) - _cy(h)) < 15.0:
                if best_h is None or gap < best_gap:
                    best_h = h
                    best_gap = gap
        result = False
        if best_h is not None:
            if best_h.get("size", body_size) >= 0.85 * body_size:
                result = True
            elif best_h["kind"] == "glyph":
                result = _touches_body_anchor(best_h, this_op)
        anchor_cache[id(o)] = result
        return result

    consumed_ids = set()
    new_tokens = []
    constructs = set()
    changed = False

    for op in op_glyphs:
        if id(op) in consumed_ids:
            continue
        opwidth = op["x1"] - op["x0"]
        op_mid = (op["y0"] + op["y1"]) / 2.0
        win_x0, win_x1, ambiguous = _bounded_window(op)

        max_reach = max(25.0, 2.5 * opwidth)
        max_reach, reach_ambiguous = _bounded_reach(op, max_reach)
        ambiguous = ambiguous or reach_ambiguous
        size_cap = min(0.5 * op["size"], 9.5)
        candidates = [
            o for o in pool
            if id(o) not in consumed_ids and id(o) != id(op) and not _is_unresolved_special(o)
            and win_x0 <= _cx(o) <= win_x1
            and o["size"] <= size_cap
            and o.get("is_eq", True)  # limits are always set in the equation font
            and abs(_cy(o) - op_mid) <= max_reach
            and not _touches_body_anchor(o, op)
        ]
        if not candidates:
            continue

        upper = sorted([o for o in candidates if _cy(o) > op_mid], key=lambda o: o["x0"])
        lower = sorted([o for o in candidates if _cy(o) <= op_mid], key=lambda o: o["x0"])
        if not upper and not lower:
            continue

        # NOTE: unlike numerator/denominator/radicand/delimiter bodies,
        # limit candidates are terminal, small-by-design content ("k",
        # "n", "=", "1" ...) -- they are not expected to themselves be
        # the target of further sub/superscript attachment, so
        # _has_unresolved_subsup's "small glyph left unattached" signal
        # does not apply here (every legitimate limit glyph IS a small,
        # never-further-attached glyph; flagging that as a defect against
        # a correctly-resolved "\sum_{k=1}^{n}" was a false positive).
        # reduce_item_pool is still run, so a genuinely NESTED construct
        # inside a limit (e.g. a compound fraction limit) is still
        # resolved recursively -- only the leftover-small-glyph defect
        # check is skipped for this specific body.
        upper_resolved, _ = reduce_item_pool(list(upper), body_size=body_size) if upper else ([], set())
        lower_resolved, _ = reduce_item_pool(list(lower), body_size=body_size) if lower else ([], set())
        upper_text = linearize(upper_resolved)
        lower_text = linearize(lower_resolved)
        macro = "\\int" if op["text"] == _INTEGRAL_CHAR else "\\sum"
        text = macro
        if lower_text:
            text += "_{%s}" % lower_text
        if upper_text:
            text += "^{%s}" % upper_text

        conf = 1.0
        if ambiguous:
            conf = min(conf, 0.6)

        token = {
            "text": text,
            "x0": op["x0"], "x1": op["x1"],
            "y0": min([op["y0"]] + [o["y0"] for o in upper + lower]),
            "y1": max([op["y1"]] + [o["y1"] for o in upper + lower]),
            "size": op["size"],
            "kind": "bigop",
            "row_y": op["y0"] + 0.25 * (op["y1"] - op["y0"]),
            "confidence": conf,
        }
        consumed_ids |= {id(op)} | {id(o) for o in upper} | {id(o) for o in lower}
        new_tokens.append(token)
        constructs.add("integral" if op["text"] == _INTEGRAL_CHAR else "sigma")
        changed = True

    if not changed:
        return pool, False, set()

    new_pool = [o for o in pool if id(o) not in consumed_ids] + new_tokens
    return new_pool, True, constructs


def _cluster_by_x(glyphs, tol=2.5, y_gap_tol=20.0):
    """Cluster delimiter-piece glyphs into vertical stacks via connected
    components (Union-Find) over pairwise x-proximity + y-overlap-or-gap,
    rather than order-dependent sequential chaining against only the most
    recently appended piece. A tall vertical 'filler' piece bridging a
    multi-line brace's corner/divider pieces can legitimately OVERLAP TWO
    neighboring pieces at once (a 'hub' shape); comparing each new piece
    (processed in strict y0-descending order) only against the previous
    group's LAST member missed this and fragmented one physical brace
    into 2-3 disjoint stacks purely from which piece happened to be
    compared against which -- confirmed against real HWP piecewise-
    function braces, where this produced the corpus's empty/duplicated-
    \\left\\{ \\right. defects. Two pieces belong to the same stack if
    they share x0 (within tol) AND their y-ranges overlap or are within
    y_gap_tol of each other -- checked for every pair and unified
    transitively, independent of processing order."""
    glyphs = list(glyphs)
    n = len(glyphs)
    if n == 0:
        return []
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    for i in range(n):
        for j in range(i + 1, n):
            a, b = glyphs[i], glyphs[j]
            if abs(a["x0"] - b["x0"]) > tol:
                continue
            overlap = min(a["y1"], b["y1"]) - max(a["y0"], b["y0"])
            if overlap >= -y_gap_tol:
                union(i, j)

    buckets = {}
    for i, g in enumerate(glyphs):
        buckets.setdefault(find(i), []).append(g)
    groups = list(buckets.values())
    for grp in groups:
        grp.sort(key=lambda o: -o["y0"])
    return groups


def _rows_to_joined(objs, y_tol=3.5):
    if not objs:
        return ""
    rows = cluster_rows(objs, tol=y_tol)
    return " \\\\ ".join(row_text(r) for r in rows)


def _inline_anchor_row_y(x0, y0, y1, pool, exclude_ids, max_dx=80.0, max_dy=15.0):
    """Find the glyph immediately to the LEFT of a resolved multiline
    delimiter (brace/bracket) that it is most plausibly inline WITH (e.g.
    the "=" introducing a piecewise function's brace, or the sentence
    fragment introducing a bracketed interval), and return that glyph's
    own row_y. A multi-line delimiter's OWN piece geometry spans several
    physical text rows by construction (that is the point of the glyph),
    so anchoring row_y to any one of its own pieces (e.g. the topmost
    corner) can place the whole resolved token a full line away from the
    text it is actually printed inline with -- confirmed against real
    piecewise-function braces and multiline brackets, where anchoring to
    the top corner hoisted the token above the header/introducing text it
    belongs beside. Returns None (caller must fall back) if nothing
    plausible is found within reach."""
    cy_mid = (y0 + y1) / 2.0
    best = None
    best_score = None
    for o in pool:
        if id(o) in exclude_ids or o["kind"] != "glyph":
            continue
        if o["x1"] > x0 + 1.0:
            continue
        dx = x0 - o["x1"]
        if dx > max_dx:
            continue
        dy = abs(_cy(o) - cy_mid)
        if dy > max_dy:
            continue
        score = dx + dy
        if best_score is None or score < best_score:
            best = o
            best_score = score
    if best is None:
        return None
    return best.get("row_y", best["y0"])


def resolve_delimiters_once(pool, body_size=None):
    brace_glyphs = [o for o in pool if o["kind"] == "glyph" and o["text"] in _BRACE_CHARS]
    bracket_glyphs = [o for o in pool if o["kind"] == "glyph" and o["text"] in _BRACKET_CHARS]
    if not brace_glyphs and not bracket_glyphs:
        return pool, False, set()

    if body_size is None:
        body_size = _compute_body_size(pool)

    consumed_ids = set()
    new_tokens = []
    constructs = set()
    changed = False

    # --- braces: \left\{ ... \right. ---
    for stack in _cluster_by_x(brace_glyphs, tol=2.5):
        stack_ids = {id(p) for p in stack}
        x0 = min(p["x0"] for p in stack)
        x1 = max(p["x1"] for p in stack)
        y0 = min(p["y0"] for p in stack)
        y1 = max(p["y1"] for p in stack)
        body = [
            o for o in pool
            if id(o) not in consumed_ids and id(o) not in stack_ids
            and o["x0"] > x1 - 0.5
            and y0 - 2.5 <= _cy(o) <= y1 + 2.5
        ]
        body_resolved, body_defect = _resolve_and_check(body, body_size)
        body_text = _rows_to_joined(body_resolved)
        anchor_row_y = _inline_anchor_row_y(
            x0, y0, y1, pool, consumed_ids | stack_ids | {id(o) for o in body})
        base_conf = 0.75 if body else 0.4
        token = {
            "text": "\\left\\{ %s \\right." % body_text,
            "x0": x0, "x1": x1, "y0": y0, "y1": y1,
            "size": stack[0]["size"],
            "kind": "delim_brace",
            "row_y": anchor_row_y if anchor_row_y is not None else max(p["y0"] for p in stack),
            "confidence": min(base_conf, 0.5) if body_defect else base_conf,
        }
        consumed_ids |= stack_ids | {id(o) for o in body}
        new_tokens.append(token)
        constructs.add("multiline_brace")
        changed = True

    # --- brackets: \left[ ... \right] ---
    # HWP renders a tall bracket from THREE pieces per side sharing the
    # same x-position: a top corner (⎡/⎤), a bottom corner (⎣/⎦), and a
    # vertical filler stroke that bridges the gap between them -- but
    # that filler is drawn with the SAME glyph ('∣', U+E101/E105) used
    # for absolute-value bars elsewhere, and is categorized "symbol" (not
    # "extensible_delimiter_piece") in the PUA map, so it is not swept up
    # by the corner-piece clustering below. It must still be consumed as
    # part of the bracket stack (matched purely by sharing that stack's
    # x-position and sitting inside its corners' y-range), or it survives
    # as a stray literal "∣∣" next to the reconstructed \\left[...\\right].
    left_glyphs = [g for g in bracket_glyphs if g["text"] in _BRACKET_LEFT_CHARS]
    right_glyphs = [g for g in bracket_glyphs if g["text"] in _BRACKET_RIGHT_CHARS]
    left_stacks = _cluster_by_x(left_glyphs, tol=2.5)
    right_stacks = _cluster_by_x(right_glyphs, tol=2.5)
    vbar_glyphs = [o for o in pool if o["kind"] == "glyph" and o["text"] == "∣"]

    def _absorb_vertical_filler(stack):
        sx0 = min(p["x0"] for p in stack)
        sx1 = max(p["x1"] for p in stack)
        sy0 = min(p["y0"] for p in stack)
        sy1 = max(p["y1"] for p in stack)
        return [
            v for v in vbar_glyphs
            if id(v) not in consumed_ids
            and sx0 - 2.5 <= v["x0"] <= sx1 + 2.5
            and v["y0"] >= sy0 - 1.0 and v["y1"] <= sy1 + 1.0
        ]

    used_right = set()
    for lstack in left_stacks:
        lstack = lstack + _absorb_vertical_filler(lstack)
        lx0 = min(p["x0"] for p in lstack)
        lx1 = max(p["x1"] for p in lstack)
        ly0 = min(p["y0"] for p in lstack)
        ly1 = max(p["y1"] for p in lstack)
        best = None
        best_dist = None
        for i, rstack in enumerate(right_stacks):
            if i in used_right:
                continue
            rx0 = min(p["x0"] for p in rstack)
            ry0 = min(p["y0"] for p in rstack)
            ry1 = max(p["y1"] for p in rstack)
            if rx0 <= lx1:
                continue
            overlap = min(ly1, ry1) - max(ly0, ry0)
            if overlap < -3:
                continue
            dist = rx0 - lx1
            if best is None or dist < best_dist:
                best = (i, rstack)
                best_dist = dist
        stack_ids = {id(p) for p in lstack}
        if best is not None:
            i, rstack = best
            rstack = rstack + _absorb_vertical_filler(rstack)
            used_right.add(i)
            stack_ids |= {id(p) for p in rstack}
            rx0 = min(p["x0"] for p in rstack)
            rx1 = max(p["x1"] for p in rstack)
            ry1 = max(p["y1"] for p in rstack)
            y0 = min(ly0, min(p["y0"] for p in rstack))
            y1 = max(ly1, ry1)
            x1 = rx1
            body_lo, body_hi = lx1, rx0
        else:
            rx1 = lx1
            y0, y1 = ly0, ly1
            x1 = lx1
            body_lo, body_hi = lx1, lx1

        body = [
            o for o in pool
            if id(o) not in consumed_ids and id(o) not in stack_ids
            and body_lo - 0.5 <= o["x0"] and o["x1"] <= body_hi + 0.5
            and y0 - 2.5 <= _cy(o) <= y1 + 2.5
        ]
        body_resolved, body_defect = _resolve_and_check(body, body_size)
        body_text = _rows_to_joined(body_resolved)
        anchor_row_y = _inline_anchor_row_y(
            lx0, y0, y1, pool, consumed_ids | stack_ids | {id(o) for o in body})
        base_conf = 0.55 if body else 0.35
        token = {
            "text": "\\left[ %s \\right]" % body_text,
            "x0": lx0, "x1": x1, "y0": y0, "y1": y1,
            "size": lstack[0]["size"],
            "kind": "delim_bracket",
            "row_y": anchor_row_y if anchor_row_y is not None else max(p["y0"] for p in lstack),
            "confidence": min(base_conf, 0.5) if body_defect else base_conf,
        }
        consumed_ids |= stack_ids | {id(o) for o in body}
        new_tokens.append(token)
        constructs.add("multiline_bracket")
        changed = True

    # any leftover, unpaired bracket pieces still get consumed as a literal
    # best-effort bracket so nothing survives literally
    leftover = [g for g in bracket_glyphs if id(g) not in consumed_ids]
    if leftover:
        for g in leftover:
            token = {
                "text": "[" if g["text"] in _BRACKET_LEFT_CHARS else "]",
                "x0": g["x0"], "x1": g["x1"], "y0": g["y0"], "y1": g["y1"],
                "size": g["size"], "kind": "delim_bracket_piece",
                "row_y": g["y0"], "confidence": 0.3,
            }
            consumed_ids.add(id(g))
            new_tokens.append(token)
            constructs.add("multiline_bracket")
            changed = True

    if not changed:
        return pool, False, set()

    new_pool = [o for o in pool if id(o) not in consumed_ids] + new_tokens
    return new_pool, True, constructs


def resolve_subsup(pool, body_size=None):
    """Generic superscript/subscript: attach small, vertically-offset
    glyphs/tokens to the nearest preceding body-sized glyph. Compound
    exponents (e.g. a raised "-5/3", where "5/3" is itself an already-
    resolved \\frac token sitting a few points right of the raised "-"
    sign) are handled by chaining: a small object whose nearest preceding
    neighbor is itself already-attached inherits that neighbor's anchor
    and direction, so multi-piece superscripts merge into one suffix."""
    if body_size is None:
        sizes = [round(o["size"], 1) for o in pool if o["kind"] == "glyph"]
        if not sizes:
            return pool, set()
        body_size = Counter(sizes).most_common(1)[0][0]

    objs = sorted(pool, key=lambda o: o["x0"])
    attach = {}  # id(g) -> (anchor_obj, direction)

    for idx, g in enumerate(objs):
        if g.get("size", body_size) >= 0.85 * body_size:
            continue
        best_h = None
        best_gap = None
        for h in objs[:idx]:
            gap = g["x0"] - h["x1"]
            if -1.0 <= gap <= 4.0 and abs(_cy(g) - _cy(h)) < 15.0:
                if best_h is None or gap < best_gap:
                    best_h = h
                    best_gap = gap
        if best_h is None:
            continue
        if best_h.get("size", body_size) >= 0.85 * body_size:
            offset = _cy(g) - _cy(best_h)
            threshold = max(1.5, 0.20 * best_h["size"])
            if abs(offset) <= threshold:
                continue
            direction = "sup" if offset > 0 else "sub"
            attach[id(g)] = (best_h, direction)
        elif id(best_h) in attach:
            anchor, direction = attach[id(best_h)]
            attach[id(g)] = (anchor, direction)
        else:
            continue

    if not attach:
        return pool, set()

    by_anchor = {}
    for g in objs:
        if id(g) in attach:
            h, direction = attach[id(g)]
            by_anchor.setdefault((id(h), direction), []).append(g)

    consumed_ids = set()
    for (hid, direction), glist in by_anchor.items():
        glist.sort(key=lambda o: o["x0"])
        h = attach[id(glist[0])][0]
        text = linearize(glist)
        suffix_key = "sup_suffix" if direction == "sup" else "sub_suffix"
        h[suffix_key] = h.get(suffix_key, "") + ("^{%s}" % text if direction == "sup" else "_{%s}" % text)
        for g in glist:
            consumed_ids.add(id(g))

    new_pool = [o for o in pool if id(o) not in consumed_ids]
    return new_pool, {"superscript_subscript"}


def _normalize_oversized_row_y(pool):
    """Oversized literal symbols (e.g. the extensible absolute-value bar
    '∣', scaled up to visually span the height of the content it
    brackets) have a raw y0 that can sit well off the visual text
    baseline, stranding them on their own row under plain y0-based row
    clustering. Empirically (calibrated against ∫/Σ, which need the same
    correction to align with their limits' row) a glyph's baseline sits
    ~25% up from the bottom of its bounding box. This is applied to any
    glyph substantially larger than the column's body text size."""
    sizes = [round(o["size"], 1) for o in pool if o["kind"] == "glyph"]
    if not sizes:
        return
    body_size = Counter(sizes).most_common(1)[0][0]
    for o in pool:
        if o["kind"] == "glyph" and o["size"] > 1.6 * body_size:
            o["row_y"] = o["y0"] + 0.25 * (o["y1"] - o["y0"])


def reduce_item_pool(pool, max_iters=8, body_size=None):
    if body_size is None:
        body_size = _compute_body_size(pool)
    constructs_used = set()
    for _ in range(max_iters):
        pool, c1, s1 = resolve_bars_once(pool, body_size=body_size)
        pool, c2, s2 = resolve_bigops_once(pool, body_size=body_size)
        pool, c3, s3 = resolve_delimiters_once(pool, body_size=body_size)
        constructs_used |= s1 | s2 | s3
        if not (c1 or c2 or c3):
            break
    pool, s4 = resolve_subsup(pool, body_size=body_size)
    constructs_used |= s4
    return pool, constructs_used


# ---------------------------------------------------------------------------
# Item segmentation (per column) + top-level extraction
# ---------------------------------------------------------------------------

def _header_rows(pool, tol=4.5):
    """Locate header rows (`^N. ...`) on an (optionally already
    construct-resolved) pool, keyed by row_y so that boundaries line up
    with resolved-token baselines rather than raw, possibly-elevated,
    glyph y0 (which is what caused item-N+1 fraction numerators/limits to
    leak into item N's zone when boundaries were computed pre-resolution)."""
    rows = cluster_rows(pool, tol=tol)
    headers = []
    for r in rows:
        txt = row_text(r)
        m = HEADER_RE.match(txt)
        if m and r["objs"] and not r["objs"][0].get("is_eq", False):
            headers.append({"y": r["y"], "item_number": int(m.group(1)), "text": txt})
    return headers


def _trim_trailing_furniture(rows):
    """Drop a trailing short, digit-only row (a page-footer page number)
    that ended up swept into the last item of a column, whose zone has no
    lower header to bound it. Only trims when there is BOTH a large
    vertical gap (page furniture sits tens of pt away from real content,
    unlike the ~10pt max seen for legitimate elevated sub/superscripts)
    AND short digit-only content, so a genuinely short final content line
    is never dropped."""
    while len(rows) >= 2:
        last, prev = rows[-1], rows[-2]
        gap = prev["y"] - last["y"]
        txt = row_text(last).strip()
        if gap > 35.0 and 0 < len(txt) <= 4 and txt.isdigit():
            rows = rows[:-1]
        else:
            break
    return rows


def _segment_column(glyphs, page_num, col_label, page_height):
    if not glyphs:
        return []

    # Resolve 2D constructs across the WHOLE column first. This collapses
    # elevated numerators/denominators/limits/sub-superscripts into single
    # tokens positioned at their baseline-equivalent row_y, so that item
    # boundary assignment (next step) never has to reason about raw,
    # vertically-offset glyph coordinates. body_size is computed ONCE
    # here, on the raw column glyphs, and threaded through the entire
    # recursive resolution (including every construct body resolved
    # locally inside resolve_bars_once/resolve_bigops_once/
    # resolve_delimiters_once) so every sub/superscript decision in the
    # column -- top-level or nested three constructs deep -- is judged
    # against the SAME dominant body size, not a possibly-skewed local
    # subset.
    glyphs = list(glyphs)
    _normalize_oversized_row_y(glyphs)
    body_size = _compute_body_size(glyphs)
    resolved_pool, _ = reduce_item_pool(glyphs, body_size=body_size)

    headers = _header_rows(resolved_pool)
    headers.sort(key=lambda h: -h["y"])
    items = []
    for i, h in enumerate(headers):
        # Nearest-header assignment: an item's zone extends to the midpoint
        # between its own header row_y and the neighboring headers' row_y.
        # A fixed small headroom above the header is not enough -- radical
        # indices and floating superscript-fractions can sit ~10pt above
        # the header's own baseline while still being part of that item, so
        # a midpoint split (typically tens of pt of slack either way) is
        # used instead of a fixed pad.
        # For the topmost header in a column there is no previous item to
        # split the midpoint against; use a bounded margin instead of
        # unbounded lookback, so page furniture above it (exam title,
        # "제2교시", page number, ...) is excluded while a radical index or
        # raised superscript (~10pt above the header baseline) is kept.
        y_top = (h["y"] + headers[i - 1]["y"]) / 2.0 if i > 0 else h["y"] + 20.0
        y_bottom = (h["y"] + headers[i + 1]["y"]) / 2.0 if i + 1 < len(headers) else -1e9
        zone_objs = [o for o in resolved_pool if y_bottom < _row_y(o) <= y_top]
        if not zone_objs:
            continue
        rows = cluster_rows(zone_objs, tol=4.5)
        rows = _trim_trailing_furniture(rows)
        zone_objs = [o for r in rows for o in r["objs"]]
        text = "\n".join(row_text(r) for r in rows)

        residual_pua = sum(o.get("residual_pua", 0) for o in zone_objs if o["kind"] == "glyph")
        low_conf_tokens = [o for o in zone_objs if o.get("confidence") is not None and o["confidence"] < 0.9]
        confidence = min([o["confidence"] for o in low_conf_tokens], default=1.0)
        if residual_pua:
            confidence = 0.0

        # Honest-confidence safety net (module docstring, signal 3): any
        # leftover small (sub/superscript-sized) equation-font glyph
        # anywhere in the FINAL item text -- never attached to anything,
        # never consumed into any construct -- is a direct, mechanical
        # signal of an unresolved sub/superscript defect that no
        # per-token confidence above happened to catch.
        if residual_pua == 0:
            orphan_subsup = any(
                o["kind"] == "glyph" and o.get("is_eq")
                and round(o.get("size", body_size), 1) < 0.85 * body_size
                for o in zone_objs
            )
            if orphan_subsup:
                confidence = min(confidence, 0.5)

        constructs = set()
        for o in zone_objs:
            k = o.get("kind")
            if k == "frac":
                constructs.add("fraction")
            elif k == "sqrt":
                constructs.add("radical")
            elif k == "overline":
                constructs.add("overline")
            elif k == "bigop":
                constructs.add("integral" if o["text"].startswith("\\int") else "sigma")
            elif k == "delim_brace":
                constructs.add("multiline_brace")
            elif k in ("delim_bracket", "delim_bracket_piece"):
                constructs.add("multiline_bracket")
            if o.get("sup_suffix") or o.get("sub_suffix"):
                constructs.add("superscript_subscript")

        xs0 = [o["x0"] for o in zone_objs]
        xs1 = [o["x1"] for o in zone_objs]
        ys0 = [o["y0"] for o in zone_objs]
        ys1 = [o["y1"] for o in zone_objs]
        min_x0, max_x1 = min(xs0), max(xs1)
        min_y0, max_y1 = min(ys0), max(ys1)
        # convert to PyMuPDF-style top-down coords for compatibility with
        # image_cropper.py: y_top = page_height - y1 ; y_bottom = page_height - y0
        rect_topdown = [min_x0, page_height - max_y1, max_x1, page_height - min_y0]

        items.append({
            "page": page_num,
            "column": col_label,
            "item_number": h["item_number"],
            "rect": rect_topdown,
            "header_text": h["text"],
            "text": text,
            "confidence": round(confidence, 3),
            "constructs": sorted(constructs),
            "residual_pua": residual_pua,
        })
    return items


def extract_pdf_questions(pdf_path):
    """Drop-in replacement for the previous PyMuPDF-based
    extract_pdf_questions(pdf_path), using pdfminer.six per-character
    coordinates + geometric 2D reconstruction instead of discarded-layout
    text blocks."""
    all_items = []
    for page_num, page in enumerate(extract_pages(pdf_path)):
        page_height = page.bbox[3] - page.bbox[1]
        page_width = page.bbox[2] - page.bbox[0]
        mid_x = page.bbox[0] + page_width / 2.0

        glyphs = _extract_page_glyphs(page)
        left = [g for g in glyphs if _cx(g) < mid_x]
        right = [g for g in glyphs if _cx(g) >= mid_x]

        all_items.extend(_segment_column(left, page_num + 1, "left", page_height))
        all_items.extend(_segment_column(right, page_num + 1, "right", page_height))

    return all_items
