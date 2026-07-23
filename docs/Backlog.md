# 수능/평가원 수학 Zero-Context Agent Infra - Future Backlog

본 문서는 Phase 3 (`Agent.md` 명세 구축) 이후 수행할 **기출 분석 인프라 자동 태깅, DB 가동 및 Phase 4 쿼리 엔진 구축 백로그(Backlog)**입니다.

---

## 📋 Task Backlog List

### Backlog Item 1: Phase 3-B 대량 문항 자동 태깅 및 점진적(Progressive) 계통도 구축
- **작업 내용**:
  - `agents_spec/`에 구축된 6대 축 `Agent.md` 및 `router_orchestrator_agent.md`를 구동하는 Async Worker Pipeline (`run_axis_tagging.py`) 작성
  - **타겟 문항 우선 구축**: 2027학년도 6월 평가원 대비 2024~2026학년도 고난도/핵심 기출 문항부터 `Axis 4A` (아이디어 족보) 및 `Axis 4B` (조건 표상 변형사) 계통도 집중 축적
  - `parsed_dataset.db` 내 `axis_analysis` 테이블에 6대 축 JSON 분석 데이터 완전 적재

### Backlog Item 2: Phase 4-A Zero-Context Agent 쿼리 API & Selective Fetching 엔진
- **작업 내용**:
  - 사전 맥락 없는 에이전트가 단 1회의 쿼리로 `Axis 1` (개념 라우팅 키)를 탐색한 후, 필요에 따라 `Axis 2~5` 데이터를 선택적으로 불러오는 Selective Fetching API 개발
  - Vector DB (pgvector / Chroma) 연동을 통한 지문 수식 및 조건 의미론적(Semantic) 유사도 검색 쿼리 인터페이스 구축

### Backlog Item 3: Phase 4-B 2027학년도 6월 평가원 기출문항 심층 분석 및 실전 시연
- **작업 내용**:
  - 2027학년도 6월 평가원 신유형 문항을 인프라에 투입하여 6대 축 기반 조건 해독, 오답 함정 예측, 과거 10년 족보 연계 및 해설 생성 엔드투엔드 시연
  - 4대 Eval Subagents를 구동하여 최종 Zero-Context 풀이 성공률(Solvability) 검증

---

## 📌 Status Tracker
- [x] **Phase 1**: Scrapling 다각도 리서치 & 문항 분석 축 정립 (`Taxonomy_Spec.md` 완료)
- [x] **Phase 2**: 2021~2026 기출 PDF/PNG 90개 파싱 & 4-Tier DB 구축 완료 (`parsed_dataset.db`, 1,350개 문항 적재)
- [x] **Phase 3-A**: 6대 분석 축별 `Agent.md` 및 Master Router 명세 생성 (완료)
- [ ] **Phase 3-B**: 백로그 아이템 1 (1,350개 문항 점진적 자동 태깅 실행)
- [ ] **Phase 4-A**: 백로그 아이템 2 (Zero-Context 쿼리 API 엔진)
- [ ] **Phase 4-B**: 백로그 아이템 3 (2027 6모 심층 분석 시연 검증)
