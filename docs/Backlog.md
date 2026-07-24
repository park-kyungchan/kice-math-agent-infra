# 수능/평가원 수학 Zero-Context Agent Infra - Future Backlog

본 문서는 Phase 3 (`Agent.md` 명세 구축) 이후 수행할 **기출 분석 인프라 SSoT Governance, 자동 태깅, DB 가동 및 Phase 4 쿼리 엔진 구축 백로그(Backlog)**입니다.

---

## 📋 Task Backlog List

### [ACTIVE] Backlog Item 1: v2.8.0 Zero-Context SSoT Governance 구축
- **작업 내용**:
  - `SSOT_MAP.md`를 통한 도메인별 기준 문서 확립
  - `STAKEHOLDER_INTENT.md`를 통한 인스트럭터 및 AI 에이전트 목표 정의
  - `PROJECT_STATE.json` 시스템 상태 머신 생성

### [PLANNED] Backlog Item 2: v2.8.1 Technical Proof & Independent Solvers
- **작업 내용**:
  - `agents_spec/`에 구축된 3-Layer 8-Axis `Agent.md` 및 `router_orchestrator_agent.md`를 구동하는 Async Worker Pipeline (`run_axis_tagging.py`) 작성
  - **타겟 문항 우선 구축**: 2027학년도 대비 고난도/핵심 기출 문항 족보(Axis 6, 7) 집중 축적
  - 외부 독립적 수식 풀이(Independent Solver) 모듈과의 결합(Integration) 및 성능 검증(Execution Proof)

### [PLANNED] Backlog Item 3: Phase 4-A Zero-Context Agent 쿼리 API & Selective Fetching 엔진
- **작업 내용**:
  - 사전 맥락 없는 에이전트가 단 1회의 쿼리로 Layer 1~3 데이터를 탐색하고 선택적으로 불러오는 Selective Fetching API 개발
  - Vector DB 연동을 통한 지문 수식 및 조건 의미론적(Semantic) 유사도 검색 쿼리 인터페이스 구축

---

## 📌 Status Tracker
- [x] **Phase 1**: Scrapling 다각도 리서치 & 문항 분석 축 정립 (`Taxonomy_Spec.md` 완료)
- [x] **Phase 2**: 2021~2026 기출 파싱 & 4-Tier DB 구축 완료 (`parsed_dataset.db`, 1,350개 문항 적재)
- [x] **Phase 3-A**: **v2.7.0** 3-Layer 8-Axis 분석 축별 `Agent.md` 및 Master Router 명세 생성 (완료)
- [~] **Phase 3-B**: **v2.8.0** Zero-Context SSoT Governance 확립 (진행 중)
- [ ] **Phase 3-C**: **v2.8.1** Technical Proof & Independent Solvers 연동 (예정)
- [ ] **Phase 4-A**: Zero-Context 쿼리 API 엔진
- [ ] **Phase 4-B**: 2027 6모 심층 분석 시연 검증
