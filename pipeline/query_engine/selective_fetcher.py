import os
import sqlite3
import json
from typing import Dict, List, Any, Optional

# NOTE (v2.8.1): the former in-file `ClaimProvenance` TypedDict was dead code —
# a type alias that nothing wrote or validated. Claim-level provenance is now
# PERSISTED per claim in the `claim_provenance` table and served by
# pipeline/query_engine/claim_provenance.py. This fetcher attaches only claims
# that actually exist; it never synthesizes empty provenance (P0-4 fix).
from pipeline.query_engine.claim_provenance import get_claims_for_items

# Single source of axis identity (I2 axis-agnostic storage refactor): the
# legacy 'Axis_1'..'Axis_8' dict-key convention this fetcher's public API
# exposes maps to axis_analysis columns / analysis_derivation axis_key
# values via pipeline/query_engine/axis_registry.py, not a hand-written
# dict here. axis_analysis itself may be a real table or (post-migration) a
# read-only compatibility VIEW over the generic analysis_derivation table --
# a plain SELECT cannot tell the difference, so this fetcher's SQL is
# unaffected either way.
from pipeline.query_engine.axis_registry import AXIS_COLUMN_BY_DICT_KEY


LAYER_MAPPING = {
    'data_infrastructure': ['Axis_1', 'Axis_2'],
    'item_reasoning': ['Axis_3', 'Axis_4', 'Axis_5'],
    'corpus_lineage': ['Axis_6', 'Axis_7', 'Axis_8'],
    'layer_1': ['Axis_1', 'Axis_2'],
    'layer_2': ['Axis_3', 'Axis_4', 'Axis_5'],
    'layer_3': ['Axis_6', 'Axis_7', 'Axis_8'],
    '1': ['Axis_1', 'Axis_2'],
    '2': ['Axis_3', 'Axis_4', 'Axis_5'],
    '3': ['Axis_6', 'Axis_7', 'Axis_8'],
}

from pipeline.query_engine.quality_plane_judges import QualityPlaneEvaluator, QualityPlaneResult

def _is_item_unverified(item: Dict[str, Any]) -> bool:
    """
    Evaluates whether an item is unverified by checking multi-axis flags and Quality Plane judges:
    - Axis_3 / Axis_5 review_required or confidence_score < 0.85
    - Lineage relation validity (Axis_6 7 closed relation enums and genealogy_parent_allowed rule)
    - Distractor Replay Veto status (Axis_5 option verification)
    - Quality Plane Evaluator overall Veto gate status
    """
    axes = item.get('axes', {})
    if not isinstance(axes, dict):
        return True

    # 1. Direct Axis_3 / Axis_5 review_required & confidence checks
    for ax_name in ('Axis_3', 'Axis_5'):
        ax_data = axes.get(ax_name)
        if isinstance(ax_data, str):
            try:
                ax_data = json.loads(ax_data)
            except Exception:
                ax_data = None
        if not isinstance(ax_data, dict):
            continue

        req = ax_data.get('review_required')
        if req is True or (isinstance(req, str) and req.lower() == 'true') or req == 1:
            return True

        conf = ax_data.get('confidence_score')
        if conf is not None:
            try:
                if float(conf) < 0.85:
                    return True
            except (ValueError, TypeError):
                pass

    # 2. Quality Plane Evaluator multi-axis Veto and confidence check
    evaluator = QualityPlaneEvaluator()
    qp_result = evaluator.evaluate(item)
    if qp_result.is_vetoed or qp_result.status == "VETOED":
        return True

    return False


