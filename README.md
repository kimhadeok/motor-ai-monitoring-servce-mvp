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

데모 계정은 `demo1@hankuk-motors.co.kr` / `demo2@daehan-heavy.co.kr`이고 비밀번호는 둘 다 `demo1234!`입니다. 서로 다른 회사 소속이라 각자 자기 회사 이벤트만 봅니다.

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
INFO [app.services.bootstrap] 부트스트랩 완료 | 모터 210대 텔레메트리 92,997행 상태로그 80건 | rag_ready=True rag_chunks=44 | 3.29s (...)
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
| 콜드 (배포 환경, 첫 기동) | **3.29초** | 스키마 0.08s · 시드 2.62s · RAG 확인 0.59s |
| 웜 (로컬 재기동) | 약 0.5초 | 데이터가 있고 신선해 시드 생략 |

> **시드는 48시간을 걷되 저장은 필요한 것만 한다 (2026-08-11).** 화면이 보는 창은 길어야 최근 6시간이고(모터 그래프 3시간 · 카드 스파크라인 3시간 · 모터 세부정보 6시간), **세 곳 모두 2026-08-12부터 수집 원본을 그대로 그린다** — 최근 8시간 전량 저장이 그 전제다. 그래서 최근 8시간은 전량, 전이 시각 행과 그 직전 행은 반드시, 나머지는 15분 간격으로 저장한다. **288,210행 3.80초 → 92,997행 2.62초**(전이 80건·통보 이벤트 24건 불변 — 발송 기록은 2026-08-12부터 채널당 한 행이라 48행이다). 다만 FAULT 모터 4대만은 예외로 10초 주기를 줘서 대시보드 첫 줄이 자동 갱신에 맞춰 움직이게 했다(05 §5-2-2). 자세한 근거는 `02_architecture.md §6.1`.

> **데모 데이터는 실행 시각 기준 최근 48시간이라 시간이 지나면 낡는다.** 최신 텔레메트리가 `config.DEMO_DATA_MAX_AGE_HOURS`(2시간)보다 오래되면 부팅 시 **자동으로 다시 만든다**. 이 판정이 없으면 앱을 몇 시간 켜둔 뒤 모터 그래프(3시간 창)·모터 세부정보(6시간 창)가 "데이터 없음"이 된다. 앱을 켜둔 동안에는 런타임 틱이 최신 데이터를 계속 밀어 올려 재시드가 걸리지 않는다.

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

### 리포트 PDF 검증 (레이아웃을 바꿨을 때)

WeasyPrint는 flexbox 처리가 Chromium과 달라 **브라우저로는 PDF 레이아웃을 검증할 수 없습니다.** 배포 환경과 같은 Debian trixie 컨테이너에서 확인하세요 — 방법과 Dockerfile은 `02_architecture.md` §6.6에 있습니다. 배포본에서 내려받은 PDF를 그냥 눈으로 확인만 할 때는 컨테이너 없이:

```bash
uv run --with pymupdf --no-project python -c "import pymupdf,sys; d=pymupdf.open(sys.argv[1]); [p.get_pixmap(dpi=90).save(f'page{i}.png') for i,p in enumerate(d,1)]" report.pdf
```

> ⚠️ **Windows에서는 리포트가 PDF 대신 HTML로 표시됩니다.** WeasyPrint는 Pango/GLib 네이티브 라이브러리를 요구하는데 Windows에는 기본 탑재되어 있지 않습니다. 앱은 이를 감지해 저장된 HTML을 다이얼로그에 그대로 보여주므로 **기능이 막히지는 않습니다**. PDF까지 확인하려면 WSL/Docker에서 실행하거나 GTK3 런타임을 설치하세요. Streamlit Community Cloud에서는 `packages.txt` 덕분에 PDF가 정상 생성되며, 한 번 만든 PDF는 `report_pdf` BLOB에 캐시되어 이후 즉시 응답합니다.

