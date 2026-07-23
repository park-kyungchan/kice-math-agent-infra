import re

def normalize_latex(text: str) -> str:
    if not text:
        return ""
    
    # Clean up multiple whitespaces
    res = re.sub(r'[ \t]+', ' ', text)
    
    # Standardize choices ① ~ ⑤
    choices_map = {
        '①': '[CHOICE_1]', '②': '[CHOICE_2]', '③': '[CHOICE_3]',
        '④': '[CHOICE_4]', '⑤': '[CHOICE_5]'
    }
    for ch, tag in choices_map.items():
        res = res.replace(ch, f"\n{tag} ")
        
    # Standardize fraction LaTeX
    res = re.sub(r'\\over\b', r'\\frac', res)
    
    # Standardize square root
    res = re.sub(r'\\root\s+(\d+)\s+\\of', r'\\sqrt[\1]', res)
    
    # Clean up empty lines
    lines = [line.strip() for line in res.split('\n') if line.strip()]
    return '\n'.join(lines)

def parse_choice_options(text: str) -> dict:
    options = {}
    pattern = r'\[CHOICE_(\d)\]\s*(.*?)(?=\[CHOICE_\d\]|$)'
    matches = re.findall(pattern, text, re.DOTALL)
    for num, content in matches:
        options[f"choice_{num}"] = content.strip()
    return options
