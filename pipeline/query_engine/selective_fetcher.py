import os
import sqlite3
import json
from typing import Dict, List, Any, Optional, TypedDict, Literal

class ClaimProvenance(TypedDict):
    claim_type: Literal['FACT', 'INFERENCE', 'ESTIMATE', 'OPINION']
    source: Literal['ORIGINAL_EXAM_TEXT', 'SYMPY_SOLVER', 'AGENT_REASONING', 'TEACHER_INPUT']
    confidence_score: float
    counter_evidence: List[str]
    human_verified: bool


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
    if qp_result.is_vetoed or qp_result.status != "VERIFIED":
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
            'review_history_json': row['review_history_json'] if 'review_history_json' in row.keys() else '[]',
            'latex_content': row['latex_content'],
            'asset_image_url': row['asset_image_url'],
            'axes': {}
        }
        
        # 8 Flat Column Axes Mapping
        raw_axes = {
            'Axis_1': row['axis1_curriculum'] if 'axis1_curriculum' in row.keys() else None,
            'Axis_2': row['axis2_raw_parsing'] if 'axis2_raw_parsing' in row.keys() else None,
            'Axis_3': row['axis3_symbolic_modeling'] if 'axis3_symbolic_modeling' in row.keys() else None,
            'Axis_4': row['axis4_contextual_tree'] if 'axis4_contextual_tree' in row.keys() else None,
            'Axis_5': row['axis5_traps_verification'] if 'axis5_traps_verification' in row.keys() else None,
            'Axis_6': row['axis6_genealogy'] if 'axis6_genealogy' in row.keys() else None,
            'Axis_7': row['axis7_mutation'] if 'axis7_mutation' in row.keys() else None,
            'Axis_8': row['axis8_knowledge_graph'] if 'axis8_knowledge_graph' in row.keys() else None,
        }
        
        for ax_key, raw_val in raw_axes.items():
            if raw_val:
                try:
                    data['axes'][ax_key] = json.loads(raw_val)
                except Exception:
                    data['axes'][ax_key] = raw_val

            # Integrate ClaimProvenance into Axis 3, 5, 6
            if ax_key in ('Axis_3', 'Axis_5', 'Axis_6'):
                if ax_key not in data['axes'] or not isinstance(data['axes'].get(ax_key), dict):
                    if ax_key in data['axes'] and isinstance(data['axes'][ax_key], str):
                        # if it's somehow a string, wrap it or ignore
                        pass
                    else:
                        data['axes'][ax_key] = data['axes'].get(ax_key, {})
                if isinstance(data['axes'].get(ax_key), dict):
                    if 'provenance' not in data['axes'][ax_key]:
                        data['axes'][ax_key]['provenance'] = []

        return data

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
                for i in range(0, len(missing_ids), CHUNK_SIZE):
                    chunk = missing_ids[i:i + CHUNK_SIZE]
                    placeholders = ','.join(['?'] * len(chunk))
                    sql = f'''
                        SELECT 
                            q.item_id, q.exam_id, q.track, q.item_number, q.score, q.answer, q.correct_rate,
                            q.review_status, q.reviewer_id, q.review_history_json,
                            q.latex_content, q.asset_image_url,
                            a.axis1_curriculum, a.axis2_raw_parsing, a.axis3_symbolic_modeling,
                            a.axis4_contextual_tree, a.axis5_traps_verification, a.axis6_genealogy,
                            a.axis7_mutation, a.axis8_knowledge_graph
                        FROM question_item q
                        LEFT JOIN axis_analysis a ON q.item_id = a.item_id
                        WHERE q.item_id IN ({placeholders})
                    '''
                    cur.execute(sql, chunk)
                    rows = cur.fetchall()
                    for row in rows:
                        item_dict = self._format_question_row(row)
                        self._question_cache[item_dict['item_id']] = item_dict

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

