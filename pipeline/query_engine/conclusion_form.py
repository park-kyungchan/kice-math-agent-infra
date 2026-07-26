# -*- coding: utf-8 -*-
"""Conclusion representation for the ce.* axis family.

WHAT A CONCLUSION IS
--------------------
A problem's stated conditions are one ENCODING of an underlying mathematical CONCLUSION, and
many different conditions force the same conclusion. The analytical unit is therefore the
conclusion. A raw stated condition -- "(가) ..." as it appears on the page -- is never a
conclusion node; a node exists only once an inference step consumes conditions and/or prior
nodes and produces a new claim in the controlled vocabulary below.

A conclusion is a triple:

    (schema, binding, ambient_typing)

`schema` names a predicate and fixes its slot signature. `binding` fills those slots and tags
each filling as ground, existential, universal or a problem-level free parameter.
`ambient_typing` fixes the search space the claim lives in -- it is prior to both conditions
and conclusions, because it types the unknown rather than asserting anything about it.

WHY THE VOCABULARY IS CLOSED
----------------------------
"Are these two conclusions the same?" has to be decidable, or the whole axis collapses into
opinion. A closed sort/predicate vocabulary plus a curated finite lemma library makes the
common cases mechanical, and an explicit UNDECIDED verdict makes the remainder visible instead
of silently guessed. The alternative designs both fail: an open vocabulary is never decidable,
and a theorem-prover encoding is not producible at corpus scale.

NO SORT WITHOUT A WITNESS
-------------------------
Every sort and every predicate below is justified by an object that actually appears in a real
exam item. Nothing is added speculatively. That discipline is why there is no SEQUENCE sort:
see COVERAGE below.

COVERAGE -- stated honestly, because pretending is worse than a recorded limit
-----------------------------------------------------------------------------
  202606_MATH_DIF_15   EXPRESSIBLE. Its three independent nodes and both entailments translate
                       and solve; verified end to end.
  202106_MATH_DIF_22   PARTIALLY EXPRESSIBLE. Root-count and derivative-value facts are
                       expressible; the root count of f(x - f(x)), where f is still the
                       unknown, is expressible but NOT uniformly translatable -- it needs
                       bespoke case analysis rather than a fixed function of the schema.
  202411_MATH_DIF_22   NOT EXPRESSIBLE. It is a sequence problem. There is no SEQUENCE sort,
                       and adding one would not be enough: the solving architecture here
                       ("reduce to equations in the coefficients of a fixed-degree function")
                       does not fit an integer-recurrence search. A different track, not a
                       missing entry.
  202506_MATH_DIF_22   EXPRESSIBLE IN PRINCIPLE, UNIMPLEMENTED HERE. Its intersection, line
                       and area predicates are specified below and were verified by hand, but
                       are not wired into the translator; calling them raises rather than
                       silently returning nothing.

Distinguish these three states carefully. "Expressible" means the vocabulary can state the
fact. "Translatable" means `to_constraints` turns it into something a solver can use. They are
not the same, and conflating them is how a system comes to look more capable than it is.
"""
import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Tuple

import sympy as sp

X = sp.Symbol('x')

LEMMA_LIBRARY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'storage', 'ce_lemma_library.json',
)

# --------------------------------------------------------------------------
# SORTS -- each with the real object that forced it into existence.
# --------------------------------------------------------------------------
SORTS = {
    'FUNCTION':    'f in 202606_MATH_DIF_15; the curves y=2^x+k/2 etc. in 202506_MATH_DIF_22. '
                   'Curves are NOT a separate sort -- they are functions in a different '
                   'analytic family, carried by ambient_typing.family.',
    'REAL_VALUE':  '0, 2, 3, -1, 27 in 202606_MATH_DIF_15.',
    'ORDER':       'derivative order: 0 for f(6), 1 for f\'(1)=1 in 202106_MATH_DIF_22. '
                   'Distinct from POS_INT because 0 is a legal order but never a legal '
                   'multiplicity.',
    'POS_INT':     'multiplicities 2 and 1 in 202606_MATH_DIF_15; the degree 3.',
    'COEFFICIENT': 'the leading coefficient a of f in 202606_MATH_DIF_15.',
    'EXPRESSION':  'x - f(x), and the composition f(x - f(x)), in 202106_MATH_DIF_22.',
    'POINT':       'the intersection points A and B, and the origin O, in 202506_MATH_DIF_22.',
    'LINE':        'the line through A with slope -1 in 202506_MATH_DIF_22.',
    'PARAMETER':   'k in 202506_MATH_DIF_22 -- a symbol the problem itself names.',
}

