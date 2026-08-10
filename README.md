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

이게 전부입니다. RAG 벡터는 저장소에 커밋되어 있어 별도 등록 절차가 필요 없습니다.

데모 계정은 `demo1@example.com` / `demo2@example.com`이고 비밀번호는 둘 다 `demo1234!`입니다. 서로 다른 회사 소속이라 각자 자기 회사 이벤트만 봅니다.

## 부팅 시 무슨 일이 일어나나

`app/services/bootstrap.py`가 프로세스당 1회 실행됩니다. **가르는 기준은 "데이터가 시간에 의존하는가"입니다.**

```
1. 스키마 보장    CREATE TABLE IF NOT EXISTS
2. 데모 시드      데이터가 있고 신선하면 생략 (재실행 안전)
3. RAG 적재 확인  collection.count()만 읽음 — 인제스트 아님
```

**부팅 경로에 OpenAI API 호출이 없습니다.** API 키가 없어도 앱은 정상 기동하며, 키는 리포트를 열 때만 쓰입니다.

부팅 결과는 프로세스 로그(배포 환경에서는 Manage app 로그)에 두 줄로 남습니다. 화면에 드러나지 않는 실패 — 특히 **RAG 미적재 시 SOP가 조용히 키워드 폴백으로 떨어지는 것** — 을 판정하는 통로입니다.

```
INFO [app.services.bootstrap] 환경 | python=3.14.6 streamlit=1.60.0 chromadb=1.5.9 langgraph=1.2.10 | openai_key=설정됨 diagnosis_llm=on
INFO [app.services.bootstrap] 부트스트랩 완료 | 모터 210대 텔레메트리 288,210행 상태로그 80건 | rag_ready=True rag_chunks=44 | 4.49s (...)
```

리포트를 열면 `진단 생성 | MTR-227 sound | source=llm | 6.31s`가 추가로 남아 LLM이 실제로 돌았는지 확인됩니다. API 키 값은 로그에 남지 않습니다 — 설정 여부만 찍습니다.

| 자산 | 시간 의존 | 준비 방식 |
|---|---|---|
| 텔레메트리·상태로그 | O | 부팅 시 생성 (`data/app.db`, 커밋 안 함) |
| RAG 벡터 | X | `data/chroma/` 커밋본 사용 — 등록 불필요 |
| 참조 지식 (고장모드) | X | `data/knowledge/*.json` 커밋본 — 파일이 곧 데이터 |
| 리포트 HTML | O | 최초 열람 시 생성 후 DB 캐시 |

데모 텔레메트리를 커밋하지 않는 이유는 `app/services/seeding.py`가 **실행 시각 기준 최근 48시간**을 채우기 때문입니다. 커밋하면 며칠 뒤 빈 대시보드를 보게 됩니다.

| 경로 | 소요 (로컬 실측, 모터 210대) | 내용 |
|---|---|---|
| 콜드 (배포 환경, 첫 기동) | **4.43초** | 스키마 0.03s · 시드 3.93s · RAG 확인 0.47s |
| 웜 (로컬 재기동) | 약 0.5초 | 데이터가 있고 신선해 시드 생략 |

> **데모 데이터는 실행 시각 기준 최근 48시간이라 시간이 지나면 낡는다.** 최신 텔레메트리가 `config.DEMO_DATA_MAX_AGE_HOURS`(2시간)보다 오래되면 부팅 시 **자동으로 다시 만든다**. 이 판정이 없으면 앱을 몇 시간 켜둔 뒤 모터 그래프(6시간 창)가 "데이터 없음"이 된다.

동시 진입은 `data/.ingest.lock`(파일 락)과 `data/.ingest_done`(완료 마커)으로 차단합니다.

## 수동 스크립트 (선택)

### 데모 데이터 재생성

시드 로직을 바꿨을 때만 사용합니다.

```bash
uv run python scripts/seed_data.py --force            # DB를 지우고 처음부터 다시 생성
uv run python scripts/seed_data.py --with-reports     # 리포트 HTML까지 전건 미리 생성
```

`--with-reports`는 건당 RAG 조회 + 진단 LLM 호출이 붙어 **약 4초 × 대상 건수**가 걸립니다(24건이면 1분 반). 시작 전에 건수와 예상 소요를 출력합니다. 평상시에는 최초 열람 시 1건씩 생성되므로 이 플래그가 필요 없습니다.

