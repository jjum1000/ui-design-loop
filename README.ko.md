# ui-design-loop

Unity uGUI 프로젝트의 UI 현황을 감사해서, 둘러볼 수 있는 카탈로그와 에이전트가 읽는 디자인 시스템 색인으로 만들고,
그 위에서 새 화면을 설계(와이어 → 스키닝 목업)하고 리뷰어 피드백을 받아 고치는 루프입니다.
일은 Claude Code 가 하고, 사람은 몇 개의 관문에서 결정합니다.

> [!IMPORTANT]
> **알려진 한계 (v0.1)**
> - **카탈로그 페이지·생성 문서·CLI 출력은 v0.1 에서 한국어만 지원합니다.** 스킬·README·코드 문서는 영어입니다. 출력 다국어화는 후속 계획입니다.
> - Unity **uGUI**(프리팹 YAML) 전용입니다. UI Toolkit 은 지원하지 않습니다.
> - Unity 배치 렌더(썸네일·배치 맵)는 **Windows** 에서만 확인했습니다. 다른 OS 는 `UNITY_EXE` 로 에디터 실행 파일을 지정하세요.
> - 리뷰 뷰어의 브라우저 e2e 테스트는 v0.1 에 포함되지 않습니다(주요 경로는 스모크 테스트가 확인).

## 하는 일

```
Unity 프로젝트 ──► A1 수집 ─► A2 분류 ─► A3 통합 ─► H2 ─► A4 토큰 ─► H3 ─► A5 카탈로그 ─► A6 검증 ─► F 보고
  (uGUI 프리팹)     (프리팹 YAML 파서, GUID 색인, 중첩 프리팹 펼치기)            사람 관문: H1 · H2 · H3
               └─► 템플릿 카탈로그(어떤 프리팹이 어디서 재사용되는지, 오버라이드, 유사품, 썸네일)
               └─► 화면 배치 맵(렌더된 화면 + 노드마다 사각형)                    ──► HTML 탐색기
               └─► 에이전트용 디자인 시스템 색인(Docs/ui-design-system/INDEX.md, templates.jsonl, screens.jsonl)
                                     │
                                     ▼
              /ui-wire-skin: 기능 정의 → 와이어 → 디자인 시스템으로 스키닝한 HTML 목업
                                     │
                                     ▼
              /ui-feedback: 리뷰 뷰어에서 컴포넌트별 피드백 → Claude 가 claim·수정·측정·개정 기록
```

모든 것이 평범한 파일입니다: Python 스크립트(표준 라이브러리 + PyYAML/Pillow), JSON 데이터, 정적 HTML(`file://` 로 열림),
그리고 피드백 루프용 작은 로컬 HTTP 서버(선택).

## 필요한 것

