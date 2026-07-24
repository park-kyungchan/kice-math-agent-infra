import os
import sqlite3
import json
from typing import Dict, List, Any, Optional

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

        return data

    def get_questions_batch(self, item_ids: List[str], axes: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        if not item_ids:
            return []

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

    def get_question(self, item_id: str, axes: Optional[List[str]] = None) -> Dict[str, Any]:
        res = self.get_questions_batch([item_id], axes=axes)
        if res:
            return res[0]
        return {'item_id': item_id, 'error': f'Item {item_id} not found', 'axes': {}}

    def get_by_routing_key(self, routing_key: str, axes: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        idx = self._load_routing_index()
        info = idx.get(routing_key, {})
        sample_items = info.get('sample_items', [])
        return self.get_questions_batch(sample_items, axes=axes)

    def get_by_keyword(self, keyword: str, axes: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        idx = self._load_routing_index()
        matched_items = []
        for r_key, info in idx.items():
            if keyword in info.get('keyword', '') or keyword in info.get('unit', ''):
                matched_items.extend(info.get('sample_items', []))
        return self.get_questions_batch(matched_items, axes=axes)

    def get_by_concept_id(self, concept_id: str, axes: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        cmap = self._load_concept_map()
        matched_concept = None
        for concept in cmap.get("concepts", []):
            if concept.get("concept_id") == concept_id:
                matched_concept = concept
                break
        if not matched_concept:
            return []
        # Return all questions matching concept patterns if tagged in routing index
        return self.get_by_keyword(matched_concept.get("concept_name_english", ""), axes=axes)

    def clear_cache(self) -> None:
        self._question_cache.clear()
        self._routing_index_cache = None
        self._concept_map_cache = None

if __name__ == '__main__':
    fetcher = QuestionFetcher()
    res = fetcher.get_question('202411_MATH_DIF_22', axes=['Axis_1', 'Axis_2', 'Axis_3', 'Axis_4', 'Axis_5', 'Axis_6', 'Axis_7', 'Axis_8'])
    print('Refactored 8-Axis Fetcher Test:', res['item_id'], 'Score:', res['score'], 'Answer:', res.get('answer'), 'Axes Fetched:', list(res['axes'].keys()))
