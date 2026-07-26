# Adjudication reference — sealed before the pilot runs
Committed 2026-07-26 BEFORE any adjudication code was executed against it, as acceptance
criterion AC2 requires. An implementer-authored reference voids AC2, so this records the
EVIDENCE, not merely the verdicts, and the evidence is the items' own text.

Subject: 202606_MATH_DIF_15 — cubic with zero constant term; two conditions about absolute-value
definite integrals; target f(6).

## 202106_MATH_DIF_22 — expected ACCEPT
Text: "(가) 방정식 f(x)=0의 서로 다른 실근의 개수는 2이다. ... f(1)=4, f′(1)=1, f′(0)>1일 때"
A real cubic with exactly two distinct real roots must have one double and one simple real root
(non-real roots come in conjugate pairs). Item 15 concludes a double root at x=0 and a simple
root at x=3. The shared conclusion is the root-multiplicity structure; item 15's ground instance
implies 2021-06's existential form, not the converse.
Note the incumbent's stored justification for this edge cites "absolute-value integral sign
change" — that item contains no integral at all. The edge is defensible; the reason given for it
was not.

## 202411_MATH_DIF_22 — expected NOT ACCEPTED
Text: "모든 항이 정수이고 다음 조건을 만족시키는 모든 수열 {a_n}에 대하여 |a_1|의 값의 합을 구하시오."
A sequence problem. No cubic, no function of a real variable, no calculus. The incumbent's stored
relation text claims "삼차함수 비율관계" — flatly false.
Expected outcome is NOT_EXPRESSIBLE rather than REJECT: the vocabulary has no sort for integer
recurrences, so the claim can be neither confirmed nor refuted from inside it. Recording it as
REJECT would let a coverage gap masquerade as a finding about mathematics.

## 202506_MATH_DIF_22 — expected REJECT
Text: "k>1인 실수 k에 대하여 두 곡선 y=2^{x}+k/2, y=k×(1/2)^{x}+k-2 가 만나는 점을 A라 하고 ...
삼각형 AOB의 넓이가 16일 때"
Exponential curves, an intersection point, a line of slope -1, a triangle area. Its conclusions
are about points and areas; item 15's are about a function's roots and extremum. No structural
sort in common and no lemma bridging them.

## Expected tally
ACCEPT 1 · REJECT 1 · NOT_EXPRESSIBLE 1 · UNDECIDED 0
