# -*- coding: utf-8 -*-
"""
Tests for pipeline/dataset_parser/hwp_layout_reconstructor.py.

Covers each construct resolver in isolation with synthetic glyph pools
(so the geometry being tested is explicit and doesn't depend on any one
PDF's exact coordinates), plus integration tests against the real
202606-h3-math-dif.pdf calibration file that lock in the flagship
DIF_15 orphaned-integral-limits regression this module exists to fix.
"""
import os
import sys
import unittest

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
PIPELINE_DIR = os.path.join(BASE_DIR, 'pipeline')
if PIPELINE_DIR not in sys.path:
    sys.path.insert(0, PIPELINE_DIR)

from dataset_parser import hwp_layout_reconstructor as hlr

CALIBRATION_PDF = os.path.join(BASE_DIR, 'raw_dataset', '202606-h3-math-dif.pdf')


def glyph(text, x0, y0, x1, y1, size=11.0, is_eq=True):
    return {
        "text": text, "orig": text,
        "x0": x0, "y0": y0, "x1": x1, "y1": y1,
        "size": size, "fontname": "AIKLMH+HyhwpEQ" if is_eq else "AIKLMG+Body",
        "is_eq": is_eq, "kind": "glyph", "residual_pua": 0,
    }


class TestPuaDecode(unittest.TestCase):
    def test_known_pua_codepoints_decode(self):
        self.assertEqual(hlr._decode_char(""), "1")
        self.assertEqual(hlr._decode_char(""), "∫")
        self.assertEqual(hlr._decode_char(""), "―")
        self.assertEqual(hlr._decode_char(""), "a")

    def test_non_pua_passthrough(self):
        self.assertEqual(hlr._decode_char("A"), "A")
        self.assertEqual(hlr._decode_char("가"), "가")

    def test_unmapped_pua_is_flagged_residual(self):
        # A PUA codepoint not in the 80-entry table must be detectable as
        # residual (used by the confidence/QA gate), not silently dropped.
        self.assertTrue(hlr._is_pua(""))
        self.assertEqual(hlr._decode_char(""), "")


class TestFractionResolution(unittest.TestCase):
    def test_simple_fraction(self):
        # "3" over "4" separated by a bar, like \frac{3}{4}
        pool = [
            glyph("3", 10, 12, 15, 21, size=10),
            glyph("―", 10, 8, 16, 11, size=10),
            glyph("4", 10, 0, 15, 7, size=10),
        ]
        new_pool, changed, constructs = hlr.resolve_bars_once(pool)
        self.assertTrue(changed)
        self.assertEqual(constructs, {"fraction"})
        self.assertEqual(len(new_pool), 1)
        self.assertEqual(new_pool[0]["text"], "\\frac{3}{4}")

    def test_nested_fraction_as_numerator(self):
        # \frac{\sqrt{3}}{2} -- a radical sitting as an outer fraction's
        # numerator. This is the exact shape of the DIF item 26 (y=√3/2)
        # regression: a wide outer bar's x-range legitimately overlaps a
        # narrower nested radical's x-range.
        pool = [
            glyph("√", 0, 10, 11, 22, size=12),
            glyph("―", 11, 13, 18, 24, size=11),   # radical vinculum (narrow)
            glyph("3", 11, 10, 17, 21, size=11),    # radicand
            glyph("―", 0, 0, 22, 11, size=11),      # outer fraction bar (wide)
            glyph("2", 3, -11, 9, -1, size=11),     # outer denominator
        ]
        new_pool, changed, constructs = hlr.resolve_bars_once(pool)
        self.assertTrue(changed)
        self.assertIn("fraction", constructs)
        self.assertIn("radical", constructs)
        self.assertEqual(len(new_pool), 1)
        self.assertEqual(new_pool[0]["text"], "\\frac{\\sqrt{3}}{2}")

    def test_empty_numerator_becomes_overline(self):
        # HWP renders segment-name overlines (\overline{AB}) with the
        # same extensible bar glyph as a fraction, distinguished only by
        # having nothing above it.
        pool = [
            glyph("―", 10, 8, 30, 11, size=10),
            glyph("A", 10, 0, 16, 7, size=10),
            glyph("B", 17, 0, 23, 7, size=10),
        ]
        new_pool, changed, constructs = hlr.resolve_bars_once(pool)
        self.assertTrue(changed)
        self.assertEqual(constructs, {"overline"})
        self.assertEqual(new_pool[0]["text"], "\\overline{AB}")

    def test_no_bar_no_change(self):
        pool = [glyph("x", 0, 0, 5, 10, size=10)]
        new_pool, changed, constructs = hlr.resolve_bars_once(pool)
        self.assertFalse(changed)
        self.assertEqual(constructs, set())


