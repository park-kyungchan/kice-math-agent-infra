import fitz  # PyMuPDF
import re

def extract_pdf_questions(pdf_path: str):
    doc = fitz.open(pdf_path)
    extracted_items = []
    
    for page_num in range(len(doc)):
        page = doc[page_num]
        page_rect = page.rect
        width, height = page_rect.width, page_rect.height
        mid_x = width / 2.0
        
        # 2-Column Boxes
        left_box = fitz.Rect(0, 0, mid_x, height)
        right_box = fitz.Rect(mid_x, 0, width, height)
        
        for col_idx, col_rect in enumerate([left_box, right_box]):
            blocks = page.get_text("blocks", clip=col_rect)
            # Sort blocks vertically
            blocks.sort(key=lambda b: b[1])
            
            current_item = None
            current_text_lines = []
            
            for b in blocks:
                b_rect = fitz.Rect(b[0], b[1], b[2], b[3])
                text = b[4].strip()
                if not text:
                    continue
                
                # Check for question header like "1.", "22.", "[22~23]"
                header_match = re.match(r'^\s*(\d{1,2})\.\s*', text)
                group_match = re.match(r'^\s*\[(\d{1,2})~(\d{1,2})\]', text)
                
                if header_match:
                    item_num = int(header_match.group(1))
                    if current_item:
                        current_item["text"] = "\n".join(current_text_lines)
                        extracted_items.append(current_item)
                        current_text_lines = []
                    
                    current_item = {
                        "page": page_num + 1,
                        "column": "left" if col_idx == 0 else "right",
                        "item_number": item_num,
                        "rect": [b_rect.x0, b_rect.y0, b_rect.x1, b_rect.y1],
                        "header_text": text
                    }
                    current_text_lines.append(text)
                elif group_match:
                    # Pass passage box
                    if current_item:
                        current_text_lines.append(text)
                else:
                    if current_item:
                        current_text_lines.append(text)
                        # Expand bbox
                        current_item["rect"][2] = max(current_item["rect"][2], b_rect.x1)
                        current_item["rect"][3] = max(current_item["rect"][3], b_rect.y1)
            
            if current_item:
                current_item["text"] = "\n".join(current_text_lines)
                extracted_items.append(current_item)
                
    doc.close()
    return extracted_items
