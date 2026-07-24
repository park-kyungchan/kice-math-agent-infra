#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Deterministic Math Replay & SymPy Solver Engine (distractor_replay_engine.py)

Phase 1B Implementation for v2.7.0:
- Evaluates student error programs (stepwise algebraic transformations, calculation mistakes)
  against target distractor values in multiple-choice options.
- Verifies whether an error program deterministically reproduces option_value.
- Veto logic: If replayed_result != option_value (or execution fails), marks hypothesis as VETOED (is_vetoed=True).
"""

import time
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union, Callable
import sympy as sp


@dataclass
class DistractorHypothesis:
    """
    Represents a student error hypothesis for a multiple-choice distractor option.
    """
    option: int
    option_value: Union[int, float, str, sp.Expr]
    error_code: str = "DIST_UNKNOWN"
    cause: str = ""
    error_program: Optional[Union[str, Dict[str, Any], Callable[[], Any]]] = None
    is_simulated_hypothesis: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReplayResult:
    """
    Result of evaluating an error program against a distractor hypothesis.
    """
    option: int
    option_value: Any
    replayed_result: Any
    is_vetoed: bool
    replay_status: str  # "VERIFIED", "VETOED", "EXECUTION_ERROR"
    error_code: str = ""
    cause: str = ""
    veto_reason: Optional[str] = None
    execution_time_ms: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "option": self.option,
            "option_value": self.option_value,
            "replayed_result": self.replayed_result,
            "is_vetoed": self.is_vetoed,
            "replay_status": self.replay_status,
            "error_code": self.error_code,
            "cause": self.cause,
            "veto_reason": self.veto_reason,
            "execution_time_ms": self.execution_time_ms,
            "details": self.details,
        }


def _compare_numeric_values(val1: Any, val2: Any, rel_tol: float = 1e-6, abs_tol: float = 1e-6) -> bool:
    """
    Compare two values numerically or symbolically for equivalence.
    """
    if val1 is None or val2 is None:
        return val1 == val2

    # Try SymPy simplification equality
    try:
        sp_val1 = sp.sympify(val1)
        sp_val2 = sp.sympify(val2)
        if sp.simplify(sp_val1 - sp_val2) == 0:
            return True
    except Exception:
        pass

    # Try float numeric comparison
    try:
        f1 = float(val1)
        f2 = float(val2)
        return math.isclose(f1, f2, rel_tol=rel_tol, abs_tol=abs_tol)
    except (ValueError, TypeError):
        pass

    # Fallback to string representation / equality
    return str(val1).strip() == str(val2).strip()


class DistractorReplayEngine:
    """
    SymPy & Python Replay Engine for verifying distractor error programs.
    """

    def __init__(self, float_tolerance: float = 1e-6):
        self.float_tolerance = float_tolerance

    def execute_sympy_expression(self, expr_str: str, symbols_map: Optional[Dict[str, Any]] = None) -> Any:
        """
        Evaluate a SymPy expression given a mapping of symbol names to values.
        """
        symbols_map = symbols_map or {}
        subs_dict = {}
        for sym_name, sym_val in symbols_map.items():
            sym = sp.Symbol(sym_name) if isinstance(sym_name, str) else sym_name
            subs_dict[sym] = sp.sympify(sym_val)

        parsed_expr = sp.sympify(expr_str)
        evaluated = parsed_expr.subs(subs_dict)
        
        # Simplify if possible
        simplified = sp.simplify(evaluated)
        
        if simplified.is_number:
            if simplified.is_integer:
                return int(simplified)
            try:
                return float(simplified) if not isinstance(simplified, sp.Rational) else float(simplified)
            except Exception:
                return simplified
        return simplified

    def execute_step_sequence(self, steps: List[Dict[str, Any]], return_var: Optional[str] = None) -> Any:
        """
        Execute a sequence of assignment steps.
        Each step: {"var": "var_name", "expr": "expression_string"}
        """
        context: Dict[str, Any] = {}
        last_var = None

        for step in steps:
            var_name = step.get("var")
            expr = step.get("expr")
            if not expr:
                continue

            val = self.execute_sympy_expression(str(expr), context)
            if var_name:
                context[var_name] = val
                last_var = var_name

        target_var = return_var or last_var
        if target_var and target_var in context:
            return context[target_var]
        
        return list(context.values())[-1] if context else None

    def execute_python_expr(self, expr_str: str, context: Optional[Dict[str, Any]] = None) -> Any:
        """
        Safely evaluate a Python mathematical expression.
        """
        math_namespace = {
            "math": math,
            "sp": sp,
            "abs": abs,
            "round": round,
            "min": min,
            "max": max,
            "pow": pow,
            "sum": sum,
        }
        if context:
            math_namespace.update(context)

        return eval(expr_str, {"__builtins__": {}}, math_namespace)

    def execute_error_program(self, error_program: Union[str, Dict[str, Any], Callable[[], Any]]) -> Any:
        """
        Dispatch and execute an error program according to its format.
        """
        if callable(error_program):
            return error_program()

        if isinstance(error_program, str):
            try:
                return self.execute_sympy_expression(error_program)
            except Exception:
                return self.execute_python_expr(error_program)

        if isinstance(error_program, dict):
            prog_type = error_program.get("type", "sympy")
            if prog_type in ("sympy", "sympy_expression"):
                expr = error_program["expression"]
                symbols = error_program.get("symbols", {})
                return self.execute_sympy_expression(expr, symbols)

            elif prog_type in ("step_sequence", "steps"):
                steps = error_program.get("steps", [])
                return_var = error_program.get("return_var")
                return self.execute_step_sequence(steps, return_var)

            elif prog_type == "python_expr":
                expr = error_program["expression"]
                context = error_program.get("context", {})
                return self.execute_python_expr(expr, context)

            elif prog_type in ("function", "callable"):
                func = error_program["func"]
                return func()

            else:
                raise ValueError(f"Unsupported error program type: '{prog_type}'")

        raise TypeError(f"Invalid error_program type: {type(error_program)}")

    def verify_hypothesis(self, hypothesis: Union[DistractorHypothesis, Dict[str, Any]]) -> ReplayResult:
        """
        Replay an error program and check against option_value.
        Sets is_vetoed = True if replayed_result != option_value.
        """
        start_time = time.perf_counter()

        if isinstance(hypothesis, dict):
            hyp_obj = DistractorHypothesis(
                option=hypothesis.get("option", 0),
                option_value=hypothesis.get("option_value", hypothesis.get("value", None)),
                error_code=hypothesis.get("error_code", "DIST_UNKNOWN"),
                cause=hypothesis.get("cause", ""),
                error_program=hypothesis.get("error_program", hypothesis.get("program", None)),
                is_simulated_hypothesis=hypothesis.get("is_simulated_hypothesis", False),
                metadata=hypothesis.get("metadata", {})
            )
        else:
            hyp_obj = hypothesis

        option = hyp_obj.option
        option_value = hyp_obj.option_value

        if hyp_obj.error_program is None:
            exec_time = (time.perf_counter() - start_time) * 1000.0
            return ReplayResult(
                option=option,
                option_value=option_value,
                replayed_result=None,
                is_vetoed=True,
                replay_status="EXECUTION_ERROR",
                error_code=hyp_obj.error_code,
                cause=hyp_obj.cause,
                veto_reason="Missing error_program specification",
                execution_time_ms=exec_time,
            )

        try:
            replayed_result = self.execute_error_program(hyp_obj.error_program)
        except Exception as e:
            exec_time = (time.perf_counter() - start_time) * 1000.0
            return ReplayResult(
                option=option,
                option_value=option_value,
                replayed_result=None,
                is_vetoed=True,
                replay_status="EXECUTION_ERROR",
                error_code=hyp_obj.error_code,
                cause=hyp_obj.cause,
                veto_reason=f"Error program execution raised exception: {str(e)}",
                execution_time_ms=exec_time,
            )

        # Verification check: replayed_result == option_value
        is_match = _compare_numeric_values(replayed_result, option_value, abs_tol=self.float_tolerance)
        exec_time = (time.perf_counter() - start_time) * 1000.0

        if is_match:
            return ReplayResult(
                option=option,
                option_value=option_value,
                replayed_result=replayed_result,
                is_vetoed=False,
                replay_status="VERIFIED",
                error_code=hyp_obj.error_code,
                cause=hyp_obj.cause,
                veto_reason=None,
                execution_time_ms=exec_time,
            )
        else:
            return ReplayResult(
                option=option,
                option_value=option_value,
                replayed_result=replayed_result,
                is_vetoed=True,
                replay_status="VETOED",
                error_code=hyp_obj.error_code,
                cause=hyp_obj.cause,
                veto_reason=f"Replayed result ({replayed_result}) does not match option value ({option_value})",
                execution_time_ms=exec_time,
            )

    def verify_matrix(self, hypotheses: List[Union[DistractorHypothesis, Dict[str, Any]]]) -> List[ReplayResult]:
        """
        Verify a matrix of distractor hypotheses.
        """
        return [self.verify_hypothesis(hyp) for hyp in hypotheses]


def build_202606_math_dif_15_hypotheses() -> List[DistractorHypothesis]:
    """
    Construct distractor hypotheses for 202606_MATH_DIF_15 item:
    f(x) = a * x^2 * (x - 3), target = f(6).
    Correct: a = 1/4 -> f(6) = 27 (Option 4).
    Option 3: error in extrema ratio -> a = 2/9 -> f(6) = 24.
    """
    hypotheses = [
        DistractorHypothesis(
            option=1,
            option_value=18,
            error_code="DIST_CASE_SIGN",
            cause="a 계수 계산 시 f(2) = -2/3 착오 (a=1/6)",
            error_program={
                "type": "step_sequence",
                "steps": [
                    {"var": "a", "expr": "1/6"},
                    {"var": "f6", "expr": "a * 6**2 * (6 - 3)"}
                ],
                "return_var": "f6"
            }
        ),
        DistractorHypothesis(
            option=2,
            option_value=21,
            error_code="DIST_INTEGRAL_BOUND",
            cause="구간 길이 계산 오류 (a=7/36)",
            error_program={
                "type": "step_sequence",
                "steps": [
                    {"var": "a", "expr": "7/36"},
                    {"var": "f6", "expr": "a * 6**2 * (6 - 3)"}
                ],
                "return_var": "f6"
            }
        ),
        DistractorHypothesis(
            option=3,
            option_value=24,
            error_code="DIST_CALC_ERROR",
            cause="x=2 극소점 비율관계 오류 (a=2/9 착오)",
            error_program={
                "type": "step_sequence",
                "steps": [
                    {"var": "a", "expr": "2/9"},
                    {"var": "f6", "expr": "a * 6**2 * (6 - 3)"}
                ],
                "return_var": "f6"
            }
        ),
        DistractorHypothesis(
            option=4,
            option_value=27,
            error_code="NONE",
            cause="정답 (f(x) = 1/4 * x^2 * (x-3), f(6)=27)",
            error_program={
                "type": "step_sequence",
                "steps": [
                    {"var": "a", "expr": "1/4"},
                    {"var": "f6", "expr": "a * 6**2 * (6 - 3)"}
                ],
                "return_var": "f6"
            }
        ),
        DistractorHypothesis(
            option=5,
            option_value=30,
            error_code="DIST_SMOOTH_TRIPLE_ROOT",
            cause="삼중근 개형 오적용 (a=5/18)",
            error_program={
                "type": "step_sequence",
                "steps": [
                    {"var": "a", "expr": "5/18"},
                    {"var": "f6", "expr": "a * 6**2 * (6 - 3)"}
                ],
                "return_var": "f6"
            }
        ),
    ]
    return hypotheses