class TestRadicalIndex(unittest.TestCase):
    def test_cube_root_index(self):
        # ∛9 -- small "3" index raised just above/left of the √ glyph,
        # matching the item 1 calibration case (∛9 × 3^(-5/3)).
        pool = [
            glyph("3", 2, 6, 5, 10, size=6, is_eq=True),     # index
            glyph("√", 0, 0, 11, 12, size=12),
            glyph("―", 11, 3, 17, 13, size=11),
            glyph("9", 11, 0, 17, 11, size=11),
        ]
        new_pool, changed, constructs = hlr.resolve_bars_once(pool)
        self.assertTrue(changed)
        self.assertEqual(constructs, {"radical"})
        self.assertEqual(new_pool[0]["text"], "\\sqrt[3]{9}")

    def test_plain_square_root_no_index(self):
        pool = [
            glyph("√", 0, 0, 11, 12, size=12),
            glyph("―", 11, 3, 17, 13, size=11),
            glyph("9", 11, 0, 17, 11, size=11),
        ]
        new_pool, changed, constructs = hlr.resolve_bars_once(pool)
        self.assertEqual(new_pool[0]["text"], "\\sqrt{9}")


class TestBigOperatorLimits(unittest.TestCase):
    def test_integral_limits(self):
        # \int_{p}^{p+3} -- matches the DIF_15 shape: small (size ~0.34x
        # the operator) limit glyphs above/below the operator's center.
        pool = [
            glyph("∫", 0, 0, 14, 22, size=22),
            glyph("p", 14, 17, 17, 24, size=7.5),
            glyph("+", 17, 17, 20, 24, size=7.5),
            glyph("3", 20, 17, 23, 24, size=7.5),
            glyph("p", 1, -3, 4, 4, size=7.5),
        ]
        new_pool, changed, constructs = hlr.resolve_bigops_once(pool)
        self.assertTrue(changed)
        self.assertEqual(constructs, {"integral"})
        self.assertEqual(new_pool[0]["text"], "\\int_{p}^{p+3}")

    def test_sigma_limits(self):
        pool = [
            glyph("Σ", 0, 0, 14, 20, size=19.8),
            glyph("5", 5, 15, 9, 22, size=7.5),
            glyph("k", -1, -4, 2, 2, size=7.5),
            glyph("=", 2, -4, 5, 2, size=7.5),
            glyph("1", 5, -4, 8, 2, size=7.5),
        ]
        new_pool, changed, constructs = hlr.resolve_bigops_once(pool)
        self.assertEqual(constructs, {"sigma"})
        self.assertEqual(new_pool[0]["text"], "\\sum_{k=1}^{5}")

    def test_body_text_not_absorbed_as_limit(self):
        # regression: a large integral operator's size-relative threshold
        # must not admit ordinary body-sized Korean/Latin text as a limit
        # candidate (this orphaned entire clauses into (가)/(나) integral
        # limits before the is_eq + tightened size_cap fix).
        pool = [
            glyph("∫", 0, 0, 14, 22, size=22),
            glyph("모", 20, 2, 31, 13, size=11.48, is_eq=False),
            glyph("든", 31, 2, 42, 13, size=11.48, is_eq=False),
        ]
        new_pool, changed, constructs = hlr.resolve_bigops_once(pool)
        self.assertFalse(changed)
        # the body text must survive untouched, not be swallowed into ^{}/_{}
        texts = {o["text"] for o in new_pool}
        self.assertIn("모", texts)
        self.assertIn("든", texts)