- Python 3.10+ 와 `pip install pyyaml pillow`
- uGUI 를 쓰는 Unity 2022.3 / 6.x 프로젝트 — 렌더러에만 필요하고, 감사 자체는 파일만 읽습니다
- 스킬용 [Claude Code](https://claude.com/claude-code)
- 선택: `pip install playwright && python -m playwright install chromium` — `/ui-wire-skin` 측정 스크립트, `/ui-feedback` 의
  claim/revise 스냅숏, 리뷰 도크의 컴포넌트 크롭, 브라우저 스모크 테스트

## 샘플 프로젝트로 해 보기

```bash
git clone https://github.com/jjum1000/ui-design-loop
cd ui-design-loop
python examples/run_demo.py                # 1~2분: 툴킷을 examples/sample-project/ui-audit 에 설치하고 전체 파이프라인 실행
python examples/run_demo.py --with-unity   # 2~3분: 위와 같고, Unity 로 썸네일·화면 배치 맵까지 렌더
```

`--with-unity` 없이(Unity 불필요) 돌리면 카탈로그는 동작하지만 그림 자리는 모두 «썸네일 없음»·«배치 맵 없음» 자리표시이고
화면 맵 페이지는 비어 있습니다. Unity(`examples/sample-project/ProjectSettings/ProjectVersion.txt` 의 버전, Hub 기본 폴더 또는
`UNITY_EXE`)가 있으면 같은 페이지에 실제 렌더가 나옵니다. 샘플 프로젝트를 연 에디터는 먼저 닫으세요.
데모(와 테스트)를 다시 돌리면 결과를 처음부터 다시 만듭니다.

브라우저로 이 순서대로 여세요:
1. `examples/sample-project/ui-audit/catalog/app-flow.html` — 탐색기 홈: 앱 아이콘 → 화면 → 다음 화면
2. `.../catalog/templates.html` — 템플릿으로 재사용되는 프리팹, 쓰이는 곳, 오버라이드
3. `.../catalog/map.html` — 렌더된 화면과 노드마다 상자(`--with-unity` 필요)
4. `.../catalog/index.html` — 감사 카탈로그(A5): 파편화 지표·그룹·토큰

리뷰 뷰어는 로컬 서버가 필요합니다:

```bash
python examples/sample-project/ui-audit/scripts/review_server.py      # Ctrl+C 로 종료, --port N 으로 포트 변경
# → http://127.0.0.1:8770/ui-audit/catalog/review.html?screen=ShopView&stage=wire     (stage=wire | mockup)
```

와이어에서 컴포넌트를 누르고 이름과 의견을 적어 «남기기» 를 누르세요. Playwright 가 있으면 데모가 하단 도크(«도크» 버튼)의
컴포넌트 크롭도 만듭니다.

## 내 프로젝트에 쓰기

1. Claude Code 에 **플러그인(스킬) 설치**:
   ```
   /plugin marketplace add jjum1000/ui-design-loop
   /plugin install ui-design-loop@ui-design-loop
   ```
2. Unity 프로젝트에 **툴킷 설치**(`<project>/ui-audit/` 생성):
   ```bash
   python install.py --target <unity-프로젝트>/ui-audit
   python install.py --target <unity-프로젝트>/ui-audit --check     # 나중에: 설치 파일이 바뀌지 않았는지 확인
   ```
   업데이트는 새 태그에서 다시 실행합니다. 설치기는 자기가 설치한 파일(`ui-audit/toolkit.lock.json` 에 기록)만 쓰고
   `project.json`·데이터·프로젝트 전용 스크립트는 건드리지 않습니다.
3. **렌더러 패키지**(에디터 전용)를 `Packages/manifest.json` 에 추가:
   ```json
   "com.ui-design-loop.bridge": "https://github.com/jjum1000/ui-design-loop.git?path=/unity#v0.1.0"
   ```
4. `ui-audit/project.json` **설정** — [docs/project-json.md](docs/project-json.md) 참고.
5. Claude Code 에서 **`ui-audit`** 스킬("UI 오딧 시작")을 실행하고 관문을 따라갑니다. `state.py render` 가 늘 다음 행동을 알려 주고,
   `run_audit.ps1` / `run_audit.sh` 가 에이전트 단계를 자동으로 돌립니다.

## 스킬

| 스킬 | 용도 |
|---|---|
| `ui-audit` | 작업 공간 준비와 감사 A0 → F(수집·분류·통합·토큰·카탈로그·검증·보고) |
| `ui-design-system` | 새 화면을 만들기 전에 생성된 디자인 시스템 색인을 읽고, 색인을 다시 만든다 |
| `ui-wire-skin` | 새 화면 설계: 기능 정의 → 와이어 → 스키닝 목업 → 측정 → 리뷰 |
| `ui-feedback` | 리뷰 뷰어에 남은 피드백 처리: claim → 수정 → 측정 → 개정 기록 |

## 저장소 구조

```
.claude-plugin/   플러그인·마켓플레이스 매니페스트
skills/           스킬 4개
toolkit/          install.py 가 <project>/ui-audit/ 로 복사하는 것(스크립트·스키마·단계 명세·에이전트 지시문 원본·카탈로그 에셋)
unity/            에디터 전용 UPM 패키지: 썸네일·배치 맵 배치 렌더러
install.py        SHA-256 lock 을 남기는 벤더링 설치기
examples/         샘플 uGUI 프로젝트(직접 그린 CC0 도형) + run_demo.py
tests/            설치 테스트, 스모크 테스트, 셀프테스트 실행기
docs/             구조, project.json 레퍼런스, 피드백 루프, 교훈
```

## 테스트

```bash
python tests/run_all.py                # 2~3분: 설치 테스트 + 샘플 프로젝트 대상 모든 스크립트 셀프테스트 + 스모크 테스트
python tests/run_all.py --with-unity   # 같고, 안의 샘플 데모가 Unity 렌더까지
```

테스트는 샘플 데모 결과를 다시 만듭니다(렌더 그림을 유지하려면 `--with-unity`).

## 라이선스

MIT — [LICENSE](LICENSE). 샘플 프로젝트의 그림은 직접 만든 것으로 CC0 입니다.
