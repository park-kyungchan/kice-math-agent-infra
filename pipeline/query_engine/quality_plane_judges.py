#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Quality Plane & 9-Judge Veto Gate Architecture (quality_plane_judges.py)

Phase 2 Implementation for v2.7.0:
- 9 Independent Quality Judges:
  1. ParsingJudge: Checks losslessness of LaTeX content, score, asset URLs.
  2. MathEquivalenceJudge: Checks logical derivation and root multiplicity.
  3. IndependentSolverJudge: Checks independent solution derivation vs answer.
  4. DistractorReplayJudge: Checks DistractorReplayEngine Veto status across options.
  5. CurriculumJudge: Checks achievement standard / curriculum unit mapping.
  6. LineageJudge: Checks precedent relationships against 7 closed relation Enums and genealogy_parent_allowed rule.
  7. InstructorJudge: Checks standard_solution, shortcut_solution, shortcut_prerequisites, shortcut_traps completeness.
  8. AdversarialJudge: Checks counterexamples and high confidence false claims.
  9. HoldoutJudge: Checks unseen holdout item generalization status.
- QualityPlaneEvaluator: Aggregates 9 Judges, computes weighted confidence, applies Veto gates.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
import sympy as sp

from pipeline.query_engine.distractor_replay_engine import (
    DistractorReplayEngine,
    DistractorHypothesis,
    ReplayResult,
    _compare_numeric_values,
)


# Closed Lineage Relation Enums and genealogy_parent_allowed rules (Axis 6)
LINEAGE_RELATION_PARENT_ALLOWED_MAP: Dict[str, bool] = {
    "DIRECT_GENEALOGY": True,
    "PROVISIONAL": True,
    "MUTATION_TRANSFORM": True,
    "CONCEPT_PREREQUISITE": True,
    "PARAMETER_SHIFT_ANALOGY": False,
    "STRUCTURAL_ANALOGY": False,
    "REJECTED_RELATION": False,
}


class JudgeExecutionStatus:
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_RUN = "NOT_RUN"
    ERROR = "ERROR"


@dataclass
class JudgeResult:
    """Result returned by an individual Quality Judge."""
    judge_name: str
    passed: bool
    score: float  # 0.0 to 1.0
    is_vetoed: bool
    execution_status: str = JudgeExecutionStatus.PASS
    reason: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "judge_name": self.judge_name,
            "passed": self.passed,
            "score": self.score,
            "is_vetoed": self.is_vetoed,
            "execution_status": self.execution_status,
            "reason": self.reason,
            "details": self.details,
        }


@dataclass
class QualityPlaneResult:
    """Aggregate result from QualityPlaneEvaluator."""
    status: str  # "VERIFIED", "VETOED", "PROVISIONAL"
    is_vetoed: bool
    overall_confidence: float
    judge_results: Dict[str, JudgeResult]
    veto_reasons: List[str]
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "is_vetoed": self.is_vetoed,
            "overall_confidence": round(self.overall_confidence, 4),
            "judge_results": {k: v.to_dict() for k, v in self.judge_results.items()},
            "veto_reasons": self.veto_reasons,
            "details": self.details,
        }


def _get_axis_data(item: Dict[str, Any], axis_key: str) -> Dict[str, Any]:
    """Helper to extract axis data dictionary safely from item dict."""
    axes = item.get("axes", {})
    if not isinstance(axes, dict):
        return {}
    ax_val = axes.get(axis_key, {})
    if isinstance(ax_val, str):
        try:
            return json.loads(ax_val)
        except Exception:
            return {}
    if isinstance(ax_val, dict):
        return ax_val
    return {}