class QuestionFetcher:
    def __init__(self, db_path: Optional[str] = None, 
                 routing_index_path: Optional[str] = None,
                 concept_map_path: Optional[str] = None):
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        
        self.db_path = db_path or os.path.join(base_dir, 'storage', 'parsed_dataset.db')
        self.routing_index_path = routing_index_path or os.path.join(os.path.dirname(__file__), 'routing_index.json')
        self.concept_map_path = concept_map_path or os.path.join(base_dir, 'storage', 'kice_math_concept_map.json')
        
        # In-Memory Caches
        self._question_cache: Dict[str, Dict[str, Any]] = {}
        self._routing_index_cache: Optional[Dict[str, Any]] = None
        self._concept_map_cache: Optional[Dict[str, Any]] = None

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute('PRAGMA foreign_keys = ON;')
        conn.row_factory = sqlite3.Row
        return conn

    def _load_routing_index(self) -> Dict[str, Any]:
        if self._routing_index_cache is None:
            if os.path.exists(self.routing_index_path):
                with open(self.routing_index_path, 'r', encoding='utf-8') as f:
                    self._routing_index_cache = json.load(f)
            else:
                self._routing_index_cache = {}
        return self._routing_index_cache

    def _load_concept_map(self) -> Dict[str, Any]:
        if self._concept_map_cache is None:
            if os.path.exists(self.concept_map_path):
                with open(self.concept_map_path, 'r', encoding='utf-8') as f:
                    self._concept_map_cache = json.load(f)
            else:
                self._concept_map_cache = {"concepts": []}
        return self._concept_map_cache

    def _format_question_row(self, row: sqlite3.Row) -> Dict[str, Any]:
        data = {
            'item_id': row['item_id'],
            'exam_id': row['exam_id'],
            'track': row['track'],
            'item_number': row['item_number'],
            'score': row['score'],
            'answer': row['answer'] if 'answer' in row.keys() else 0,
            'correct_rate': row['correct_rate'] if 'correct_rate' in row.keys() else None,
            'review_status': row['review_status'] if 'review_status' in row.keys() else 'AUTO_ANALYSIS_COMPLETED',
            'reviewer_id': row['reviewer_id'] if 'reviewer_id' in row.keys() else None,
            'review_version': row['review_version'] if 'review_version' in row.keys() else 0,
            'review_history_json': row['review_history_json'] if 'review_history_json' in row.keys() else '[]',
            'latex_content': row['latex_content'],
            'asset_image_url': row['asset_image_url'],
            'axes': {}
        }
        
        # Axis mapping, resolved through the axis registry (single source of
        # axis identity) rather than a hand-written 8-entry dict.
        row_keys = row.keys()
        raw_axes = {
            dict_key: (row[column] if column in row_keys else None)
            for dict_key, column in AXIS_COLUMN_BY_DICT_KEY.items()
        }
        
        for ax_key, raw_val in raw_axes.items():
            if raw_val:
                try:
                    data['axes'][ax_key] = json.loads(raw_val)
                except Exception:
                    data['axes'][ax_key] = raw_val

        # P0-4 invariant: an axis with no stored analysis stays ABSENT from
        # data['axes']. Provenance is attached later (batch) from the
        # claim_provenance table — real records only, never synthesized.
        return data

    def _attach_claim_provenance(self, conn: sqlite3.Connection, items: List[Dict[str, Any]]) -> None:
        """Attach persisted claim-level provenance to freshly formatted items.
        Claims are exposed at item['claim_provenance'][axis] and, when the
        corresponding axis analysis dict is present, mirrored at
        item['axes'][axis]['provenance']. Absent axes are never created."""
        try:
            claims_by_item = get_claims_for_items(conn, [it['item_id'] for it in items])
        except sqlite3.Error:
            claims_by_item = {}
        for item in items:
            item_claims = claims_by_item.get(item['item_id'])
            if not item_claims:
                continue
            item['claim_provenance'] = item_claims
            for axis, claims in item_claims.items():
                ax_data = item['axes'].get(axis)
                if isinstance(ax_data, dict):
                    ax_data['provenance'] = claims

    def get_questions_batch(self, item_ids: List[str], layer: Optional[str] = None, axes: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        if not item_ids:
            return []

        if axes is None and layer is not None:
            axes = LAYER_MAPPING.get(layer.lower())

        # Deduplicate preserving order
        unique_ids = list(dict.fromkeys(item_ids))
        
        # Check cache hits and misses
        missing_ids = [i_id for i_id in unique_ids if i_id not in self._question_cache]
        
        if missing_ids:
            CHUNK_SIZE = 500
            with self.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("PRAGMA table_info(question_item)")
                q_cols = [r[1] for r in cur.fetchall()]
                version_col = "q.review_version," if 'review_version' in q_cols else ""
                fresh_items: List[Dict[str, Any]] = []
                for i in range(0, len(missing_ids), CHUNK_SIZE):
                    chunk = missing_ids[i:i + CHUNK_SIZE]
                    placeholders = ','.join(['?'] * len(chunk))
                    # axis_analysis columns, resolved through the registry
                    # (axis1..axis8 order preserved -- see axis_registry.py).
                    axis_col_list = ', '.join(f'a.{col}' for col in AXIS_COLUMN_BY_DICT_KEY.values())
                    sql = f'''
                        SELECT
                            q.item_id, q.exam_id, q.track, q.item_number, q.score, q.answer, q.correct_rate,
                            q.review_status, q.reviewer_id, q.review_history_json, {version_col}
                            q.latex_content, q.asset_image_url,
                            {axis_col_list}
                        FROM question_item q
                        LEFT JOIN axis_analysis a ON q.item_id = a.item_id
                        WHERE q.item_id IN ({placeholders})
                    '''
                    cur.execute(sql, chunk)
                    rows = cur.fetchall()
                    for row in rows:
                        item_dict = self._format_question_row(row)
                        fresh_items.append(item_dict)
                        self._question_cache[item_dict['item_id']] = item_dict
                # Attach persisted claim-level provenance (real records only)
                self._attach_claim_provenance(conn, fresh_items)

        # Collect and apply optional axis filtering in memory
        results = []
        for i_id in unique_ids:
            item = self._question_cache.get(i_id)
            if item:
                if axes is not None:
                    filtered_item = item.copy()
                    filtered_item['axes'] = {k: v for k, v in item['axes'].items() if k in axes}
                    results.append(filtered_item)
                else:
                    results.append(item)
                    
        return results

    def get_question(self, item_id: str, layer: Optional[str] = None, axes: Optional[List[str]] = None) -> Dict[str, Any]:
        res = self.get_questions_batch([item_id], layer=layer, axes=axes)
        if res:
            return res[0]
        return {'item_id': item_id, 'error': f'Item {item_id} not found', 'axes': {}}

    def get_question_lineage(self, item_id: str, visited: Optional[set] = None) -> Dict[str, Any]:
        if visited is None:
            visited = set()

        if item_id in visited:
            return {'item_id': item_id, 'cyclic_reference': True}
        visited.add(item_id)

        item_data = self.get_question(item_id)
        if 'error' in item_data:
            return {'item_id': item_id, 'error': item_data['error']}

        axis6 = item_data.get('axes', {}).get('Axis_6', {})
        if isinstance(axis6, str):
            try:
                axis6 = json.loads(axis6)
            except Exception:
                axis6 = {}

        precedent_ids = []
        if isinstance(axis6, dict):
            p_ids = axis6.get('precedent_item_ids')
            if isinstance(p_ids, list):
                for p in p_ids:
                    if isinstance(p, str):
                        precedent_ids.append(p)
                    elif isinstance(p, dict) and 'precedent_item_id' in p:
                        precedent_ids.append(str(p['precedent_item_id']))
            elif isinstance(p_ids, str):
                precedent_ids.append(p_ids)

            h_precedents = axis6.get('historical_precedents')
            if isinstance(h_precedents, list):
                for hp in h_precedents:
                    if isinstance(hp, str):
                        precedent_ids.append(hp)
                    elif isinstance(hp, dict):
                        pid = hp.get('precedent_item_id') or hp.get('item_id')
                        if pid:
                            precedent_ids.append(str(pid))

            direct_pid = axis6.get('precedent_item_id')
            if isinstance(direct_pid, str):
                precedent_ids.append(direct_pid)

        unique_precedents = []
        for pid in precedent_ids:
            if pid and pid not in unique_precedents and pid != item_id:
                unique_precedents.append(pid)

        precedents_lineage = []
        for pid in unique_precedents:
            if pid not in visited:
                sub_tree = self.get_question_lineage(pid, visited=visited)
                if sub_tree:
                    precedents_lineage.append(sub_tree)

        return {
            'item_id': item_id,
            'item': item_data,
            'precedents': precedents_lineage
        }

    def get_unverified_questions(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT item_id FROM question_item")
            rows = cur.fetchall()
            all_item_ids = [r[0] for r in rows]

        all_items = self.get_questions_batch(all_item_ids)
        return [item for item in all_items if _is_item_unverified(item)]

    def get_by_routing_key(self, routing_key: str, layer: Optional[str] = None, axes: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        idx = self._load_routing_index()
        info = idx.get(routing_key, {})
        sample_items = info.get('sample_items', [])
        return self.get_questions_batch(sample_items, layer=layer, axes=axes)

    def get_by_keyword(self, keyword: str, layer: Optional[str] = None, axes: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        idx = self._load_routing_index()
        matched_items = []
        for r_key, info in idx.items():
            if keyword in info.get('keyword', '') or keyword in info.get('unit', ''):
                matched_items.extend(info.get('sample_items', []))
        return self.get_questions_batch(matched_items, layer=layer, axes=axes)

    def get_by_concept_id(self, concept_id: str, layer: Optional[str] = None, axes: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        cmap = self._load_concept_map()
        matched_concept = None
        for concept in cmap.get("concepts", []):
            if concept.get("concept_id") == concept_id:
                matched_concept = concept
                break
        if not matched_concept:
            return []
        return self.get_by_keyword(matched_concept.get("concept_name_english", ""), layer=layer, axes=axes)

    def evaluate_quality_plane(self, item_id: str, context: Optional[Dict[str, Any]] = None) -> QualityPlaneResult:
        item = self.get_question(item_id)
        evaluator = QualityPlaneEvaluator()
        return evaluator.evaluate(item, context=context)

    def clear_cache(self) -> None:
        self._question_cache.clear()
        self._routing_index_cache = None
        self._concept_map_cache = None


if __name__ == '__main__':
    fetcher = QuestionFetcher()
    res = fetcher.get_question('202411_MATH_DIF_22', axes=['Axis_1', 'Axis_2', 'Axis_3', 'Axis_4', 'Axis_5', 'Axis_6', 'Axis_7', 'Axis_8'])
    print('Refactored 8-Axis Fetcher Test:', res['item_id'], 'Score:', res['score'], 'Answer:', res.get('answer'), 'Axes Fetched:', list(res['axes'].keys()))