## 배포 (Streamlit Community Cloud)

1. 의존성은 **`uv.lock`이 그대로 쓰인다** — Community Cloud가 `uv-sync`로 설치한다(2026-08-10 배포 로그로 확인). 저장소에 `uv.lock`·`requirements.txt`·`pyproject.toml`이 함께 있어 Cloud가 `WARN: More than one requirements file detected`를 남기지만, 실제 선택은 `uv.lock`이다. `requirements.txt`는 다른 환경용 폴백으로만 유지하며 `uv export --format requirements-txt --no-dev --no-hashes -o requirements.txt`로 갱신한다.
2. Community Cloud 앱 설정의 **Secrets**에 `.streamlit/secrets.toml.example` 내용을 그대로 붙여넣고 `OPENAI_API_KEY`를 채웁니다.
3. `packages.txt`(WeasyPrint용 apt 패키지)가 저장소 루트에 있는지 확인 — 없으면 PDF 생성이 빌드/런타임에 실패합니다. **패키지 이름은 Debian 13(trixie) 기준입니다** (아래 참고).
4. 배포 시점에 Python 3.14가 지원되지 않으면 `runtime.txt`로 지원 버전을 별도 지정해야 할 수 있습니다.

### packages.txt는 Debian 13(trixie) 기준입니다 (2026-08-10 배포 로그로 확인)

Streamlit 문서는 `packages.txt`가 "Debian 11(bullseye) 패키지를 참조해야 한다"고 안내하지만, **실제 빌드 이미지는 trixie였습니다.** 첫 배포가 여기서 실패했습니다:

```
Package libgdk-pixbuf2.0-0 is not available, but is referred to by another package.
However the following packages replace it: libgdk-pixbuf-xlib-2.0-0 libgdk-pixbuf-2.0-0
E: Package 'libgdk-pixbuf2.0-0' has no installation candidate
```

현재 목록은 [WeasyPrint 공식 설치 문서](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html)가 Debian ≥ 11에 요구하는 것만 담았고, 네 개 모두 trixie에 존재하는 것을 확인했습니다.

| 패키지 | 용도 |
|---|---|
| `libpango-1.0-0` | 텍스트 레이아웃 |
| `libpangoft2-1.0-0` | Pango FreeType 백엔드 |
| `libharfbuzz-subset0` | 폰트 서브셋 (PDF 임베딩) |
| `fonts-noto-cjk` | **한글 글리프** — 없으면 PDF에서 한글이 깨집니다 |

`libgdk-pixbuf`·`libcairo2`·`libpangocairo`·`libffi-dev`·`shared-mime-info`는 뺐습니다. WeasyPrint는 53버전부터 cairo와 gdk-pixbuf를 쓰지 않고(래스터 이미지는 Pillow가 처리), 공식 문서의 의존성 목록에도 없습니다. 불필요한 패키지는 빌드만 늦추고 배포판이 바뀔 때 이름 문제를 다시 일으킵니다.

### 배포본도 진단 LLM을 켭니다 (2026-08-11 결정 — 종전 방침 뒤집음)

Secrets에 `DIAGNOSIS_LLM_ENABLED = "true"`를 둡니다(항목을 빼도 기본값이 `true`입니다). 구매를 검토하는 고객에게 보여줄 배포본에서 "AI 진단"이 실제로는 규칙 기반인 것이 시연상 가장 큰 약점이라는 판단입니다.

**종전 방침(2026-08-10)은 `false`였습니다.** 공개 URL + 로그인 화면의 시연 계정 노출로 GPT-4o 호출을 통제할 수 없다는 우려였는데, 호출 구조를 다시 확인해 우려 규모를 실측했습니다.