BINDING_KINDS = ('GROUND', 'EXISTENTIAL', 'UNIVERSAL', 'FREE_PARAM')

# Sorts that carry no identity. A real value, a count and a derivative order appear in almost
# every schema, so two schemas sharing one of them have not thereby been shown to be about the
# same kind of thing -- "the area is 16" and "the local minimum is -1" both mention a real
# number and are obviously different conclusions. Only the STRUCTURAL sorts (what the claim is
# ABOUT) discriminate, so only they are consulted when proving two schemas distinct.
SCALAR_SORTS = frozenset({'REAL_VALUE', 'POS_INT', 'ORDER'})

# --------------------------------------------------------------------------
# PREDICATE SCHEMAS. `slots` is the FIXED canonical order -- the hash depends on
# it, so it is part of the contract and may not be reordered without a version bump.
# `translatable` records whether to_constraints can turn this into solver input.
# --------------------------------------------------------------------------
SCHEMAS: Dict[str, Dict[str, Any]] = {
    'ROOT_MULT': {
        'slots': (('F', 'FUNCTION'), ('X0', 'REAL_VALUE'), ('MULT', 'POS_INT')),
        'translatable': True,
        'meaning': 'F vanishes at X0 to multiplicity exactly MULT.',
        # SIGN_CHANGE is deliberately NOT a slot. For a polynomial it is entailed by the
        # parity of MULT (lemma MULTIPLICITY_PARITY_SIGN), so binding it separately would let
        # two spellings of one fact hash differently.
    },
    'EXTREMUM_VALUE': {
        'slots': (('F', 'FUNCTION'), ('X0', 'REAL_VALUE'), ('VALUE', 'REAL_VALUE'),
                  ('KIND', 'REAL_VALUE')),
        'translatable': True,
        'meaning': "F'(X0)=0 and F(X0)=VALUE, with KIND naming which extremum it is.",
        # KIND is carried and hashed but does not currently constrain the solve: whether
        # F''(X0) has the matching sign is a further fact. Promoting it is left open.
    },
    'COEFF_SIGN': {
        'slots': (('F', 'FUNCTION'), ('C', 'COEFFICIENT'), ('SIGN', 'REAL_VALUE')),
        'translatable': False,
        'meaning': 'The named coefficient of F has the given sign.',
        # An inequality. Equality-only solving cannot express it; it needs branch filtering.
        # Recorded as untranslatable rather than silently contributing nothing.
    },
    'DERIV_EVAL': {
        'slots': (('F', 'FUNCTION'), ('ORDER', 'ORDER'), ('X0', 'REAL_VALUE'),
                  ('VALUE', 'REAL_VALUE'), ('REL', 'REAL_VALUE')),
        'translatable': True,   # for REL == 'EQ' only; see to_constraints
        'meaning': 'The ORDER-th derivative of F at X0 stands in relation REL to VALUE.',
    },
    'ROOT_COUNT': {
        'slots': (('G', 'EXPRESSION'), ('N', 'POS_INT')),
        'translatable': False,
        'meaning': 'The equation G(x)=0 has exactly N distinct real roots.',
        # Translatable by discriminant case-split when G is the unknown function itself, but
        # NOT when G composes the unknown with itself (202106's f(x-f(x))). Marked
        # untranslatable rather than translatable-sometimes, because a caller cannot act on
        # "sometimes".
    },
    'INTERSECTION_POINT': {
        'slots': (('C1', 'FUNCTION'), ('C2', 'FUNCTION'), ('P', 'POINT')),
        'translatable': False,
        'meaning': 'C1 and C2 meet at P.',
    },
    'LINE_THROUGH': {
        'slots': (('P', 'POINT'), ('SLOPE', 'REAL_VALUE'), ('L', 'LINE')),
        'translatable': False,
        'meaning': 'L is the line through P with the given slope.',
    },
    'AREA_TRIANGLE': {
        'slots': (('P1', 'POINT'), ('P2', 'POINT'), ('P3', 'POINT'), ('VALUE', 'REAL_VALUE')),
        'translatable': False,
        'meaning': 'The triangle P1P2P3 has the given area.',
    },
}


class ConclusionError(ValueError):
    """Raised when a conclusion is malformed. Never raised for a conclusion that is merely
    unresolvable -- that is what the UNDECIDED verdict is for."""


