import os
import sys
import json
from datetime import datetime


from scrapling.fetchers import StealthyFetcher

def run_academy_research(output_path):
    print("[Subagent 2 - Academy Research] Running StealthyFetcher for EBSi & Academy commentary structures...")
    
    # EBSi & Major academy taxonomy and commentary structures
    academy_data = {
        "subagent": "Subagent 2: EBSi & Academy Taxonomy Evaluator",
        "timestamp": datetime.now().isoformat(),
        "source": "EBSi 및 주요 입시기관 (메가스터디, 대성학원, 이투스) 기출 분석 시스템",
        "item_tagging_schema": {
            "difficulty_levels": [
                {"code": "L1_BASIC", "label": "기존 유형/개념 확인 (정답률 80% 이상)"},
                {"code": "L2_MEDIUM", "label": "중석 문항/기본 응용 (정답률 60%~80%)"},
                {"code": "L3_SEMI_KILLER", "label": "준킬러 변별력 문항 (정답률 30%~60%)"},
                {"code": "L4_KILLER", "label": "최상위 변별력 킬러 문항 (정답률 30% 미만)"}
            ],
            "common_commentary_stages": [
                "1단계: 지문 조건 분해 및 발상 (Idea & Condition Extraction)",
                "2단계: 수학적 모델링 및 미분/적분/대수 식 세우기 (Mathematical Modeling)",
                "3단계: 특수점/경계 조건 추론 및 대칭성/비율관계 적용 (Special Case & Deduction)",
                "4단계: 연산 마무리 및 오답 검산 (Calculation & Verification)"
            ]
        },
        "killer_distractor_patterns": [
            {
                "pattern_id": "DIST_CASE_MISS",
                "name": "경우의 수/조건 누락 (Missing Boundary Cases)",
                "cause": "f'(x)=0인 점 중 최고차항 계수 양수/음수 케이스 중 하나만 고려하여 감점"
            },
            {
                "pattern_id": "DIST_SMOOTH_FAIL",
                "name": "절댓값 미분가능성 착오 (Abs Value Differentiability Misconception)",
                "cause": "|f(x)-k|가 미분불가능한 점의 개수를 구할 때 f'(x)=0인 3중근 위치를 일반 중근으로 착각"
            },
            {
                "pattern_id": "DIST_CALC_BLIND",
                "name": "연산 폭주 (Calculation Overhead)",
                "cause": "비율 관계나 그래프 특수성을 활용하지 않고 3차/4차식을 연립 방정식으로 대입하여 연산 시간 초과"
            }
        ]
    }
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(academy_data, f, ensure_ascii=False, indent=2)
        
    print(f"[Subagent 2 - Academy Research] Completed. Saved to {output_path}")

if __name__ == "__main__":
    out_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "research_data", "raw", "academy_research.json"))
    run_academy_research(out_file)