class TestSubSup(unittest.TestCase):
    def test_simple_superscript(self):
        pool = [
            glyph("x", 0, 0, 6, 11, size=11),
            glyph("2", 6, 6, 10, 12, size=7.5),
        ]
        new_pool, constructs = hlr.resolve_subsup(pool, body_size=11)
        self.assertEqual(constructs, {"superscript_subscript"})
        self.assertEqual(len(new_pool), 1)
        self.assertEqual(new_pool[0]["sup_suffix"], "^{2}")

    def test_simple_subscript(self):
        pool = [
            glyph("a", 0, 0, 6, 11, size=11),
            glyph("n", 6, -3, 10, 2, size=7.5),
        ]
        new_pool, constructs = hlr.resolve_subsup(pool, body_size=11)
        self.assertEqual(new_pool[0]["sub_suffix"], "_{n}")

    def test_compound_superscript_chains_through_resolved_token(self):
        # 3^{-5/3}: "-" attaches directly to the base "3"; the small
        # \frac{5}{3} token (already resolved by resolve_bars_once) sits
        # a few points further right and must chain onto the same anchor
        # via the "-" rather than being left stranded (item 1 regression).
        pool = [
            glyph("3", 0, 0, 5, 11, size=11),
            glyph("-", 5, 11, 8, 18, size=7.5),
            {
                "text": "\\frac{5}{3}", "x0": 8.5, "x1": 14, "y0": 8, "y1": 22,
                "size": 7.5, "kind": "frac", "row_y": 10, "confidence": 1.0,
            },
        ]
        new_pool, constructs = hlr.resolve_subsup(pool, body_size=11)
        anchors = [o for o in new_pool if o["text"] == "3"]
        self.assertEqual(len(anchors), 1)
        self.assertEqual(anchors[0]["sup_suffix"], "^{-\\frac{5}{3}}")


class TestDelimiters(unittest.TestCase):
    def test_brace_pieces_consumed_no_literal_survivor(self):
        pool = [
            glyph("⎧", 0, 20, 5, 30, size=11),
            glyph("⎪", 0, 10, 5, 20, size=15),
            glyph("⎨", 0, 0, 5, 10, size=11),
            glyph("⎪", 0, -10, 5, 0, size=15),
            glyph("⎩", 0, -20, 5, -10, size=11),
            glyph("x", 6, 20, 11, 28, size=11),
            glyph("y", 6, -18, 11, -10, size=11),
        ]
        new_pool, changed, constructs = hlr.resolve_delimiters_once(pool)
        self.assertTrue(changed)
        self.assertEqual(constructs, {"multiline_brace"})
        survivors = {o["text"] for o in new_pool if o["kind"] == "glyph"}
        self.assertFalse(survivors & hlr._BRACE_CHARS)
        self.assertIn("\\left\\{", new_pool[0]["text"])
        self.assertIn("\\right.", new_pool[0]["text"])

    def test_bracket_pieces_consumed_no_literal_survivor(self):
        pool = [
            glyph("⎡", 0, 10, 5, 20, size=11),
            glyph("⎣", 0, -10, 5, 0, size=11),
            glyph("⎤", 20, 10, 25, 20, size=11),
            glyph("⎦", 20, -10, 25, 0, size=11),
            glyph("1", 8, 0, 12, 10, size=11),
        ]
        new_pool, changed, constructs = hlr.resolve_delimiters_once(pool)
        self.assertTrue(changed)
        self.assertEqual(constructs, {"multiline_bracket"})
        survivors = {o["text"] for o in new_pool if o["kind"] == "glyph"}
        self.assertFalse(survivors & hlr._BRACKET_CHARS)


class TestRowClustering(unittest.TestCase):
    def test_chained_row_membership(self):
        # A row with 3 sub-pieces whose row_y values step by ~3-4pt each
        # (e.g. overline > body text > inline fraction bar) must all end
        # up on the SAME output row even though the first-vs-last gap
        # exceeds tol, as long as each step is within tol of the row's
        # current extent (item 8 calibration regression).
        objs = [
            glyph("―", 0, 20, 10, 20, size=11), glyph("A", 0, 17, 5, 17, size=11),
            glyph("B", 20, 17, 25, 17, size=11),
        ]
        objs[0]["row_y"] = 20.0
        objs[1]["row_y"] = 17.0
        objs[2]["row_y"] = 13.0
        rows = hlr.cluster_rows(objs, tol=4.5)
        self.assertEqual(len(rows), 1)


