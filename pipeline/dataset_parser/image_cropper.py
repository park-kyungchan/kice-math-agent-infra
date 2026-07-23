import os
import fitz

def crop_item_asset(pdf_path: str, page_num: int, rect: list, output_image_path: str) -> str:
    os.makedirs(os.path.dirname(output_image_path), exist_ok=True)
    
    doc = fitz.open(pdf_path)
    page = doc[page_num - 1]
    
    # 10px safety margin
    crop_box = fitz.Rect(
        max(0, rect[0] - 5),
        max(0, rect[1] - 5),
        min(page.rect.width, rect[2] + 5),
        min(page.rect.height, rect[3] + 5)
    )
    
    # 300 DPI matrix (scale = 300/72 = 4.1666)
    zoom = 300 / 72.0
    mat = fitz.Matrix(zoom, zoom)
    
    pix = page.get_pixmap(matrix=mat, clip=crop_box)
    pix.save(output_image_path)
    doc.close()
    
    return output_image_path
