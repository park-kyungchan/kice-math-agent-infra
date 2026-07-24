import os
import shutil
import sqlite3
import json
from datetime import datetime

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
STORAGE_DIR = os.path.join(BASE_DIR, 'storage')
DB_PATH = os.path.join(STORAGE_DIR, 'parsed_dataset.db')
BACKUP_PATH = os.path.join(STORAGE_DIR, 'parsed_dataset_backup.db')

def create_physical_backup():
    if os.path.exists(DB_PATH):
        shutil.copy2(DB_PATH, BACKUP_PATH)
        print(f"[Phase 0] Backup created: {BACKUP_PATH}")
    else:
        raise FileNotFoundError(f"Database not found at {DB_PATH}")

def run_migration():
    print(f"[Phase 1] Starting SQLite DB Migration for 8-Axis Schema...")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF;")
    cur = conn.cursor()

    try:
        cur.execute("BEGIN TRANSACTION;")

        # 1. Update question_item: Add answer & correct_rate if missing
        cur.execute("PRAGMA table_info(question_item);")
        columns = [row[1] for row in cur.fetchall()]
        
        if 'answer' not in columns:
            cur.execute("ALTER TABLE question_item ADD COLUMN answer INTEGER DEFAULT 0;")
            print("  - Added 'answer' column to question_item")
        if 'correct_rate' not in columns:
            cur.execute("ALTER TABLE question_item ADD COLUMN correct_rate REAL;")
            print("  - Added 'correct_rate' column to question_item")
        if 'review_status' not in columns:
            cur.execute("ALTER TABLE question_item ADD COLUMN review_status TEXT DEFAULT 'AUTO_ANALYSIS_COMPLETED';")
            print("  - Added 'review_status' column to question_item")
        if 'reviewer_id' not in columns:
            cur.execute("ALTER TABLE question_item ADD COLUMN reviewer_id TEXT DEFAULT NULL;")
            print("  - Added 'reviewer_id' column to question_item")
        if 'review_history_json' not in columns:
            cur.execute("ALTER TABLE question_item ADD COLUMN review_history_json TEXT DEFAULT '[]';")
            print("  - Added 'review_history_json' column to question_item")

        # 2. Refactor axis_analysis table to 8 flat columns using Table Recreation Pattern
        cur.execute("PRAGMA table_info(axis_analysis);")
        axis_columns = [row[1] for row in cur.fetchall()]
        
        if 'kice_objective' in axis_columns:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS axis_analysis_new (
                item_id TEXT PRIMARY KEY REFERENCES question_item(item_id) ON DELETE CASCADE,
                axis1_curriculum TEXT,
                axis2_raw_parsing TEXT,
                axis3_symbolic_modeling TEXT,
                axis4_contextual_tree TEXT,
                axis5_traps_verification TEXT,
                axis6_genealogy TEXT,
                axis7_mutation TEXT,
                axis8_knowledge_graph TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # Migrate legacy rows into new 8 flat columns
            cur.execute("SELECT item_id, kice_objective, condition_parsing, practical_heuristics, distractor_patterns, macro_lineage FROM axis_analysis;")
            legacy_rows = cur.fetchall()
            print(f"  - Migrating {len(legacy_rows)} rows from legacy axis_analysis...")

            for row in legacy_rows:
                item_id, kice_obj, cond_parse, prac_heur, dist_patt, macro_lin = row
                
                # Map legacy JSON blobs to 8 flat columns
                cur.execute("""
                INSERT OR REPLACE INTO axis_analysis_new (
                    item_id, axis1_curriculum, axis2_raw_parsing, axis3_symbolic_modeling,
                    axis4_contextual_tree, axis5_traps_verification, axis6_genealogy,
                    axis7_mutation, axis8_knowledge_graph
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    item_id,
                    kice_obj,    # axis1_curriculum
                    cond_parse,  # axis2_raw_parsing
                    prac_heur,   # axis3_symbolic_modeling
                    None,        # axis4_contextual_tree
                    dist_patt,   # axis5_traps_verification
                    macro_lin,   # axis6_genealogy
                    None,        # axis7_mutation
                    None         # axis8_knowledge_graph
                ))

            cur.execute("DROP TABLE axis_analysis;")
            cur.execute("ALTER TABLE axis_analysis_new RENAME TO axis_analysis;")
        else:
            print("  - axis_analysis is already migrated to 8 flat columns.")

        # Create Indexes
        cur.execute("CREATE INDEX IF NOT EXISTS idx_question_item_exam ON question_item(exam_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_question_item_track ON question_item(track, item_number);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_axis_analysis_item ON axis_analysis(item_id);")

        conn.commit()
        print("  - Migration transaction COMMITTED successfully.")

    except Exception as e:
        conn.rollback()
        print(f"  - [ERROR] Migration failed, transaction ROLLED BACK: {e}")
        raise e
    finally:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.close()

    # Reindex & Verify
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_key_check;")
    fk_errors = cur.fetchall()
    cur.execute("SELECT COUNT(*) FROM question_item;")
    q_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM axis_analysis;")
    a_count = cur.fetchone()[0]
    conn.close()

    print(f"[Phase 1 Complete] Foreign Key Errors: {len(fk_errors)}, Question Items: {q_count}, Axis Analysis Rows: {a_count}")
    return q_count, a_count

if __name__ == '__main__':
    create_physical_backup()
    run_migration()