리포트 템플릿이나 진단 로직을 바꿨다면 **이미 저장된 HTML은 갱신되지 않습니다.** 캐시를 비우면 다음 열람에서 새로 생성됩니다:

```bash
uv run python scripts/seed_data.py --reset-reports
```

### RAG 벡터 재구축

**`data/rag_sources/`의 텍스트를 수정했을 때만** 실행합니다. 원본이 시간에 무관한 정적 텍스트라 한 번 만들면 끝이고, 산출물을 커밋해야 배포에 반영됩니다.

```bash
uv run python scripts/build_knowledge.py --dry-run    # 임베딩 없이 청크 구성만 확인 (API 키 불필요)
uv run python scripts/build_knowledge.py --force      # 실제 재임베딩 (앱을 내린 상태에서)
```

> ⚠️ **앱이 떠 있는 상태로 실행하지 마세요.** ChromaDB의 persist 디렉터리는 다중 프로세스 동시 쓰기를 가정하지 않습니다. 앱이 스토어를 연 채로 갱신되면 앱 쪽 벡터 검색이 **예외 없이 조용히** 실패해 SOP가 키워드 폴백으로 떨어집니다. 재구축 후에는 앱을 재기동하세요.

> ⚠️ **Windows에서는 리포트가 PDF 대신 HTML로 표시됩니다.** WeasyPrint는 Pango/GLib 네이티브 라이브러리를 요구하는데 Windows에는 기본 탑재되어 있지 않습니다. 앱은 이를 감지해 저장된 HTML을 다이얼로그에 그대로 보여주므로 **기능이 막히지는 않습니다**. PDF까지 확인하려면 WSL/Docker에서 실행하거나 GTK3 런타임을 설치하세요. Streamlit Community Cloud에서는 `packages.txt` 덕분에 PDF가 정상 생성되며, 한 번 만든 PDF는 `report_pdf` BLOB에 캐시되어 이후 즉시 응답합니다.

## 배포 (Streamlit Community Cloud)

1. `uv export --format requirements-txt --no-dev --no-hashes -o requirements.txt` 로 배포용 `requirements.txt`를 최신 상태로 갱신 후 커밋 (uv/pyproject.toml 변경 시마다 재실행).
2. Community Cloud 앱 설정의 **Secrets**에 `.streamlit/secrets.toml.example` 내용을 그대로 붙여넣고 `OPENAI_API_KEY`를 채웁니다.
3. `packages.txt`(WeasyPrint용 apt 패키지)가 저장소 루트에 있는지 확인 — 없으면 PDF 생성이 빌드/런타임에 실패합니다. Community Cloud는 이 목록을 **Debian 11(bullseye)** 기준으로 `apt-get` 합니다.
4. 배포 시점에 Python 3.14가 지원되지 않으면 `runtime.txt`로 지원 버전을 별도 지정해야 할 수 있습니다.

### 배포본은 진단 LLM을 끕니다 (2026-08-10 결정)

Secrets에 `DIAGNOSIS_LLM_ENABLED = "false"`를 둡니다. Community Cloud 앱은 URL을 아는 누구나 접근할 수 있고 **로그인 화면에 시연 계정이 노출되어 있어**, 리포트를 열 때마다 나가는 GPT-4o 호출을 통제할 수단이 없기 때문입니다.

- 배포본의 리포트는 규칙 기반 진단으로 생성되고, 진단 모델 라벨이 `규칙 기반 진단 (LLM 미사용)`으로 표시됩니다. 4개 섹션 구성과 측정 근거는 동일합니다.
- **`OPENAI_API_KEY`는 그대로 둡니다.** 이 스위치는 진단 LLM만 끄며, 키를 비우면 SOP 벡터 검색까지 죽어 `rag_ready=False`가 됩니다. 임베딩 비용은 질의당 $0.00002 수준입니다.
- **AI 진단 시연은 로컬에서** `DIAGNOSIS_LLM_ENABLED=true`로 두고 보여줍니다.

### 배포 후 확인 (Manage app → 로그)

부팅 두 줄로 대부분이 판정됩니다 — 자세한 배경은 `02_architecture.md` §6.5.