class TestFullPdfCalibration(unittest.TestCase):
    """Locks in the flagship 202606_MATH_DIF_15 fix and a handful of
    other calibration items against regression. Skips gracefully if the
    calibration PDF isn't available in this checkout."""

    @classmethod
    def setUpClass(cls):
        if not getattr(hlr, "_HAS_PDFMINER", False):
            raise unittest.SkipTest("pdfminer not installed")
        if not os.path.exists(CALIBRATION_PDF):
            raise unittest.SkipTest("calibration PDF not present")
        cls.items = hlr.extract_pdf_questions(CALIBRATION_PDF)
        cls.by_num = {it["item_number"]: it for it in cls.items}

    def test_all_30_items_found_no_dup_no_missing(self):
        self.assertEqual(len(self.items), 30)
        self.assertEqual(set(self.by_num.keys()), set(range(1, 31)))

    def test_item_15_integral_limits_not_orphaned(self):
        # This is the flagship example from the brief:
        # printed page reads (가) ∫_p^{p+3}|f(x)|dx ≠ |∫_p^{p+3}f(x)dx|
        text = self.by_num[15]["text"]
        self.assertIn("\\int_{p}^{p+3}", text)
        self.assertIn("∣f(x)∣dx≠∣\\int_{p}^{p+3}f(x)dx∣", text)
        self.assertNotIn("―", text)
        self.assertEqual(self.by_num[15]["residual_pua"], 0)

    def test_item_1_nested_radical_index_and_exponent_fraction(self):
        text = self.by_num[1]["text"]
        self.assertIn("\\sqrt[3]{9}", text)
        self.assertIn("3^{-\\frac{5}{3}}", text)

    def test_item_6_two_fractions_same_line(self):
        text = self.by_num[6]["text"]
        self.assertIn("\\frac{3π}{2}", text)
        self.assertIn("cos^{2}θ", text)
        self.assertIn("\\frac{1}{10}", text)

    def test_item_8_overline_segment_notation(self):
        text = self.by_num[8]["text"]
        self.assertIn("\\overline{AB}", text)
        self.assertIn("\\overline{BC}", text)
        self.assertIn("\\frac{1}{4}", text)

    def test_item_26_nested_fraction_of_radical(self):
        text = self.by_num[26]["text"]
        self.assertIn("\\frac{\\sqrt{3}}{2}", text)

    def test_no_item_has_stranded_special_chars(self):
        special = hlr._SPECIAL_ROLE_CHARS - {hlr._RADICAL_CHAR}
        for it in self.items:
            survivors = special & set(it["text"])
            self.assertFalse(
                survivors,
                "item %s has stranded literal special chars: %s\n%s"
                % (it["item_number"], survivors, it["text"]),
            )

    def test_no_residual_pua_across_calibration_file(self):
        for it in self.items:
            self.assertEqual(it["residual_pua"], 0, it["item_number"])


