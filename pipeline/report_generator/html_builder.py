#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Automated Zero-Data-Loss HTML Report Generator (html_builder.py)
Sample 09: Notion / Craft Clean Workspace Theme with Dynamic Adaptive Layouts.
"""

import os
import sys
import io
import json
import html
import tempfile
from html.parser import HTMLParser
from typing import Dict, List, Any, Tuple, Set, Optional

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

class HTMLTextAndAttrExtractor(HTMLParser):
    """Parses HTML DOM to extract all text nodes, attribute values, and data-keys for verification."""
    def __init__(self):
        super().__init__()
        self.text_tokens: Set[str] = set()
        self.attr_values: Set[str] = set()
        self.data_keys: Set[str] = set()

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, str]]):
        for attr, val in attrs:
            if val:
                val_clean = html.unescape(val).strip()
                self.attr_values.add(val_clean)
                if attr.startswith('data-key') or attr in ('id', 'class'):
                    self.data_keys.add(val_clean)

    def handle_data(self, data: str):
        cleaned = html.unescape(data).strip()
        if cleaned:
            self.text_tokens.add(cleaned)
            for line in cleaned.splitlines():
                if line.strip():
                    self.text_tokens.add(line.strip())

def flatten_payload(data: Any, prefix: str = '') -> Tuple[List[Tuple[str, str]], List[Tuple[str, Any]]]:
    """Recursively flattens nested dict/list payload into (path, key_name) and (path, leaf_value)."""
    keys_list = []
    values_list = []

    if isinstance(data, dict):
        for k, v in data.items():
            current_path = f"{prefix}.{k}" if prefix else str(k)
            keys_list.append((current_path, str(k)))
            sub_keys, sub_vals = flatten_payload(v, current_path)
            keys_list.extend(sub_keys)
            values_list.extend(sub_vals)
    elif isinstance(data, list):
        for idx, item in enumerate(data):
            current_path = f"{prefix}[{idx}]"
            sub_keys, sub_vals = flatten_payload(item, current_path)
            keys_list.extend(sub_keys)
            values_list.extend(sub_vals)
    else:
        if data is not None:
            values_list.append((prefix, data))

    return keys_list, values_list

def validate_html_completeness(item_data: Dict[str, Any], html_content: str) -> Dict[str, Any]:
    """Validates 100% data preservation of 8-Axis payload inside rendered HTML."""
    extractor = HTMLTextAndAttrExtractor()
    extractor.feed(html_content)

    keys, values = flatten_payload(item_data)
    
    missing_keys: List[str] = []
    missing_values: List[Tuple[str, Any]] = []

    full_html_text = html.unescape(html_content)

    # 1. Validate Keys
    for path, key_name in keys:
        if key_name not in full_html_text and key_name not in extractor.data_keys:
            missing_keys.append(f"{path} (key: '{key_name}')")

    # 2. Validate Leaf Values
    for path, val in values:
        val_str = str(val).strip()
        if not val_str:
            continue
        
        found = False
        if val_str in extractor.text_tokens or val_str in extractor.attr_values or val_str in full_html_text:
            found = True
        elif isinstance(val, (int, float)):
            if str(val) in full_html_text or f"{val:.2f}" in full_html_text:
                found = True
        elif isinstance(val, bool):
            if str(val).lower() in full_html_text.lower():
                found = True

        if not found:
            missing_values.append((path, val))

    total_keys = len(keys)
    total_values = len(values)
    keys_found = total_keys - len(missing_keys)
    values_found = total_values - len(missing_values)

    total_items = total_keys + total_values
    completeness_score = ((keys_found + values_found) / total_items) * 100.0 if total_items > 0 else 100.0

    return {
        'is_complete': len(missing_keys) == 0 and len(missing_values) == 0,
        'completeness_score': round(completeness_score, 2),
        'total_keys': total_keys,
        'missing_keys_count': len(missing_keys),
        'missing_keys': missing_keys,
        'total_values': total_values,
        'missing_values_count': len(missing_values),
        'missing_values': missing_values
    }

def render_dynamic_tree(obj: Any, key_name: str = "", depth: int = 0) -> str:
    """Recursively generates semantic HTML for arbitrary nested JSON objects without missing keys."""
    if obj is None:
        return f'<span class="null-val" data-key="{key_name}">null</span>'

    if isinstance(obj, dict):
        if not obj:
            return f'<div class="empty-dict" data-key="{key_name}">(empty map)</div>'
        items_html = []
        for k, v in obj.items():
            child_html = render_dynamic_tree(v, key_name=str(k), depth=depth + 1)
            items_html.append(
                f'<div class="tree-node depth-{depth}">'
                f'<span class="tree-key" data-key="{html.escape(str(k))}">{html.escape(str(k))}:</span> '
                f'<div class="tree-value">{child_html}</div>'
                f'</div>'
            )
        return f'<div class="tree-dict" data-depth="{depth}">{"".join(items_html)}</div>'

    elif isinstance(obj, list):
        if not obj:
            return f'<span class="empty-list" data-key="{key_name}" data-count="0">(empty list)</span>'
        list_items = []
        for idx, elem in enumerate(obj):
            elem_html = render_dynamic_tree(elem, key_name=f"{key_name}[{idx}]", depth=depth + 1)
            list_items.append(f'<li data-index="{idx}">{elem_html}</li>')
        return f'<ol class="tree-list" data-key="{key_name}">{"".join(list_items)}</ol>'

    else:
        val_str = str(obj)
        escaped_val = html.escape(val_str)
        return f'<span class="tree-leaf" data-key="{key_name}">{escaped_val}</span>'

import base64

def convert_image_to_base64_data_uri(image_path: str) -> Optional[str]:
    """Converts a local PNG/JPEG image file to a self-contained Base64 Data URI."""
    if not image_path or not os.path.exists(image_path):
        return None
    try:
        with open(image_path, 'rb') as f:
            data = f.read()
        if not data:
            return None
        encoded = base64.b64encode(data).decode('utf-8')
        mime_type = 'image/png' if image_path.lower().endswith('.png') else 'image/jpeg'
        return f"data:{mime_type};base64,{encoded}"
    except Exception:
        return None

class DualTargetReportWriter:
    """Handles atomic dual-target writing of validated HTML reports."""

    def __init__(self, repo_storage_dir: Optional[str] = None, artifacts_dir: Optional[str] = None):
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        self.repo_dir = repo_storage_dir or os.path.join(base_dir, 'storage', 'html_reports')
        self.artifacts_dir = artifacts_dir or os.environ.get('SESSION_ARTIFACTS_DIR', '')

        os.makedirs(self.repo_dir, exist_ok=True)
        if self.artifacts_dir:
            os.makedirs(self.artifacts_dir, exist_ok=True)

    def _atomic_write(self, filepath: str, content: str) -> None:
        target_dir = os.path.dirname(filepath)
        os.makedirs(target_dir, exist_ok=True)
        with tempfile.NamedTemporaryFile('w', dir=target_dir, delete=False, encoding='utf-8') as tf:
            tf.write(content)
            temp_name = tf.name
        os.replace(temp_name, filepath)

    def save_report(self, item_id: str, item_data: Dict[str, Any], html_content: str, enforce_completeness: bool = True) -> Tuple[str, Optional[str]]:
        if enforce_completeness:
            val_result = validate_html_completeness(item_data, html_content)
            if not val_result['is_complete']:
                raise ValueError(
                    f"HTML completeness validation failed for item {item_id} (Score: {val_result['completeness_score']}%).\n"
                    f"Missing keys: {val_result['missing_keys']}\n"
                    f"Missing values: {val_result['missing_values']}"
                )

        filename = f"{item_id}_report.html"
        repo_path = os.path.join(self.repo_dir, filename)
        self._atomic_write(repo_path, html_content)

        artifact_path = None
        if self.artifacts_dir:
            artifact_path = os.path.join(self.artifacts_dir, filename)
            self._atomic_write(artifact_path, html_content)

        return repo_path, artifact_path

class HTMLReportBuilder:
    """
    Sample 09: Notion / Craft Workspace Aesthetic with Dynamic Adaptive Placement Engine.
    Dynamically adjusts layout based on item asset presence, subject track, and reasoning depth.
    """

    def __init__(self, writer: Optional[DualTargetReportWriter] = None):
        self.writer = writer or DualTargetReportWriter()

    def build_report(self, item_data: Dict[str, Any], save: bool = True, enforce_completeness: bool = True) -> str:
        item_id = item_data.get('item_id', 'UNKNOWN_ITEM')
        exam_id = item_data.get('exam_id', '')
        track = item_data.get('track', '')
        item_number = item_data.get('item_number', 0)
        score = item_data.get('score', 0)
        answer = item_data.get('answer', 0)
        correct_rate = item_data.get('correct_rate')
        latex_content = item_data.get('latex_content', '')
        asset_image_url = item_data.get('asset_image_url', '')
        axes = item_data.get('axes', {})

        # Dynamic Layout Engine Construction
        dynamic_axes_tree = render_dynamic_tree(axes, key_name="axes")

        # Process Asset Image (Base64 Data URI for 100% Guaranteed Browser Rendering)
        img_src = convert_image_to_base64_data_uri(asset_image_url) if asset_image_url else None
        if not img_src and asset_image_url:
            img_src = f"file:///{asset_image_url.replace('\\', '/')}"
        has_asset = bool(img_src)

        # Dynamic Question Header & Split Layout
        if has_asset:
            question_block = f"""
            <div class="notion-split-grid" data-key="asset_image_url" data-asset-url="{html.escape(str(asset_image_url))}">
                <div class="notion-card">
                    <div class="card-label">📷 원본 평가원 자산 이미지</div>
                    <img src="{img_src}" data-asset-url="{html.escape(str(asset_image_url))}" alt="Diagram Asset" style="max-width:100%; border-radius:6px; border:1px solid #e3e3e1;">
                </div>
                <div class="notion-card" data-key="latex_content">
                    <div class="card-label">📝 KaTeX 파싱 명제 원문</div>
                    <div class="math-box">{html.escape(latex_content)}</div>
                </div>
            </div>
            """
        else:
            question_block = f"""
            <div class="notion-card full-width" data-key="latex_content">
                <div class="card-label">📝 KaTeX 파싱 명제 원문</div>
                <div class="math-box">{html.escape(latex_content)}</div>
            </div>
            """

        # Dynamic Choice Options Block
        choices_html = ""
        for i in range(1, 6):
            is_correct = (i == answer)
            cls = "choice-tag correct" if is_correct else "choice-tag"
            choices_html += f'<span class="{cls}">{"①②③④⑤"[i-1]} Choice {i} {"(Correct)" if is_correct else ""}</span> '

        html_doc = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(item_id)} Notion Workspace Master Analysis Report</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Noto+Sans+KR:wght@400;500;700;900&family=Fira+Code:wght@400;600&display=swap" rel="stylesheet">
    <script>
        window.MathJax = {{
            tex: {{
                inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
                displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']]
            }},
            svg: {{ fontCache: 'global' }}
        }};
    </script>
    <script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"></script>
    <style>
        :root {{
            --bg-notion: #ffffff;
            --text-notion: #37352f;
            --text-muted: #787774;
            --bg-callout: #f1f1ef;
            --border-notion: #e3e3e1;
            --accent-red: #eb5757;
            --accent-blue: #2eaadc;
            --accent-green: #0f7b6c;
            --accent-purple: #9065b0;
            --accent-amber: #d9730d;
        }}

        @media (prefers-color-scheme: dark) {{
            :root {{
                --bg-notion: #191919;
                --text-notion: #d4d4d4;
                --text-muted: #9b9b9b;
                --bg-callout: #252525;
                --border-notion: #2f2f2f;
                --accent-red: #ff6b6b;
                --accent-blue: #52c41a;
                --accent-green: #20c997;
                --accent-purple: #b197fc;
                --accent-amber: #ffd43b;
            }}
        }}

        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background: var(--bg-notion);
            color: var(--text-notion);
            font-family: 'Inter', 'Noto Sans KR', sans-serif;
            padding: 3rem 1.5rem;
            max-width: 960px;
            margin: 0 auto;
            line-height: 1.7;
        }}

        .notion-header {{
            margin-bottom: 2rem;
            border-bottom: 1px solid var(--border-notion);
            padding-bottom: 1.5rem;
        }}

        .notion-icon {{ font-size: 3.5rem; margin-bottom: 0.5rem; display: inline-block; }}
        .notion-title {{ font-size: 2.4rem; font-weight: 800; color: var(--text-notion); letter-spacing: -0.02em; }}
        
        .pill-group {{ display: flex; gap: 0.5rem; flex-wrap: wrap; margin-top: 0.75rem; }}
        .pill {{
            font-size: 0.8rem;
            font-weight: 600;
            padding: 0.25rem 0.6rem;
            border-radius: 4px;
            background: rgba(135, 131, 120, 0.15);
            color: var(--text-notion);
        }}
        .pill-green {{ background: rgba(15, 123, 108, 0.15); color: var(--accent-green); font-weight: 700; }}

        .notion-callout {{
            background: var(--bg-callout);
            border: 1px solid var(--border-notion);
            border-radius: 6px;
            padding: 1.25rem;
            display: flex;
            gap: 1rem;
            margin: 1.5rem 0;
        }}

        .notion-split-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1.25rem;
            margin: 1.5rem 0;
        }}

        @media (max-width: 768px) {{
            .notion-split-grid {{ grid-template-columns: 1fr; }}
        }}

        .notion-card {{
            background: var(--bg-callout);
            border: 1px solid var(--border-notion);
            border-radius: 8px;
            padding: 1.25rem;
        }}

        .card-label {{ font-size: 0.8rem; font-weight: 700; color: var(--text-muted); margin-bottom: 0.75rem; text-transform: uppercase; }}

        .math-box {{
            font-size: 1.05rem;
            line-height: 1.6;
        }}

        .choice-tag {{
            display: inline-block;
            padding: 0.3rem 0.6rem;
            border-radius: 4px;
            border: 1px solid var(--border-notion);
            font-size: 0.85rem;
            margin-right: 0.4rem;
            margin-top: 0.4rem;
        }}

        .choice-tag.correct {{
            background: rgba(15, 123, 108, 0.15);
            border-color: var(--accent-green);
            color: var(--accent-green);
            font-weight: 700;
        }}

        details {{ margin: 1rem 0; border: 1px solid var(--border-notion); border-radius: 6px; padding: 0.75rem 1rem; background: var(--bg-callout); }}
        details summary {{ cursor: pointer; font-weight: 700; color: var(--text-notion); font-size: 0.95rem; }}

        .tree-node {{ margin-left: 0.75rem; border-left: 1px solid var(--border-notion); padding-left: 0.75rem; margin-top: 0.35rem; }}
        .tree-key {{ font-weight: 700; color: var(--accent-blue); font-family: 'Fira Code', monospace; font-size: 0.85rem; }}
        .tree-leaf {{ color: var(--text-notion); font-size: 0.85rem; word-break: break-all; }}
    </style>
</head>
<body>

    <!-- Header -->
    <header class="notion-header">
        <div class="notion-icon">📐</div>
        <div class="notion-title" data-key="item_id">{html.escape(str(item_id))}</div>
        <div class="pill-group">
            <span class="pill" data-key="exam_id">Exam: {html.escape(str(exam_id))}</span>
            <span class="pill" data-key="track">Track: {html.escape(str(track))}</span>
            <span class="pill" data-key="item_number">Item #{item_number}</span>
            <span class="pill" data-key="score">{score} Points</span>
            <span class="pill pill-green" data-key="correct_rate">Correct Rate: {correct_rate if correct_rate is not None else 'N/A'}</span>
        </div>
    </header>

    <!-- Callout Executive Summary -->
    <div class="notion-callout">
        <span style="font-size: 1.5rem;">💡</span>
        <div>
            <strong>CSAT 8-Axis Analysis Summary:</strong>
            <p style="font-size: 0.95rem; margin-top: 0.25rem;">
                문항 <code>{html.escape(str(item_id))}</code>에 대한 Master 8-Axis 수식 추론 및 데이터 무누락 검증 완료.
            </p>
        </div>
    </div>

    <!-- Dynamic Question & Asset Placement Block -->
    <h3 style="font-size: 1.2rem; font-weight: 700; margin-top: 2rem;">📌 1. 문항 원문 및 조건 (Dynamic Layout)</h3>
    {question_block}

    <div class="notion-card" style="margin-top: 1rem;">
        <div class="card-label">🎯 정답 선택지 & Answer Mapping</div>
        <div>{choices_html}</div>
        <div style="font-weight:700; color:var(--accent-green); margin-top:0.5rem;" data-key="answer">Confirmed Answer Choice: Choice {answer}</div>
    </div>

    <!-- 8-Axis Structured Section Explorers -->
    <section data-key="axes">
        <h3 style="font-size: 1.2rem; font-weight: 700; margin-top: 2rem;">⚡ 2. Master 8-Axis Multi-Dimensional Analysis</h3>

    <details open data-key="Axis_1">
        <summary>📘 Axis 1: Curriculum & Integration</summary>
        <div class="tree-node">{render_dynamic_tree(axes.get('Axis_1', {}), key_name="Axis_1")}</div>
    </details>

    <details open data-key="Axis_2">
        <summary>📝 Axis 2: Raw Parsing & Normalization</summary>
        <div class="tree-node">{render_dynamic_tree(axes.get('Axis_2', {}), key_name="Axis_2")}</div>
    </details>

    <details open data-key="Axis_3">
        <summary>📐 Axis 3: Symbolic Modeling & Solution</summary>
        <div class="tree-node">{render_dynamic_tree(axes.get('Axis_3', {}), key_name="Axis_3")}</div>
    </details>

    <details open data-key="Axis_4">
        <summary>🌳 Axis 4: Contextual Tree & Backtrack Telemetry</summary>
        <div class="tree-node">{render_dynamic_tree(axes.get('Axis_4', {}), key_name="Axis_4")}</div>
    </details>

    <details open data-key="Axis_5">
        <summary>⚠️ Axis 5: Traps & Verification Protocol</summary>
        <div class="tree-node">{render_dynamic_tree(axes.get('Axis_5', {}), key_name="Axis_5")}</div>
    </details>

    <details open data-key="Axis_6">
        <summary>🧬 Axis 6: Core Idea Genealogy & Precedents</summary>
        <div class="tree-node">{render_dynamic_tree(axes.get('Axis_6', {}), key_name="Axis_6")}</div>
    </details>

    <details open data-key="Axis_7">
        <summary>🔄 Axis 7: Condition Representation Mutation</summary>
        <div class="tree-node">{render_dynamic_tree(axes.get('Axis_7', {}), key_name="Axis_7")}</div>
    </details>

    <details open data-key="Axis_8">
        <summary>🌐 Axis 8: Knowledge Graph Topology</summary>
        <div class="tree-node">{render_dynamic_tree(axes.get('Axis_8', {}), key_name="Axis_8")}</div>
    </details>

    <!-- Fallback Explorer for 100% Zero-Data-Loss Verification -->
    <details style="margin-top: 2rem;">
        <summary>📁 Full 8-Axis Schema Explorer (100% Key/Value Preserved)</summary>
        <div style="margin-top: 1rem;">
            {dynamic_axes_tree}
        </div>
    </details>
    </section>

</body>
</html>"""

        if save:
            self.writer.save_report(item_id, item_data, html_doc, enforce_completeness=enforce_completeness)

        return html_doc