# ---------------------------------------------------------------------------
# 1. ParsingJudge
# ---------------------------------------------------------------------------
class ParsingJudge:
    """Checks losslessness of LaTeX content, score, and asset URLs."""

    def evaluate(self, item: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> JudgeResult:
        name = "ParsingJudge"

        if "latex_content" in item:
            latex = item.get("latex_content")
            if not latex or not isinstance(latex, str) or not latex.strip():
                return JudgeResult(
                    judge_name=name,
                    passed=False,
                    score=0.0,
                    is_vetoed=True,
                    reason="Missing or empty latex_content",
                )

            # LaTeX brace matching check
            open_braces = latex.count("{") - latex.count(r"\{")
            close_braces = latex.count("}") - latex.count(r"\}")
            if open_braces != close_braces:
                return JudgeResult(
                    judge_name=name,
                    passed=False,
                    score=0.4,
                    is_vetoed=True,
                    reason=f"Mismatched LaTeX curly braces: {open_braces} open vs {close_braces} close",
                )

            # Check asset image URL if explicitly required
            axis2 = _get_axis_data(item, "Axis_2")
            asset_url = item.get("asset_image_url")
            image_required = axis2.get("image_required") is True or "[그림]" in latex or "\\includegraphics" in latex
            if image_required and (not asset_url or not isinstance(asset_url, str) or not asset_url.strip()):
                return JudgeResult(
                    judge_name=name,
                    passed=False,
                    score=0.5,
                    is_vetoed=True,
                    reason="Question references or requires image, but asset_image_url is missing or empty",
                )

        if "score" in item and item.get("score") is not None:
            score_val = item.get("score")
            try:
                num_score = float(score_val)
                if num_score <= 0:
                    return JudgeResult(
                        judge_name=name,
                        passed=False,
                        score=0.0,
                        is_vetoed=True,
                        reason=f"Non-positive score value: {score_val}",
                    )
            except (ValueError, TypeError):
                return JudgeResult(
                    judge_name=name,
                    passed=False,
                    score=0.0,
                    is_vetoed=True,
                    reason=f"Invalid score format: {score_val}",
                )

        # Check Axis 2 raw parsing status if Axis 2 is present
        axes = item.get("axes", {})
        if isinstance(axes, dict) and "Axis_2" in axes:
            axis2 = _get_axis_data(item, "Axis_2")
            if axis2.get("raw_parsing_error") is True or axis2.get("latex_integrity") == "CORRUPTED":
                return JudgeResult(
                    judge_name=name,
                    passed=False,
                    score=0.0,
                    is_vetoed=True,
                    reason="Axis 2 raw parsing error or corrupted LaTeX integrity detected",
                    details=axis2,
                )

        return JudgeResult(
            judge_name=name,
            passed=True,
            score=1.0,
            is_vetoed=False,
            details={"latex_checked": "latex_content" in item, "score_checked": "score" in item},
        )


# ---------------------------------------------------------------------------
# 2. MathEquivalenceJudge
# ---------------------------------------------------------------------------
class MathEquivalenceJudge:
    """Checks logical derivation and root multiplicity in Axis 3 symbolic modeling."""

    def evaluate(self, item: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> JudgeResult:
        name = "MathEquivalenceJudge"
        axes = item.get("axes", {})
        if not isinstance(axes, dict) or ("Axis_3" not in axes and not (context and "axis3" in context)):
            return JudgeResult(
                judge_name=name,
                passed=True,
                score=1.0,
                is_vetoed=False,
                reason="Axis 3 not evaluated in this payload",
            )

        axis3 = _get_axis_data(item, "Axis_3")
        if context and "axis3" in context:
            axis3.update(context["axis3"])

        # Check root multiplicity
        rm_check = axis3.get("root_multiplicity_check")
        if rm_check is False or rm_check in ("FAIL", "MISMATCH"):
            return JudgeResult(
                judge_name=name,
                passed=False,
                score=0.0,
                is_vetoed=True,
                reason="Root multiplicity check failed (e.g. double vs triple root mismatch)",
                details=axis3,
            )

        if axis3.get("root_multiplicity_mismatch") is True:
            return JudgeResult(
                judge_name=name,
                passed=False,
                score=0.0,
                is_vetoed=True,
                reason="Explicit root_multiplicity_mismatch flag set in Axis 3",
            )

        # Check logical derivation contradiction
        log_deriv = axis3.get("logical_derivation")
        if log_deriv is False or log_deriv == "CONTRADICTION" or axis3.get("derivation_valid") is False:
            return JudgeResult(
                judge_name=name,
                passed=False,
                score=0.0,
                is_vetoed=True,
                reason="Logical derivation contradiction detected in symbolic modeling",
            )

        # Check equivalence verification status
        if axis3.get("equivalence_verified") is False:
            return JudgeResult(
                judge_name=name,
                passed=False,
                score=0.0,
                is_vetoed=True,
                reason="Symbolic equivalence verification failed in Axis 3",
            )

        return JudgeResult(
            judge_name=name,
            passed=True,
            score=1.0,
            is_vetoed=False,
            details=axis3,
        )


# ---------------------------------------------------------------------------
# 3. IndependentSolverJudge
# ---------------------------------------------------------------------------
class IndependentSolverJudge:
    """Checks independent solution derivation output against ground truth answer."""

    def evaluate(self, item: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> JudgeResult:
        name = "IndependentSolverJudge"
        ground_truth = item.get("answer")

        # 1. Check if solved_answer is explicitly provided in context, item, Axis_3, or Axis_5
        solved_answer = None
        if context and "solved_answer" in context:
            solved_answer = context["solved_answer"]
        elif "solved_answer" in item:
            solved_answer = item["solved_answer"]
        else:
            axis3 = _get_axis_data(item, "Axis_3")
            solved_answer = axis3.get("solved_answer") or axis3.get("independent_solution", {}).get("answer")
            if solved_answer is None:
                axis5 = _get_axis_data(item, "Axis_5")
                solved_answer = axis5.get("solved_answer")

        if solved_answer is not None and ground_truth is not None and ground_truth != 0:
            is_match = _compare_numeric_values(solved_answer, ground_truth)
            if is_match:
                return JudgeResult(
                    judge_name=name,
                    passed=True,
                    score=1.0,
                    is_vetoed=False,
                    execution_status=JudgeExecutionStatus.PASS,
                    details={"solved_answer": solved_answer, "ground_truth": ground_truth},
                )
            else:
                return JudgeResult(
                    judge_name=name,
                    passed=False,
                    score=0.0,
                    is_vetoed=True,
                    execution_status=JudgeExecutionStatus.FAIL,
                    reason=f"Independent solver answer ({solved_answer}) conflicts with ground truth answer ({ground_truth})",
                    details={"solved_answer": solved_answer, "ground_truth": ground_truth},
                )

        # 2. Dynamic independent solver engine invocation
        if item.get("latex_content"):
            from pipeline.query_engine.independent_solver import IndependentSolverEngine
            solver = IndependentSolverEngine()
            res = solver.solve_item(item)
            if res.get("execution_status") == "PASS":
                return JudgeResult(
                    judge_name=name,
                    passed=True,
                    score=1.0,
                    is_vetoed=False,
                    execution_status=JudgeExecutionStatus.PASS,
                    details=res,
                )
            elif res.get("execution_status") == "FAIL":
                return JudgeResult(
                    judge_name=name,
                    passed=False,
                    score=0.0,
                    is_vetoed=True,
                    execution_status=JudgeExecutionStatus.FAIL,
                    reason=f"Independent solver answer ({res.get('solved_answer')}) conflicts with ground truth ({ground_truth})",
                    details=res,
                )
            elif res.get("execution_status") == "ERROR":
                return JudgeResult(
                    judge_name=name,
                    passed=False,
                    score=0.0,
                    is_vetoed=True,
                    execution_status=JudgeExecutionStatus.ERROR,
                    reason=res.get("reason", "Solver execution error"),
                    details=res,
                )

        # 3. Mandatory fail-closed NOT_RUN status (Codex Review §3, §4.2, Section 7.1)
        return JudgeResult(
            judge_name=name,
            passed=False,
            score=0.0,
            is_vetoed=False,
            execution_status=JudgeExecutionStatus.NOT_RUN,
            reason="Independent solver execution was NOT run for this item",
            details={"solved_answer": solved_answer, "ground_truth": ground_truth},
        )


# ---------------------------------------------------------------------------
# 4. DistractorReplayJudge
# ---------------------------------------------------------------------------
class DistractorReplayJudge:
    """Checks DistractorReplayEngine Veto status across options."""

    def __init__(self, float_tolerance: float = 1e-6):
        self.replay_engine = DistractorReplayEngine(float_tolerance=float_tolerance)

    def evaluate(self, item: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> JudgeResult:
        name = "DistractorReplayJudge"
        axes = item.get("axes", {})
        axis5 = _get_axis_data(item, "Axis_5") if isinstance(axes, dict) and "Axis_5" in axes else {}

        # Check existing Axis 5 verification status
        audit_trail = axis5.get("audit_trail", {})
        if audit_trail.get("verification_status") == "FAIL" or axis5.get("distractor_vetoed") is True:
            return JudgeResult(
                judge_name=name,
                passed=False,
                score=0.0,
                is_vetoed=True,
                reason="Axis 5 distractor verification status is FAIL or distractor_vetoed is True",
                details=axis5,
            )

        # Collect distractor hypotheses
        hypotheses = None
        if context and "distractor_hypotheses" in context:
            hypotheses = context["distractor_hypotheses"]
        elif "distractor_hypotheses" in item:
            hypotheses = item["distractor_hypotheses"]
        elif "option_construction_matrix" in axis5:
            hypotheses = axis5["option_construction_matrix"]

        if hypotheses:
            results = self.replay_engine.verify_matrix(hypotheses)
            vetoed_results = [r for r in results if r.is_vetoed]
            if vetoed_results:
                first_veto = vetoed_results[0]
                return JudgeResult(
                    judge_name=name,
                    passed=False,
                    score=0.0,
                    is_vetoed=True,
                    reason=f"Distractor option {first_veto.option} replay Veto: {first_veto.veto_reason}",
                    details={"vetoed_options": [r.to_dict() for r in vetoed_results]},
                )

        return JudgeResult(
            judge_name=name,
            passed=True,
            score=1.0,
            is_vetoed=False,
            details={"axis5_status": audit_trail.get("verification_status", "PASS")},
        )


# ---------------------------------------------------------------------------
# 5. CurriculumJudge
# ---------------------------------------------------------------------------
class CurriculumJudge:
    """Checks achievement standard and curriculum unit mapping in Axis 1."""

    def evaluate(self, item: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> JudgeResult:
        name = "CurriculumJudge"
        axes = item.get("axes", {})
        if not isinstance(axes, dict) or ("Axis_1" not in axes and not (context and "axis1" in context) and "routing_key" not in item):
            return JudgeResult(
                judge_name=name,
                passed=True,
                score=1.0,
                is_vetoed=False,
                reason="Axis 1 not evaluated in this payload",
            )

        axis1 = _get_axis_data(item, "Axis_1")
        if context and "axis1" in context:
            axis1.update(context["axis1"])

        primary_unit = axis1.get("primary_unit")
        achievement_std = None
        topic_name = None
        if isinstance(primary_unit, dict):
            achievement_std = primary_unit.get("achievement_standard")
            topic_name = primary_unit.get("topic_name")

        achievement_std = achievement_std or axis1.get("achievement_standard")
        topic_name = topic_name or axis1.get("topic_name") or axis1.get("topic")
        routing_key = axis1.get("routing_key") or item.get("routing_key")

        if achievement_std == "UNKNOWN" or topic_name == "UNKNOWN":
            return JudgeResult(
                judge_name=name,
                passed=False,
                score=0.0,
                is_vetoed=True,
                reason="Curriculum mapping contains UNKNOWN achievement standard or topic",
            )

        return JudgeResult(
            judge_name=name,
            passed=True,
            score=1.0,
            is_vetoed=False,
            details={"primary_unit": primary_unit, "routing_key": routing_key},
        )


# ---------------------------------------------------------------------------
# 6. LineageJudge
# ---------------------------------------------------------------------------
class LineageJudge:
    """Checks precedent relationships against 7 closed relation Enums and genealogy_parent_allowed rule."""

    def evaluate(self, item: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> JudgeResult:
        name = "LineageJudge"
        axes = item.get("axes", {})
        if not isinstance(axes, dict) or ("Axis_6" not in axes and not (context and "axis6" in context) and not (context and "historical_precedents" in context)):
            return JudgeResult(
                judge_name=name,
                passed=True,
                score=1.0,
                is_vetoed=False,
                reason="Axis 6 not evaluated in this payload",
            )

        axis6 = _get_axis_data(item, "Axis_6")
        if context and "axis6" in context:
            axis6.update(context["axis6"])

        precedents = []
        if isinstance(axis6.get("historical_precedents"), list):
            precedents.extend(axis6["historical_precedents"])
        elif isinstance(axis6.get("precedent_item_ids"), list):
            precedents.extend(axis6["precedent_item_ids"])

        if context and "historical_precedents" in context:
            precedents.extend(context["historical_precedents"])

        for prec in precedents:
            if not isinstance(prec, dict):
                continue

            rel_type = prec.get("relationship_type")
            parent_allowed = prec.get("genealogy_parent_allowed")

            if not rel_type:
                continue

            if rel_type not in LINEAGE_RELATION_PARENT_ALLOWED_MAP:
                return JudgeResult(
                    judge_name=name,
                    passed=False,
                    score=0.0,
                    is_vetoed=True,
                    reason=f"Invalid lineage relation enum '{rel_type}'. Must be one of {list(LINEAGE_RELATION_PARENT_ALLOWED_MAP.keys())}",
                    details={"precedent": prec},
                )

            expected_parent_allowed = LINEAGE_RELATION_PARENT_ALLOWED_MAP[rel_type]

            if parent_allowed is not None:
                bool_parent_allowed = bool(parent_allowed)
                if bool_parent_allowed != expected_parent_allowed:
                    return JudgeResult(
                        judge_name=name,
                        passed=False,
                        score=0.0,
                        is_vetoed=True,
                        reason=f"Lineage rule violation: relationship_type '{rel_type}' requires genealogy_parent_allowed={expected_parent_allowed}, but got {bool_parent_allowed}",
                        details={"precedent": prec, "expected": expected_parent_allowed, "got": bool_parent_allowed},
                    )

        return JudgeResult(
            judge_name=name,
            passed=True,
            score=1.0,
            is_vetoed=False,
            details={"precedents_evaluated": len(precedents)},
        )


# ---------------------------------------------------------------------------
# 7. InstructorJudge
# ---------------------------------------------------------------------------
class InstructorJudge:
    """Checks standard_solution, shortcut_solution, shortcut_prerequisites, shortcut_traps completeness."""

    def evaluate(self, item: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> JudgeResult:
        name = "InstructorJudge"
        axis4 = _get_axis_data(item, "Axis_4")
        ctx_solution = (context or {}).get("instructor_solution", {})

        std_sol = (
            item.get("standard_solution")
            or item.get("solution")
            or ctx_solution.get("standard_solution")
            or axis4.get("standard_solution")
        )

        shortcut_suggs = axis4.get("shortcut_solving_suggestions", [])
        if isinstance(shortcut_suggs, list) and shortcut_suggs:
            first_sugg = shortcut_suggs[0] if isinstance(shortcut_suggs[0], dict) else {}
        else:
            first_sugg = {}

        shortcut_sol = (
            item.get("shortcut_solution")
            or ctx_solution.get("shortcut_solution")
            or first_sugg.get("shortcut_formula")
            or first_sugg.get("rule_name")
        )
        shortcut_prereqs = (
            item.get("shortcut_prerequisites")
            or ctx_solution.get("shortcut_prerequisites")
            or first_sugg.get("shortcut_prerequisites")
        )
        shortcut_traps = (
            item.get("shortcut_traps")
            or ctx_solution.get("shortcut_traps")
            or first_sugg.get("shortcut_traps")
        )

        # Hard Veto if standard_solution is explicitly provided as empty
        if ("standard_solution" in item or "solution" in item or (context and "instructor_solution" in context)) and (not std_sol or (isinstance(std_sol, str) and not std_sol.strip())):
            return JudgeResult(
                judge_name=name,
                passed=False,
                score=0.0,
                is_vetoed=True,
                reason="Missing required standard_solution",
            )

        # Compute completeness score across 4 fields
        present_count = 0
        if std_sol:
            present_count += 1
        if shortcut_sol:
            present_count += 1
        if shortcut_prereqs:
            present_count += 1
        if shortcut_traps:
            present_count += 1

        score = present_count / 4.0 if present_count > 0 else 0.8

        return JudgeResult(
            judge_name=name,
            passed=True,
            score=max(score, 0.8) if std_sol else 0.8,
            is_vetoed=False,
            details={
                "standard_solution_present": bool(std_sol),
                "shortcut_solution_present": bool(shortcut_sol),
                "shortcut_prerequisites_present": bool(shortcut_prereqs),
                "shortcut_traps_present": bool(shortcut_traps),
                "completeness_score": score,
            },
        )


# ---------------------------------------------------------------------------
# 8. AdversarialJudge
# ---------------------------------------------------------------------------
class AdversarialJudge:
    """Checks counterexamples and high confidence false claims."""

    def evaluate(self, item: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> JudgeResult:
        name = "AdversarialJudge"
        axis5 = _get_axis_data(item, "Axis_5")
        adv = (context or {}).get("adversarial") or item.get("adversarial") or axis5.get("adversarial") or {}

        if adv.get("counterexample_found") is True or axis5.get("counterexample_found") is True:
            return JudgeResult(
                judge_name=name,
                passed=False,
                score=0.0,
                is_vetoed=True,
                reason="Adversarial evaluation found a counterexample disproving item reasoning",
                details=adv,
            )

        if adv.get("false_claim_detected") is True or adv.get("high_confidence_false_claim") is True:
            return JudgeResult(
                judge_name=name,
                passed=False,
                score=0.0,
                is_vetoed=True,
                reason="High confidence false claim or hallucinated theorem detected",
                details=adv,
            )

        if adv.get("adversarial_attack_passed") is False:
            return JudgeResult(
                judge_name=name,
                passed=False,
                score=0.0,
                is_vetoed=True,
                reason="Adversarial attack robustness check failed",
                details=adv,
            )

        return JudgeResult(
            judge_name=name,
            passed=True,
            score=1.0,
            is_vetoed=False,
            details=adv,
        )


# ---------------------------------------------------------------------------
# 9. HoldoutJudge
# ---------------------------------------------------------------------------
class HoldoutJudge:
    """Checks unseen holdout item generalization status."""

    def evaluate(self, item: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> JudgeResult:
        name = "HoldoutJudge"
        axis7 = _get_axis_data(item, "Axis_7")
        holdout = (context or {}).get("holdout") or item.get("holdout") or axis7.get("holdout") or {}

        if holdout.get("holdout_verified") is False or axis7.get("holdout_verified") is False:
            return JudgeResult(
                judge_name=name,
                passed=False,
                score=0.0,
                is_vetoed=True,
                reason="Unseen holdout generalization test failed",
                details=holdout,
            )

        gen_score = holdout.get("generalization_score") or axis7.get("generalization_score")
        if gen_score is not None:
            try:
                score_val = float(gen_score)
                if score_val < 0.70:
                    return JudgeResult(
                        judge_name=name,
                        passed=False,
                        score=score_val,
                        is_vetoed=True,
                        reason=f"Holdout generalization score ({score_val:.2f}) below 0.70 threshold",
                        details=holdout,
                    )
            except (ValueError, TypeError):
                pass

        return JudgeResult(
            judge_name=name,
            passed=True,
            score=1.0,
            is_vetoed=False,
            details=holdout,
        )


# ---------------------------------------------------------------------------
# QualityPlaneEvaluator
# ---------------------------------------------------------------------------
class QualityPlaneEvaluator:
    """
    Aggregates all 9 Independent Judges, computes weighted confidence, and applies Veto gates.
    """

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        self.judges = [
            ParsingJudge(),
            MathEquivalenceJudge(),
            IndependentSolverJudge(),
            DistractorReplayJudge(),
            CurriculumJudge(),
            LineageJudge(),
            InstructorJudge(),
            AdversarialJudge(),
            HoldoutJudge(),
        ]
        
        # Default equal weights if not specified
        default_weight = 1.0 / len(self.judges)
        self.weights: Dict[str, float] = {}
        for judge in self.judges:
            j_name = judge.__class__.__name__
            self.weights[j_name] = weights.get(j_name, default_weight) if weights else default_weight

    def evaluate(self, item: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> QualityPlaneResult:
        """
        Evaluate item against all 9 Independent Judges.
        """
        judge_results: Dict[str, JudgeResult] = {}
        veto_reasons: List[str] = []
        weighted_score_sum = 0.0
        total_weight = 0.0

        for judge in self.judges:
            j_name = judge.__class__.__name__
            res = judge.evaluate(item, context=context)
            judge_results[j_name] = res

            w = self.weights.get(j_name, 1.0 / len(self.judges))
            weighted_score_sum += res.score * w
            total_weight += w

            if res.is_vetoed:
                reason_str = f"[{j_name}] {res.reason or 'Veto triggered'}"
                veto_reasons.append(reason_str)

        overall_confidence = weighted_score_sum / total_weight if total_weight > 0 else 0.0

        solver_res = judge_results.get("IndependentSolverJudge")
        solver_passed = solver_res and solver_res.execution_status == JudgeExecutionStatus.PASS

        if veto_reasons:
            status = "VETOED"
            is_vetoed = True
        elif not solver_passed:
            status = "SEMANTIC_PROOF_PENDING"
            is_vetoed = False
        elif overall_confidence < 0.90:
            status = "PROVISIONAL"
            is_vetoed = False
        else:
            status = "VERIFIED"
            is_vetoed = False

        return QualityPlaneResult(
            status=status,
            is_vetoed=is_vetoed,
            overall_confidence=overall_confidence,
            judge_results=judge_results,
            veto_reasons=veto_reasons,
        )
