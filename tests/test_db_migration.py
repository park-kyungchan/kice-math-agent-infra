import os
import sqlite3
import unittest

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DB_PATH = os.path.join(BASE_DIR, 'storage', 'parsed_dataset.db')

class TestDBMigration(unittest.TestCase):
    def setUp(self):
        self.assertTrue(os.path.exists(DB_PATH), "Database file storage/parsed_dataset.db does not exist")
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.execute("PRAGMA foreign_keys = ON;")

    def tearDown(self):
        self.conn.close()

    def test_pragma_integrity_and_fk_check(self):
        cur = self.conn.cursor()
        cur.execute("PRAGMA integrity_check;")
        integrity = cur.fetchone()[0]
        self.assertEqual(integrity, "ok", "DB integrity check failed")

        cur.execute("PRAGMA foreign_key_check;")
        fk_errors = cur.fetchall()
        self.assertEqual(len(fk_errors), 0, f"Foreign key check errors found: {fk_errors}")

    def test_question_item_columns(self):
        cur = self.conn.cursor()
        cur.execute("PRAGMA table_info(question_item);")
        columns = [row[1] for row in cur.fetchall()]
        self.assertIn("answer", columns, "Column 'answer' missing in question_item")
        self.assertIn("correct_rate", columns, "Column 'correct_rate' missing in question_item")

    def test_axis_analysis_8flat_columns(self):
        cur = self.conn.cursor()
        cur.execute("PRAGMA table_info(axis_analysis);")
        columns = [row[1] for row in cur.fetchall()]
        
        expected_columns = [
            'item_id', 'axis1_curriculum', 'axis2_raw_parsing',
            'axis3_symbolic_modeling', 'axis4_contextual_tree',
            'axis5_traps_verification', 'axis6_genealogy',
            'axis7_mutation', 'axis8_knowledge_graph'
        ]
        
        for col in expected_columns:
            self.assertIn(col, columns, f"Column '{col}' missing in axis_analysis")

    def test_row_counts_preserved(self):
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM question_item;")
        q_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM axis_analysis;")
        a_count = cur.fetchone()[0]

        self.assertEqual(q_count, 1350, f"Question item count mismatch: {q_count} != 1350")
        self.assertEqual(a_count, 1350, f"Axis analysis count mismatch: {a_count} != 1350")

if __name__ == '__main__':
    unittest.main()