| 확인할 것 | 로그에서 볼 값 | 기대값 |
|---|---|---|
| Python 버전 | `환경 \| python=` | 선택한 버전 |
| chromadb 버전 | `환경 \| chromadb=` | `1.5.9` (커밋된 persist 포맷 기준) |
| Secrets 반영 | `환경 \| openai_key=` / `diagnosis_llm=` | `설정됨` / `off` |
| RAG 적재 | `부트스트랩 완료 \| rag_ready=` `rag_chunks=` | `True` / `44` |
| 부팅 시드 소요 | `부트스트랩 완료 \| … N초` | 로컬 4.49초 대비 비교 |
| 진단 경로 | 리포트를 열면 `진단 생성 \| … source=` | `rule` (배포본 설정상 정상) |

`rag_ready=False`면 WARNING이 함께 뜹니다. PDF는 로그가 아니라 화면으로 확인합니다 — 리포트가 다운로드 버튼(PDF)으로 나오면 성공, 다이얼로그에 HTML로 표시되면 WeasyPrint가 실패한 것입니다.

## 프로젝트 구조

```
app/            # 애플리케이션 코드
  pages/        #   화면: 로그인 · 메인 대시보드 · 모터 그래프 · 모터 현황 · 모터 상세
  ui/           #   재사용 컴포넌트 · 전역 스타일 · 네비게이션 · 테마
  agents/       #   LangGraph 진단 에이전트 + 입출력 스키마 (실패 시 규칙 기반 폴백)
  logging_setup.py  # 앱 로거 설정 — 부팅 요약·진단 결과를 프로세스 로그로 남긴다
  services/     #   bootstrap(부팅 시 데이터 준비), seeding, motors, company, events, diagnosis
  reports/      #   HTML/PDF 렌더 및 리포트 제공 (PDF 실패 시 HTML 폴백)
  rag/          #   ChromaDB 인제스트·SOP 조회(실패 시 키워드 폴백), 참조 지식 조회
  prompts.py    #   LLM 프롬프트 문자열 (비즈니스 코드와 분리)
data/
  rag_sources/  #   RAG 인제스트 원본 텍스트 (커밋)
  knowledge/    #   참조 지식 — 고장모드·지표 매핑 JSON (커밋)
  chroma/       #   ChromaDB persist — 수동 구축 후 커밋
  app.db        #   런타임 생성 — SQLite (git 제외)
  .ingest_done  #   부트스트랩 완료 마커 (git 제외)
  .ingest.lock  #   부트스트랩 파일 락 (git 제외)
scripts/        # 수동 CLI — seed_data.py(데모 데이터), build_knowledge.py(RAG 벡터)
.claude/docs/generated/  # 확정 사양 문서 (단일 소스 오브 트루스)
```

## 현재 범위

동작하는 것: 로그인/인증, 런타임 데모 데이터 부트스트랩(COMP-001 200대 포함), 메인 대시보드(상단 요약 §3.1 · 조치 배너 · 정비 완료 확인 · 모터 카드 §3.2 · 이벤트 리스트 §3.3), 모터 그래프(지표별 추이 · 상태/위치/모델 필터 · 임계선), 모터 현황(확인사항/위치/상태 그룹핑), 모터 상세(§4), **LangGraph 진단 에이전트**(리포트 AI 진단 4섹션), 리포트 제공(PDF 우선, 불가 시 HTML).

**첫 리포트 열람은 몇 초 걸립니다.** 진단은 리포트를 열 때 생성되며(부팅 경로에는 LLM 호출이 없습니다), 프로세스 최초 열람이 실측 5~9초(LangGraph 콜드 import 3.17초 포함), 이후 4초대, 재열람은 캐시로 0.03초입니다. API 키가 없거나 LLM이 실패하면 규칙 기반 진단으로 폴백하고, 리포트의 진단 모델 라벨이 "규칙 기반 진단 (LLM 미사용)"으로 바뀝니다. `DIAGNOSIS_LLM_ENABLED=false`로 강제 오프할 수 있습니다.

아직 구현되지 않은 것: 실시간 상태 전이 감지 · 자동 갱신 · 통신 두절 판정, 알림 실제 발송, 48시간 보관 배치, Python 3.14 배포 검증. 상세 추적은 [`.claude/docs/plan/remaining_work.md`](.claude/docs/plan/remaining_work.md).