class TestRegressionFixesTrackD(unittest.TestCase):
    """Pins the specific corpus-wide defects named in the Track D
    adversarial verification report (scratch/staging/verify/trackD.txt)
    against regression, one real PDF item per defect class:

      (a) recursive resolution -- sub/superscript loss inside a
          construct body (fraction/radical/sigma) is destroyed
      (b) sigma/integral limit-window scrambling between two operators
          sharing a row (or two branches of the same piecewise stacked
          vertically)
      (c) reading-order hoisting of an overline/vector token above the
          sentence/header it is inline with
      (d) empty/duplicated/fragmented multiline-brace bodies
      (e) multiline-brace content sorted before the text that introduces
          it (e.g. "g(x)=" line)

    Each PDF is loaded once (class-level cache) since several defects
    share a PDF. Skips gracefully (matching TestFullPdfCalibration's own
    convention) if a source PDF is not present in this checkout."""

    _CACHE = {}

    @classmethod
    def _items(cls, pdf_name):
        if not getattr(hlr, "_HAS_PDFMINER", False):
            raise unittest.SkipTest("pdfminer not installed")
        if pdf_name not in cls._CACHE:
            path = os.path.join(BASE_DIR, 'raw_dataset', pdf_name)
            if not os.path.exists(path):
                raise unittest.SkipTest("%s not present" % pdf_name)
            items = hlr.extract_pdf_questions(path)
            by_num = {}
            for it in items:
                by_num.setdefault(it["item_number"], []).append(it)
            cls._CACHE[pdf_name] = by_num
        return cls._CACHE[pdf_name]

    def _item(self, pdf_name, item_number, column=None):
        by_num = self._items(pdf_name)
        candidates = by_num.get(item_number, [])
        if column is not None:
            candidates = [it for it in candidates if it["column"] == column]
        self.assertTrue(candidates, "item %d not found in %s" % (item_number, pdf_name))
        return candidates[0]

    # -- (a) recursive resolution: sub/superscript inside a construct body --

    def test_a_202109_dif_07_subscripts_survive_inside_sigma_and_fraction(self):
        # Ground truth: sum_{k=1}^{n} (a_{k+1}-a_k)/(a_k a_{k+1}) = 1/n.
        # v1 flat-linearized the fraction's numerator/denominator BEFORE
        # sub/superscript resolution ran, destroying every "_k"/"_{k+1}"
        # inside it ("ak+1-ak" / "akak+1") while identical subscripts
        # OUTSIDE the fraction (e.g. a_{13} later in the same item)
        # survived -- the defining symptom of the bug.
        it = self._item('202109-h3-math-dif.pdf', 7)
        text = it["text"]
        self.assertIn("\\sum_{k=1}^{n}\\frac{a_{k+1}-a_{k}}{a_{k}a_{k+1}}=\\frac{1}{n}", text)
        self.assertIn("a_{13}", text)
        # the old corruption patterns must not be present
        self.assertNotIn("ak+1-ak", text)
        self.assertNotIn("akak+1", text)

    def test_a_202511_dif_20_nested_sigma_subscripts_resolved(self):
        it = self._item('202511-h3-math-dif.pdf', 20)
        text = it["text"]
        self.assertIn("\\sum_{k=1}^{12}a_{k}+\\sum_{k=1}^{5}a_{2k+1}", text)
        self.assertIn("a_{2k+1}", text)

    # -- (b) sigma/integral limit-window scrambling --

    def test_b_202511_dif_20_each_sigma_keeps_its_own_limits_exactly_once(self):
        # v1 produced "_{k}\\sum_{=1}^{125}a_{k}+_{k}\\sum_{1k+1}a_{2}":
        # a detached "_{k}" floating before \\sum, malformed limits
        # ("=1", "1k+1"), and a digit-run "125" formed by one operator's
        # window swallowing the NEXT operator's own upper limit.
        it = self._item('202511-h3-math-dif.pdf', 20)
        text = it["text"]
        self.assertIn("\\sum_{k=1}^{12}", text)
        self.assertIn("\\sum_{k=1}^{5}", text)
        self.assertIn("\\sum_{k=1}^{n+1}", text)
        # no operator's own "k=1" may be split off as a detached prefix,
        # and no limit run may be malformed like the v1 "=1"/"125"/"1k+1"
        self.assertNotIn("_{k}\\sum", text)
        self.assertNotIn("^{125}", text)
        self.assertNotIn("_{1k+1}", text)
        self.assertNotIn("_{=1", text)

    def test_b_202206_dif_14_stacked_integral_branches_each_keep_own_limits(self):
        # Distinct mechanism from the same-row case above: two \\int_0^x
        # branches of the SAME piecewise, stacked vertically (not on the
        # same row), where the first (tall, ~22pt) integral's plain
        # vertical reach swallowed the second branch's own upper limit
        # ("\\int_{x0}^{x}...(x<0) \\\\ \\int_{0}...(x>=0)", missing the
        # second branch's "^x" entirely).
        it = self._item('202206-h3-math-dif.pdf', 14)
        text = it["text"]
        self.assertEqual(text.count("\\int_{0}^{x}"), 2)
        self.assertNotIn("\\int_{x0}", text)

    # -- (c) reading-order hoisting (overline / vector notation) --

    def test_c_202106_geo_23_vector_overline_stays_inline_not_hoisted(self):
        # v1: "\\overline{a→}\\overline{b→}\\n23.두벡터=(k+3,3k-1)과=(1,1)..."
        # -- the vector tokens hoisted to their own line ABOVE the header,
        # and "a"/"b" vanished from their rightful inline position.
        it = self._item('202106-h3-math-geo.pdf', 23)
        text = it["text"]
        lines = text.split("\n")
        self.assertTrue(lines[0].startswith("23."), "header must be the first line, got: %r" % lines[0])
        self.assertIn("\\vec{a}=(k+3,3k-1)", text)
        self.assertIn("\\vec{b}=(1,1)", text)

    def test_c_202106_geo_24_no_orphaned_exponent_line_before_header(self):
        # v1: "22\\n24.타원\\frac{x}{8}+\\frac{y}{4}=1..." -- both "^2"
        # exponents stripped from x^2/y^2 and dumped as a floating "22"
        # line before the item's own header.
        it = self._item('202106-h3-math-geo.pdf', 24)
        text = it["text"]
        lines = text.split("\n")
        self.assertTrue(lines[0].startswith("24."), "header must be the first line, got: %r" % lines[0])
        self.assertIn("\\frac{x^{2}}{8}+\\frac{y^{2}}{4}=1", text)

    # -- (d) empty / fragmented / duplicated multiline-brace bodies --

    def test_d_202309_dif_13_piecewise_cubic_single_brace_no_empty_fragments(self):
        # v1 (worst finding in the whole audit): FOUR separate
        # \\left\\{...\\right. fragments for a 2-branch piecewise, two of
        # them empty, exponents ^3/^2 stripped off every term entirely
        # and dumped as a meaningless floating "32" token twice.
        it = self._item('202309-h3-math-dif.pdf', 13)
        text = it["text"]
        self.assertEqual(text.count("\\left\\{"), 1)
        self.assertEqual(text.count("\\right."), 1)
        self.assertNotIn("\\left\\{ \\right.", text)
        self.assertIn("-\\frac{1}{3}x^{3}-ax^{2}-bx(x<0)", text)
        self.assertIn("\\frac{1}{3}x^{3}+ax^{2}-bx(x", text)

    def test_d_202109_dif_15_piecewise_and_sigma_single_brace_no_empty_fragments(self):
        # v1: FIVE fragments for a 3-branch piecewise (one empty, one the
        # nonsense body "nn"), every a_n losing its own "_n", and the
        # sigma corrupted the same way as (b) ("_{k}\\sum_{=1}").
        it = self._item('202109-h3-math-dif.pdf', 15)
        text = it["text"]
        self.assertEqual(text.count("\\left\\{"), 1)
        self.assertEqual(text.count("\\right."), 1)
        self.assertNotIn("\\left\\{ \\right.", text)
        self.assertIn("a_{n+1}", text)
        self.assertIn("a_{5}+a_{6}", text)
        self.assertIn("\\sum_{k=1}^{5}a_{k}", text)

    def test_d_202206_dif_06_piecewise_no_empty_brace(self):
        it = self._item('202206-h3-math-dif.pdf', 6)
        text = it["text"]
        self.assertEqual(text.count("\\left\\{"), 1)
        self.assertNotIn("\\left\\{ \\right.", text)
        self.assertIn("x+a(x<-1)", text)
        self.assertIn("bx-2(x", text)

    # -- (e) multiline-brace line ordering (content correct, sorted before
    #        the "f(x)="/"g(x)=" line that introduces it) --

    def test_e_202106_dif_11_brace_follows_gx_equals_not_before(self):
        it = self._item('202106-h3-math-dif.pdf', 11)
        text = it["text"]
        idx_gx = text.find("g(x)=")
        idx_brace = text.find("\\left\\{")
        self.assertNotEqual(idx_gx, -1)
        self.assertNotEqual(idx_brace, -1)
        self.assertLess(idx_gx, idx_brace,
                         "brace must appear AFTER 'g(x)=' in printed reading order:\n%r" % text)

    def test_e_202206_dif_14_brace_follows_gx_equals_not_before(self):
        it = self._item('202206-h3-math-dif.pdf', 14)
        text = it["text"]
        idx_gx = text.find("g(x)=")
        idx_brace = text.find("\\left\\{")
        self.assertNotEqual(idx_gx, -1)
        self.assertNotEqual(idx_brace, -1)
        self.assertLess(idx_gx, idx_brace,
                         "brace must appear AFTER 'g(x)=' in printed reading order:\n%r" % text)

    def test_e_202211_dif_09_bracket_stays_inline_with_sentence(self):
        # v1: the \\left[...\\right] bracket emitted on its own line
        # BEFORE "가 닫힌구간 ... 에서 최댓값...", leaving a nonsensical
        # gap ("구간 에서") with the bracket floating above it.
        it = self._item('202211-h3-math-dif.pdf', 9)
        text = it["text"]
        self.assertIn("닫힌구간 \\left[", text)
        self.assertIn("\\right]에서", text)
        self.assertNotIn("구간 에서", text)


if __name__ == "__main__":
    unittest.main()
