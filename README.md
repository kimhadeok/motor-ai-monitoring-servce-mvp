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

# 3. 앱 실행 (최초 실행 시 SQLite 스키마 자동 생성)
uv run streamlit run main.py
```

## 시연용 데이터 생성 (최초 1회, 로컬에서만 실행)

이 프로젝트는 Streamlit Community Cloud에 배포합니다. Community Cloud는 재배포/재시작 시 로컬 파일시스템이 초기화될 수 있어, 런타임에 관리자 페이지로 데이터를 채우는 대신 **배포 전 로컬에서 시드 스크립트를 1회 실행하고 그 결과물을 git에 커밋**하는 방식을 사용합니다.

```bash
uv run python scripts/seed_data.py
```

실행하면 `data/app.db`(SQLite), `data/chroma/`(ChromaDB persist 디렉터리)가 생성/갱신됩니다. 완료 후 반드시 커밋하세요.

> ⚠️ **Windows 로컬에서 PDF(`report_pdf`) 생성이 실패하는 경우**: WeasyPrint는 Pango/Cairo/GLib 네이티브 라이브러리가 필요한데, Windows에는 기본으로 없습니다. 시드 스크립트는 PDF 생성 실패를 무시하고 나머지 데이터는 정상 시딩하도록 되어 있습니다(`report_pdf`만 NULL로 남음). 로컬에서 PDF까지 포함해 완전히 테스트하려면 WSL/Docker(Linux 컨테이너)에서 실행하거나 GTK3 런타임을 설치하세요. Streamlit Community Cloud는 `packages.txt`로 이 문제가 해결됩니다.

```bash
git add data/app.db data/chroma/
git commit -m "chore: 시연용 데이터 갱신"
```

> ⚠️ `data/app.db`, `data/chroma/`는 `.gitignore`에 추가하지 마세요 — 의도적으로 커밋해야 하는 파일입니다.

## 배포 (Streamlit Community Cloud)

1. `uv export --format requirements-txt --no-dev --no-hashes -o requirements.txt` 로 배포용 `requirements.txt`를 최신 상태로 갱신 후 커밋 (uv/pyproject.toml 변경 시마다 재실행).
2. Community Cloud 앱 설정의 **Secrets**에 `.streamlit/secrets.toml.example` 내용을 참고해 `OPENAI_API_KEY` 등을 입력.
3. `packages.txt`(WeasyPrint용 apt 패키지)가 저장소 루트에 있는지 확인 — 없으면 PDF 생성이 빌드/런타임에 실패합니다.
4. 배포 시점에 Python 3.14가 지원되지 않으면 `runtime.txt`로 지원 버전을 별도 지정해야 할 수 있습니다.

## 프로젝트 구조

```
app/            # 애플리케이션 코드 (config, db, rag, auth, reports, ui, pages)
data/           # 시드 스크립트 산출물 — SQLite DB, ChromaDB persist 디렉터리 (git 커밋 대상)
scripts/        # 1회성 로컬 스크립트 (seed_data.py)
.claude/docs/generated/  # 확정 사양 문서 (단일 소스 오브 트루스)
```

## 현재 범위

이 저장소는 스캐폴딩 단계입니다 — 폴더 구조, 문서-스키마 정합성, 로그인/DB 초기화가 동작하는 최소 뼈대, 시연용 시드 데이터까지가 범위입니다. 실제 AI 에이전트 진단 로직과 대시보드 실데이터 렌더링은 이후 별도 작업으로 구현합니다.