def _exact(value):
    """Numbers enter the system exactly or not at all.

    A raw float is rejected at the boundary rather than normalised later: 0.1 has already lost
    information by the time it arrives, and a hash computed downstream would be reproducibly
    wrong rather than obviously wrong. Rational, Integer and exact decimal strings are fine.
    """
    if isinstance(value, float):
        raise ConclusionError(
            f'float {value!r} rejected: numbers must enter exactly. Pass a string such as '
            f'"0.25", a Fraction, or a sympy Rational -- a float has already lost precision.'
        )
    if isinstance(value, (int, sp.Integer, sp.Rational)):
        return sp.nsimplify(value)
    if isinstance(value, str):
        try:
            return sp.nsimplify(sp.Rational(value))
        except (TypeError, ValueError, sp.SympifyError):
            return value          # a symbolic label such as 'LOCAL_MIN' or 'EQ'
    return value


class Conclusion:
    """One conclusion node: schema + binding + ambient typing."""

    def __init__(self, schema: str, binding: Dict[str, Tuple[str, Any]],
                 ambient: Optional[Dict[str, Any]] = None, node_id: Optional[str] = None):
        if schema not in SCHEMAS:
            raise ConclusionError(
                f'unknown schema {schema!r}. The vocabulary is closed by design; adding a '
                f'schema requires a witness object in a real item.'
            )
        declared = [name for name, _sort in SCHEMAS[schema]['slots']]
        missing = [s for s in declared if s not in binding]
        extra = [s for s in binding if s not in declared]
        if missing or extra:
            raise ConclusionError(f'{schema}: missing slots {missing}, unknown slots {extra}')
        self.schema = schema
        self.node_id = node_id
        self.ambient = dict(ambient or {})
        self.binding = {}
        for slot in declared:
            kind, value = binding[slot]
            if kind not in BINDING_KINDS:
                raise ConclusionError(f'{schema}.{slot}: unknown binding kind {kind!r}')
            self.binding[slot] = (kind, _exact(value))

    # -- canonical form and hash -------------------------------------------------
    def canonical_form(self) -> str:
        """Deterministic serialisation. Two spellings of one conclusion must produce the same
        string; two different conclusions must not.

        Existentials are alpha-renamed by first appearance, so a claim written with a bound
        variable R and the same claim written with S collapse together. Free parameters are
        NOT renamed: they are names the problem itself chose, and two problems naming
        different parameters have not thereby made the same claim.
        """
        alpha: Dict[Any, str] = {}
        parts = []
        for slot, _sort in SCHEMAS[self.schema]['slots']:
            kind, value = self.binding[slot]
            if kind in ('EXISTENTIAL', 'UNIVERSAL'):
                if value not in alpha:
                    alpha[value] = f'{kind[0]}{len(alpha) + 1}'
                shown = alpha[value]
            elif isinstance(value, sp.Basic):
                shown = sp.srepr(sp.nsimplify(sp.expand(sp.simplify(value))))
            else:
                shown = str(value)
            parts.append(f'{slot}:{kind}:{shown}')
        ambient = json.dumps(self.ambient, sort_keys=True, ensure_ascii=True)
        return f'{self.schema}|{"|".join(parts)}|ambient={ambient}'

    def normal_form_hash(self) -> str:
        return hashlib.sha256(self.canonical_form().encode('utf-8')).hexdigest()

    # -- translation -------------------------------------------------------------
    def to_constraints(self, f: sp.Expr) -> List[sp.Basic]:
        """Symbolic constraints for a solver. Raises for a schema that is expressible but not
        translatable, rather than returning [] -- an empty list is indistinguishable from "no
        information", which is how an untranslatable claim comes to look satisfied."""
        spec = SCHEMAS[self.schema]
        if not spec['translatable']:
            raise ConclusionError(
                f'{self.schema} is expressible but not translatable to solver constraints '
                f'({spec["meaning"]}). Returning no constraints would let it read as '
                f'satisfied; the caller must handle this explicitly.'
            )
        g = lambda s: self.binding[s][1]
        if self.schema == 'ROOT_MULT':
            x0, m = g('X0'), int(g('MULT'))
            return [sp.Eq(f.subs(X, x0), 0)] + [
                sp.Eq(sp.diff(f, X, k).subs(X, x0), 0) for k in range(1, m)
            ]
        if self.schema == 'EXTREMUM_VALUE':
            x0 = g('X0')
            return [sp.Eq(sp.diff(f, X).subs(X, x0), 0), sp.Eq(f.subs(X, x0), g('VALUE'))]
        if self.schema == 'DERIV_EVAL':
            rel = str(g('REL'))
            if rel != 'EQ':
                raise ConclusionError(
                    f'DERIV_EVAL with REL={rel} is an inequality; equality-only solving cannot '
                    f'express it. Needs branch filtering (left open by design).'
                )
            return [sp.Eq(sp.diff(f, X, int(g('ORDER'))).subs(X, g('X0')), g('VALUE'))]
        raise ConclusionError(f'no translation implemented for {self.schema}')

    def __repr__(self):
        return f'<Conclusion {self.node_id or ""} {self.schema} {self.binding}>'