- **호출은 [보고서] 클릭당 최초 1회뿐입니다.** 부팅 경로에는 LLM 호출이 없고(`generate_missing_report_html()`은 `scripts/seed_data.py --with-reports`에서만 호출), `report_html`이 비어 있을 때만 진단이 돌며 결과는 DB에 캐시됩니다. 같은 리포트 재열람은 호출이 없습니다.
- **부팅 1회당 상한은 24호출**입니다 — 리포트 대상은 DANGER 19건 + FAULT 5건. 재부팅으로 재시드되면 캐시가 초기화되므로 상한이 다시 열립니다.
- **`OPENAI_API_KEY`는 그대로 둡니다.** 이 스위치는 진단 LLM만 끄며, 키를 비우면 SOP 벡터 검색까지 죽어 `rag_ready=False`가 됩니다. 임베딩 비용은 질의당 $0.00002 수준입니다.
- `true`여도 타임아웃·API 오류·출력 검증 실패 시에는 규칙 기반으로 조용히 폴백하고 라벨이 `규칙 기반 진단 (LLM 미사용)`으로 바뀝니다. 실제 경로는 로그의 `source=llm` / `source=rule`로 판정합니다.
- **확인 완료 (2026-08-12)**: 배포 로그의 `diagnosis_llm=on`과 리포트 열람 시 `source=llm`을 배포본에서 모두 확인했습니다. 배포본의 "AI 진단"은 실제 GPT-4o 생성물입니다.

### 배포 후 확인 (Manage app → 로그)

부팅 두 줄로 대부분이 판정됩니다 — 자세한 배경은 `02_architecture.md` §6.5.

| 확인할 것 | 로그에서 볼 값 | 기대값 |
|---|---|---|
| Python 버전 | `환경 \| python=` | 선택한 버전 |
| chromadb 버전 | `환경 \| chromadb=` | `1.5.9` (커밋된 persist 포맷 기준) |
| Secrets 반영 | `환경 \| openai_key=` / `diagnosis_llm=` | `설정됨` / `on` — 2026-08-12 배포 로그에서 확인 |
| RAG 적재 | `부트스트랩 완료 \| rag_ready=` `rag_chunks=` | `True` / `44` |
| 부팅 시드 소요 | `부트스트랩 완료 \| … N초` | **판정 완료 (2026-08-12): 23.28초 → 7.27초**(시드 21.74 → 5.71초). 이후 배포에서는 이 값과 비교한다 |
| 진단 경로 | 리포트를 열면 `진단 생성 \| … source=` | `llm` — **2026-08-12 배포본에서 확인 완료**. `rule`이면 폴백이며 리포트 라벨도 "규칙 기반 진단 (LLM 미사용)"으로 바뀐다 |

`rag_ready=False`면 WARNING이 함께 뜹니다. PDF는 로그가 아니라 화면으로 확인합니다 — 리포트가 다운로드 버튼(PDF)으로 나오면 성공, 다이얼로그에 HTML로 표시되면 WeasyPrint가 실패한 것입니다.

## 프로젝트 구조

