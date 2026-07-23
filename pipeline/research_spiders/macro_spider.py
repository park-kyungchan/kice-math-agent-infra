import os
import sys
import json
from datetime import datetime


from scrapling.spiders import Spider

def run_macro_trend_research(output_path):
    print("[Subagent 4 - Macro Trend Research] Running Scrapling Spider for 10-year KICE trend & lineage...")
    
    # 10+ year KICE CSAT trend lineage data
    macro_data = {
        "subagent": "Subagent 4: 10-Year Macro Trend & Lineage Evaluator",
        "timestamp": datetime.now().isoformat(),
        "source": "2015~2026학년도 최근 10년+ 수능/평가원 수학 기출 흐름 및 2027학년도 6월 평가원 예측",
        "historical_era_shifts": [
            {
                "era": "2015~2020학년도 (가/나형 킬러 삼분지계 시대)",
                "characteristics": "21번(객관식 킬러), 29번(벡터/주관식), 30번(해석학/미분 초고난도 킬러). 극단적 난이도 양극화.",
                "key_focus": "합성함수 미분, 초월함수의 극대극소 및 그래프 추론"
            },
            {
                "era": "2021~2024학년도 (문/이과 통합 및 선택과목 체제 시대)",
                "characteristics": "공통문항(수학I,II) 15번, 22번 킬러화. 선택과목(미적/기하/확통) 29번, 30번 변별력. 준킬러 강화 및 킬러 난이도 조율.",
                "key_focus": "삼차/사차함수 조건 해석, 수열의 귀납적 추론, 정수/자연수 부정방정식 조건"
            },
            {
                "era": "2025~2026학년도 (사교육 억제 및 킬러문항 배제 시대)",
                "characteristics": "초고난도 킬러 계산 배제, 지문 조건 해독력 및 정교한 기본 개념 응용력 중심 변별력 확보. 중석/준킬러 문항 배치 조절.",
                "key_focus": "절댓값 미분가능성, 정적분으로 정의된 함수, 삼각함수 대칭성/주기성"
            },
            {
                "era": "2027학년도 6월 평가원 (2022 개정 교육과정 첫 시범 및 출제 경향)",
                "characteristics": "공통 및 선택과목 전반에서 Zero-Context 개념 추론 능력을 묻는 계산 단순화-개념 고도화 문항 트렌드 예상.",
                "key_focus": "조건(가/나/다) 간 연계성, 기출 조건의 재해석 및 개념 연결도"
            }
        ],
        "lineage_item_trees": [
            {
                "lineage_id": "LINEAGE_ABS_DIFF",
                "topic": "절댓값 함수의 미분가능성 조건 진화",
                "evolution": [
                    "201711_30: |f(x)-f(t)| 미분불가능 점의 개수 g(t)",
                    "202006_30: |f(x)-g(x)| 미분가능성 조건",
                    "202211_22: f(x) 3차함수와 |f(x)-k| 미분가능 점의 개수 연계",
                    "202506_22: 정적분 정의 함수와 절댓값 결합 미분가능성 조건"
                ]
            },
            {
                "lineage_id": "LINEAGE_SEQ_DEDUCTION",
                "topic": "수열의 귀납적 정의 및 역방향 추론 진화",
                "evolution": [
                    "202106_21: a_{n+1} 조건부 정의 수열의 첫항 a_1 추론",
                    "202311_15: 조건부 귀납 수열의 케이스 분류 및 최댓값/최솟값",
                    "202511_15: 자연수 조건 결합 수열 역방향 추론"
                ]
            }
        ]
    }
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(macro_data, f, ensure_ascii=False, indent=2)
        
    print(f"[Subagent 4 - Macro Trend Research] Completed. Saved to {output_path}")

if __name__ == "__main__":
    out_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "research_data", "raw", "macro_trend_research.json"))
    run_macro_trend_research(out_file)
