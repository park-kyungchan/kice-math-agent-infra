#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Fix and Normalize Asset Image Paths in SQLite DB (fix_asset_paths.py)
Audits storage/parsed_dataset.db question_item table asset_image_url column,
resolves broken external paths to local workspace storage/assets/<item_id>_fig.png,
and commits updated paths.
"""

import sqlite3
import os

def fix_asset_image_paths(db_path: str = 'storage/parsed_dataset.db') -> dict:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT item_id, asset_image_url FROM question_item")
    rows = cur.fetchall()

    base_assets_dir = os.path.abspath('storage/assets')
    updated_count = 0
    missing_count = 0

    for item_id, current_url in rows:
        # Candidate local paths
        cand1 = os.path.join(base_assets_dir, f"{item_id}_fig.png")
        cand2 = os.path.join(base_assets_dir, f"{item_id}.png")

        valid_path = None
        if os.path.exists(cand1):
            valid_path = os.path.abspath(cand1)
        elif os.path.exists(cand2):
            valid_path = os.path.abspath(cand2)
        elif current_url and os.path.exists(current_url):
            valid_path = os.path.abspath(current_url)

        if valid_path:
            if current_url != valid_path:
                cur.execute("UPDATE question_item SET asset_image_url = ? WHERE item_id = ?", (valid_path, item_id))
                updated_count += 1
        else:
            missing_count += 1

    conn.commit()
    conn.close()

    return {
        "total_items": len(rows),
        "updated_paths": updated_count,
        "missing_assets": missing_count
    }

if __name__ == "__main__":
    res = fix_asset_image_paths()
    print(f"Asset Path Resolution Complete: Total Items={res['total_items']}, Updated={res['updated_paths']}, Missing={res['missing_assets']}")
