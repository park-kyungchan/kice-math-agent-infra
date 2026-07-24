#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Deterministic LaTeX Condition & Target Extractor (condition_parser.py)
Rule-based parser for extracting (가), (나) conditions, target expressions,
and choices from CSAT math items with 0 LLM token cost.
"""

import re
import html
from typing import Dict, List, Any

def parse_item_conditions_deterministic(latex_str: str) -> Dict[str, Any]:
    """
    Deterministically parses LaTeX question text into structured conditions,
    target expression, and options with 0 LLM token consumption.
    """
    if not latex_str:
        return {"intro": "", "conditions": [], "target_expr": "", "choices": []}

    text = latex_str.replace('\r\n', '\n').strip()
    
    # Extract choices [CHOICE_1] ... [CHOICE_5]
    choices = []
    choice_matches = re.findall(r'\[CHOICE_([1-5])\]\s*(.*?)(?=\[CHOICE_|\n|$)', text)
    for num, val in choice_matches:
        choices.append({"number": int(num), "value": val.strip()})

    # Remove choice blocks for clean text parsing
    clean_text = re.sub(r'\[CHOICE_[1-5]\].*?$', '', text, flags=re.MULTILINE).strip()

    # Extract conditions (가), (나), (다)
    cond_matches = re.findall(r'(\([가-하]\))\s*(.*?)(?=\([가-하]\)|$|\n\s*f\(|\n\s*g\(|\n\s*h\()', clean_text, flags=re.DOTALL)
    conditions = []
    for label, body in cond_matches:
        conditions.append({
            "label": label.strip(),
            "body": body.strip()
        })

    # Extract target expression (e.g. f(6)의 값은?)
    target_match = re.search(r'([fgh]\([0-9a-zA-Z가-힣\s\+\-\*\/,]+\)\s*의\s*값은\?.*$)', clean_text)
    target_expr = target_match.group(1).strip() if target_match else ""

    # Extract intro sentence
    intro = clean_text
    if conditions:
        first_cond = conditions[0]["label"]
        intro = clean_text.split(first_cond)[0].strip()

    return {
        "intro": intro,
        "conditions": conditions,
        "target_expr": target_expr,
        "choices": choices
    }

if __name__ == "__main__":
    sample = "15. 삼차함수 f(x)가 (가) int_0^3 f(x) dx = 0 (나) f(2) = -1 을 만족할 때 f(6)의 값은? [4점]"
    parsed = parse_item_conditions_deterministic(sample)
    print(parsed)