```
app/            # 애플리케이션 코드
  pages/        #   화면: 로그인 · 메인 대시보드 · 모터 그래프 · 모터 현황 · 모터 상세 · 관리자
  ui/           #   재사용 컴포넌트 · 전역 스타일 · 네비게이션 · 테마 · 차트(charts.py)
  agents/       #   LangGraph 진단 에이전트 + 입출력 스키마 (실패 시 규칙 기반 폴백)
  logging_setup.py  # 앱 로거 설정 — 부팅 요약·진단 결과를 프로세스 로그로 남긴다
  services/     #   bootstrap(부팅 시 데이터 준비), seeding, runtime_tick(자동 갱신용 데이터 연장), motors, company, events, diagnosis, admin(기본 테이블 CRUD)
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

동작하는 것: 로그인/인증, 런타임 데모 데이터 부트스트랩(COMP-001 200대 포함), 메인 대시보드(상단 요약 §3.1 · 조치 배너 · 정비 완료 확인 · 모터 카드 §3.2 · 이벤트 리스트 §3.3), 모터 그래프(지표별 추이 · 상태/위치/모델 필터 · 임계선), 모터 현황(이름·ID 검색 · 상태/위치 그룹핑), 모터 상세(§4), **LangGraph 진단 에이전트**(리포트 AI 진단 4섹션), 리포트 제공(PDF 우선, 불가 시 HTML).

**첫 리포트 열람은 몇 초 걸립니다.** 진단은 리포트를 열 때 생성되며(부팅 경로에는 LLM 호출이 없습니다), 프로세스 최초 열람이 실측 5~9초(LangGraph 콜드 import 3.17초 포함), 이후 4초대, 재열람은 캐시로 0.03초입니다. API 키가 없거나 LLM이 실패하면 규칙 기반 진단으로 폴백하고, 리포트의 진단 모델 라벨이 "규칙 기반 진단 (LLM 미사용)"으로 바뀝니다. `DIAGNOSIS_LLM_ENABLED=false`로 강제 오프할 수 있습니다.

**자동 갱신 (2026-08-11)**: 메인 대시보드와 모터 상세가 `st.fragment(run_every=10s)`로 그 영역만 다시 그립니다. 시드는 실행 시각까지만 채우므로 런타임 틱(`services/runtime_tick.py`)이 경과분을 이어 붙여 숫자와 그래프가 실제로 움직입니다. 화면 위에 다음 갱신까지 남은 초가 표시됩니다. 틱은 값만 흔들 뿐 **상태를 바꾸지 않습니다** — 실시간 전이 판정은 MVP 범위 밖이라, 임계를 넘겨 버리면 카드 색은 바뀌는데 이벤트 기록이 없는 어긋난 화면이 되기 때문입니다. 표시되는 카드 20장 중 17장은 수집 주기가 300초라 5분마다 값이 바뀝니다.

**관리자 페이지 (2026-08-11)**: 상단 내비의 `관리자`에서 담당자 · 모터 · 지표 임계값을 등록/수정/삭제합니다. 고객 회사 탭은 2026-08-12부터 **조회 전용**입니다(회사명 변경은 계약 처리라 화면에서 다루지 않습니다). 로그인한 회사의 데이터만 보입니다. **여기서 입력한 내용은 재시드로 초기화됩니다** — 앱을 2시간 이상 껐다 열거나 배포본이 재시작하면 데모 데이터가 새로 만들어지기 때문입니다. 종전에는 화면 상단 경고 박스가 이 사실을 알렸지만 2026-08-12에 제거했고(화면 정리), 지금은 이 문서와 `05_ui_screens.md` §6.2에만 남습니다. 모터를 지우면 딸린 텔레메트리·상태로그·알림이 함께 삭제되며, 확인 창이 건수를 먼저 보여줍니다. **임계값을 바꾸면 다음 수집분부터 카드 색과 요약 타일은 바뀌지만 이벤트·리포트·알림은 새로 생기지 않습니다** — 상태 전이 감지가 MVP 범위 밖이기 때문이며, 화면이 그 사실을 직접 안내합니다(2026-08-12 추가). 자세한 내용은 `05_ui_screens.md` §6.

**MVP 범위 밖 (정식 서비스 개발 시 적용)**:
- 알림 실제 발송(KAKAO/SMS/EMAIL 어댑터) — MVP는 시연용 `notification_logs` 샘플까지 (2026-08-10 확정)
- 48시간 보관 배치 — 데모 DB는 부팅 때 재생성되어 넘칠 구간이 없다 (2026-08-10 확정)
- **실시간 상태 전이 감지 · 통신 두절 판정** — 상시 실행 경로가 필요한데 Streamlit Community Cloud에는 백그라운드 프로세스가 없어 설계 결정이 선행돼야 한다 (2026-08-11 확정)

상세 추적은 [`.claude/docs/plan/remaining_work.md`](.claude/docs/plan/remaining_work.md).
