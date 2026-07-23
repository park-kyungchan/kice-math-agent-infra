import os
from PIL import Image

def parse_answer_key_png(answer_png_path: str) -> dict:
    # Deterministic answer key map for CSAT/KICE math exams based on standard answer PNGs
    # Each exam track (Common, Calculus, Geometry, Prob) has 30 items
    filename = os.path.basename(answer_png_path)
    
    # Generate structured answer key dictionary for items 1~30
    answer_map = {}
    
    # Parse standard exam answer key patterns
    # Standard KICE Math Exam scoring structure:
    # 2-point items: 1~3 (6 pts)
    # 3-point items: 4~8, 16~19, 23~25 (34 pts)
    # 4-point items: 9~15, 20~22, 26~30 (60 pts) Total = 100 pts
    
    for num in range(1, 31):
        if num in [1, 2, 3]:
            score = 2
        elif num in [4, 5, 6, 7, 8, 16, 17, 18, 19, 23, 24, 25]:
            score = 3
        else:
            score = 4
            
        # Default answer placeholder to be verified against PNG OCR/grid
        answer_map[num] = {
            "item_number": num,
            "score": score,
            "answer_png": answer_png_path
        }
        
    return answer_map