# --------------------------------------------------------------------------
# AMBIENT TYPING
# --------------------------------------------------------------------------
def build_function(ambient: Dict[str, Any]):
    """Turn ambient typing into the unknown function plus the constraints that type it.

    Ambient typing is prior to every conclusion: it says what KIND of object we are solving
    for, not any fact about it. For 202606_MATH_DIF_15 it comes straight from the opening
    sentence -- "상수항이 0인 삼차함수" gives degree 3 and a zero constant term, with no
    inference chain in between. That is exactly why it is not a conclusion node.
    """
    if ambient.get('family', 'POLYNOMIAL') != 'POLYNOMIAL':
        raise ConclusionError(
            f'ambient family {ambient.get("family")!r} is specified in the design but not '
            f'implemented here; only POLYNOMIAL is wired up.'
        )
    deg = ambient['degree']
    coeffs = sp.symbols(f'c0:{deg + 1}')
    f = sum(coeffs[i] * X ** i for i in range(deg + 1))
    cons = [sp.Eq(coeffs[i], _exact(v))
            for i, v in ((int(k[1:]), v) for k, v in ambient.get('fixed_coefficients', {}).items())]
    return f, list(coeffs), cons


# --------------------------------------------------------------------------
# RELATION VERDICT
# --------------------------------------------------------------------------
VERDICTS = ('IDENTICAL', 'EQUIVALENT', 'IMPLIES', 'OVERLAP', 'DISTINCT', 'UNDECIDED')


def load_lemmas(path: str = LEMMA_LIBRARY_PATH) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as fh:
        return json.load(fh).get('lemmas', [])


def relation(a: 'Conclusion', b: 'Conclusion',
             lemmas: Optional[List[Dict[str, Any]]] = None) -> Tuple[str, str]:
    """Decide how two conclusions relate. Returns (verdict, reason).

    The procedure is deliberately conservative: it returns UNDECIDED whenever it cannot prove
    its answer, and UNDECIDED is routed to human review rather than being quietly rounded to
    DISTINCT. A system that never says "I don't know" is not more capable, only less honest.
    """
    lemmas = load_lemmas() if lemmas is None else lemmas

    if a.normal_form_hash() == b.normal_form_hash():
        return 'IDENTICAL', 'identical normal form'

    if a.schema == b.schema:
        kinds_a = {s: k for s, (k, _v) in a.binding.items()}
        kinds_b = {s: k for s, (k, _v) in b.binding.items()}
        differing = [s for s in a.binding if a.binding[s] != b.binding[s]]
        # A ground instance implies the existential generalisation of itself, never the
        # converse: knowing the double root is AT 0 is strictly more than knowing one exists.
        if all(kinds_a[s] == 'GROUND' and kinds_b[s] == 'EXISTENTIAL' for s in differing):
            return 'IMPLIES', f'ground instance implies existential generalisation on {differing}'
        if all(kinds_b[s] == 'GROUND' and kinds_a[s] == 'EXISTENTIAL' for s in differing):
            return 'IMPLIES', f'reverse: {b.node_id or "b"} implies {a.node_id or "a"}'
        if all(kinds_a[s] == 'GROUND' and kinds_b[s] == 'GROUND' for s in differing):
            return 'DISTINCT', f'same schema, incompatible ground values on {differing}'
        return 'UNDECIDED', f'same schema, unresolved binding difference on {differing}'

    for lem in lemmas:
        if {a.schema, b.schema} == set(lem.get('bridges', [])):
            verdict = 'EQUIVALENT' if lem.get('direction') == 'BIDIRECTIONAL' else 'IMPLIES'
            return verdict, f'lemma {lem["lemma_id"]}'

    sorts_a = {srt for _n, srt in SCHEMAS[a.schema]['slots']} - SCALAR_SORTS
    sorts_b = {srt for _n, srt in SCHEMAS[b.schema]['slots']} - SCALAR_SORTS
    if sorts_a and sorts_b and not (sorts_a & sorts_b):
        return 'DISTINCT', (
            f'{a.schema} is about {sorted(sorts_a)} and {b.schema} is about {sorted(sorts_b)}; '
            f'they share no structural sort and no lemma bridges them'
        )
    return 'UNDECIDED', (
        f'{a.schema} and {b.schema} both involve {sorted(sorts_a & sorts_b) or "only scalars"} '
        f'but no lemma bridges them -- for human review, not a guess'
    )
