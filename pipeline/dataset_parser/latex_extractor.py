from dataset_parser.math_normalizer import normalize_latex, parse_choice_options

def process_item_content(item_raw: dict) -> dict:
    raw_text = item_raw.get("text", "")
    normalized_text = normalize_latex(raw_text)
    options = parse_choice_options(normalized_text)
    
    return {
        "item_number": item_raw.get("item_number"),
        "page": item_raw.get("page"),
        "column": item_raw.get("column"),
        "rect": item_raw.get("rect"),
        "latex_content": normalized_text,
        "options": options
    }
