# 모터 AI 모니터링 서비스 MVP

Streamlit + LangChain/LangGraph + ChromaDB + SQLite 기반 모터 상태 모니터링 및 AI 진단 서비스 MVP.

전체 사양은 [`.claude/docs/generated/`](.claude/docs/generated/) 6개 문서(`01_tech_stack.md` ~ `06_report_spec.md`)를 참고하세요. `.claude/docs/user/`는 원본 초안이며 개발 시 참고하지 않습니다.

## 로컬 개발 환경 설정

의존성 관리는 [uv](https://docs.astral.sh/uv/)를 사용합니다.

```bash
# 1. 의존성 설치 (.venv 자동 생성)
uv sync

# 2. 환경변수 설정
cp .env.example .env
# .env 파일을 열어 OPENAI_API_KEY 입력

# 3. 앱 실행 (최초 실행 시 스키마 생성 + 시연용 데이터 자동 준비)
uv run streamlit run main.py
```

데모 계정은 `demo1@example.com` / `demo2@example.com`이고 비밀번호는 둘 다 `demo1234!`입니다. 서로 다른 회사 소속이라 각자 자기 회사 이벤트만 봅니다.

## 시연용 데이터 (앱 부팅 시 자동 생성)

별도 준비 절차가 없습니다. 앱을 처음 띄우면 `app/services/bootstrap.py`가 스키마 생성 → 데모 데이터 시드 → RAG 인제스트 → 리포트 HTML 생성까지 한 번에 수행합니다.

Streamlit Community Cloud는 재배포/재시작 시 파일시스템이 초기화되므로 산출물을 커밋해도 소용이 없고, 커밋된 데이터는 시간이 지나면 "최근 48시간" 구간이 비어버립니다. 런타임 생성 방식은 **언제 켜도 항상 지금 기준 최근 48시간** 데이터를 갖습니다.

| 경로 | 소요 (로컬 실측) | 내용 |
|---|---|---|
| 콜드 (배포 환경, 첫 기동) | 약 3.4초 | 스키마 0.07s · 시드 0.68s · RAG 인제스트 1.4s · 리포트 HTML 1.3s |
| 웜 (로컬 재기동) | 약 0.5초 | 데이터·벡터가 이미 있어 시드와 인제스트를 모두 생략 |

생성물은 `data/app.db`(SQLite)와 `data/chroma/`(ChromaDB)이며 **git에 커밋하지 않습니다**. 동시 진입은 `data/.ingest.lock`(파일 락)과 `data/.ingest_done`(완료 마커)으로 차단합니다. 인제스트 원본인 `data/rag_sources/`만 커밋 대상입니다.

### 수동 재생성 (선택)

시드 로직을 바꿨거나 `data/rag_sources/`의 내용을 수정했을 때만 사용합니다. 청크 수가 그대로면 인제스트 생략 로직이 변경을 감지하지 못하므로 `--force`가 필요합니다.

```bash
uv run python scripts/seed_data.py --force   # DB를 지우고 처음부터 다시 생성
```

> ⚠️ **Windows에서는 리포트가 PDF 대신 HTML로 표시됩니다.** WeasyPrint는 Pango/GLib 네이티브 라이브러리를 요구하는데 Windows에는 기본 탑재되어 있지 않습니다. 앱은 이를 감지해 저장된 HTML을 다이얼로그에 그대로 보여주므로 **기능이 막히지는 않습니다**. PDF까지 확인하려면 WSL/Docker에서 실행하거나 GTK3 런타임을 설치하세요. Streamlit Community Cloud에서는 `packages.txt` 덕분에 PDF가 정상 생성되며, 한 번 만든 PDF는 `report_pdf` BLOB에 캐시되어 이후 즉시 응답합니다.

## 배포 (Streamlit Community Cloud)

1. `uv export --format requirements-txt --no-dev --no-hashes -o requirements.txt` 로 배포용 `requirements.txt`를 최신 상태로 갱신 후 커밋 (uv/pyproject.toml 변경 시마다 재실행).
2. Community Cloud 앱 설정의 **Secrets**에 `.streamlit/secrets.toml.example` 내용을 참고해 `OPENAI_API_KEY` 등을 입력.
3. `packages.txt`(WeasyPrint용 apt 패키지)가 저장소 루트에 있는지 확인 — 없으면 PDF 생성이 빌드/런타임에 실패합니다.
4. 배포 시점에 Python 3.14가 지원되지 않으면 `runtime.txt`로 지원 버전을 별도 지정해야 할 수 있습니다.

## 프로젝트 구조

```
app/            # 애플리케이션 코드
  pages/        #   화면: 로그인 · 메인 대시보드 · 모터 그래프 · 모터 현황 · 모터 상세
  ui/           #   재사용 컴포넌트 · 전역 스타일 · 네비게이션 · 테마
  services/     #   bootstrap(부팅 시 데이터 준비), seeding, motors, company, events, diagnosis
  reports/      #   HTML/PDF 렌더 및 리포트 제공 (PDF 실패 시 HTML 폴백)
  rag/          #   ChromaDB 인제스트 및 SOP 조회 (실패 시 키워드 매칭 폴백)
data/
  rag_sources/  #   RAG 인제스트 원본 텍스트 (git 커밋 대상)
  app.db        #   런타임 생성 — SQLite (git 제외)
  chroma/       #   런타임 생성 — ChromaDB persist (git 제외)
  .ingest_done  #   부트스트랩 완료 마커 (git 제외)
  .ingest.lock  #   부트스트랩 파일 락 (git 제외)
scripts/        # 선택적 수동 재생성 CLI (seed_data.py)
.claude/docs/generated/  # 확정 사양 문서 (단일 소스 오브 트루스)
```

## 현재 범위

동작하는 것: 로그인/인증, 런타임 데모 데이터 부트스트랩(COMP-001 200대 포함), 메인 대시보드(상단 요약 §3.1 · 조치 배너 · 정비 완료 확인 · 모터 카드 §3.2 · 이벤트 리스트 §3.3), 모터 그래프(지표별 추이 · 상태/위치/모델 필터 · 임계선), 모터 현황(확인사항/위치/상태 그룹핑), 모터 상세(§4), 리포트 제공(PDF 우선, 불가 시 HTML).

아직 구현되지 않은 것: LangGraph 진단 에이전트(현재는 `app/services/diagnosis.py`의 규칙 기반 템플릿), 실시간 상태 전이 감지 · 자동 갱신 · 통신 두절 판정, 알림 실제 발송, 48시간 보관 배치, Python 3.14 배포 검증. 상세 추적은 [`.claude/docs/plan/remaining_work.md`](.claude/docs/plan/remaining_work.md).
