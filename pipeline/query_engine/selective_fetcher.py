import os
import sqlite3
import json

class QuestionFetcher:
    def __init__(self, db_path=None):
        if db_path is None:
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
            db_path = os.path.join(base_dir, 'storage', 'parsed_dataset.db')
        self.db_path = db_path
        self.routing_index_path = os.path.join(os.path.dirname(__file__), 'routing_index.json')

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute('PRAGMA foreign_keys = ON;')
        return conn

    def get_question(self, item_id: str, axes: list = None) -> dict:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute('SELECT item_id, exam_id, track, item_number, score, latex_content, asset_image_url FROM question_item WHERE item_id = ?', (item_id,))
            row = cur.fetchone()
            if not row:
                return {'item_id': item_id, 'error': f'Item {item_id} not found', 'axes': {}}
                
            data = {
                'item_id': row[0],
                'exam_id': row[1],
                'track': row[2],
                'item_number': row[3],
                'score': row[4],
                'latex_content': row[5],
                'asset_image_url': row[6],
                'axes': {}
            }
            
            cur.execute('SELECT kice_objective, condition_parsing, practical_heuristics, distractor_patterns, macro_lineage FROM axis_analysis WHERE item_id = ?', (item_id,))
            axis_row = cur.fetchone()
            if axis_row:
                axis_map = {
                    'Axis_1': axis_row[0],     # Concept Routing
                    'Axis_2': axis_row[1],     # Condition Parsing
                    'Axis_3': axis_row[3],     # Misconception & Trap
                    'Axis_4A': axis_row[4],    # Core Idea Lineage
                    'Axis_4B': axis_row[2],    # Condition Mutation
                }
                target_axes = axes if axes else axis_map.keys()
                for ax in target_axes:
                    if ax in axis_map and axis_map[ax]:
                        try:
                            data['axes'][ax] = json.loads(axis_map[ax])
                        except Exception:
                            data['axes'][ax] = axis_map[ax]
                            
            return data

    def get_by_routing_key(self, routing_key: str) -> list:
        if not os.path.exists(self.routing_index_path):
            return []
        with open(self.routing_index_path, 'r', encoding='utf-8') as f:
            idx = json.load(f)
        info = idx.get(routing_key, {})
        sample_items = info.get('sample_items', [])
        return [self.get_question(item_id) for item_id in sample_items]

    def get_by_keyword(self, keyword: str) -> list:
        if not os.path.exists(self.routing_index_path):
            return []
        with open(self.routing_index_path, 'r', encoding='utf-8') as f:
            idx = json.load(f)
        matched_items = []
        for r_key, info in idx.items():
            if keyword in info.get('keyword', '') or keyword in info.get('unit', ''):
                matched_items.extend(info.get('sample_items', []))
        return [self.get_question(item_id) for item_id in matched_items]

if __name__ == '__main__':
    fetcher = QuestionFetcher()
    res = fetcher.get_question('202411_MATH_DIF_22', axes=['Axis_1', 'Axis_2', 'Axis_3', 'Axis_4A', 'Axis_4B'])
    print('Fixed Fetcher Test:', res['item_id'], 'Score:', res['score'], 'Axes Fetched:', list(res['axes'].keys()))
