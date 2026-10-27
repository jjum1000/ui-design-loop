"""T5 리뷰 뷰어 페이지(catalog/review.html) 빌더 — 설계 산출물 위에서 컴포넌트를 골라 피드백을 남기고 이력을 본다.

출처: feedback/CONTRACT.md 4.5(뷰어 URL·동작) · 2절(registry) · 4.1(접은 상태) · 4.3(서버 API) · 5절(data-area) · 6절(권한)
      · 7.5(개정 L 하단 도크 — 트리·확대 뷰·라이브러리, DOM 계약 표의 id 를 이 골격이 만든다).
      design/2026-10-22-design-feedback-loop-plan.md 단계 3 · design/2026-10-23-component-dock-milestone.md 1절.

사용(오케스트레이터가 build_catalog 에 통합하기 전 단독 실행):
  python -c "import sys; sys.path.insert(0,'ui-audit/scripts'); import build_catalog as B, catalog_review as R; R.build_review(B, 'ui-audit/catalog')"
  → ui-audit/catalog/review.html.tmp (이어서 validate.py --rename catalog 또는 손으로 rename)

페이지는 정적 골격만 담고, 동작은 손으로 관리하는 catalog/assets/review.js · review.css 가 한다(catalog_assets.py 가 덮어쓰지 않음).
빌드 시점의 design/registry.json 을 <script type="application/json" id="rv-registry"> 로 심는다 — 서버 응답이나 state.js 에
registry 가 있으면 그쪽이 우선이고, 심은 값은 둘 다 없을 때(서버 꺼짐·state.js 없음)의 폴백이다.

한계:
- 셸 내비(TEMPLATE_NAV)는 build_catalog.build() 가 채운다. 이 함수만 단독으로 부르면 상단 내비에 템플릿 탐색기 링크가 빠진다.
- registry 가 바뀌면 다시 빌드해야 폴백이 최신이 된다(서버·state.js 경로는 런타임 값을 쓰므로 무관).
"""
import json
import os

import common as C

TITLE = "리뷰 뷰어"


def _registry_json():
    """design/registry.json 을 <script> 안에 넣을 수 있는 JSON 문자열로(`</` 이스케이프). 없으면 빈 등록부."""
    reg = C.load_json(C.p("design", "registry.json"), None) or {"version": 1, "screens": {}}
    return json.dumps(reg, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")


BODY = """<link rel="stylesheet" href="assets/review.css">
<div class="rv" id="rv">
 <div class="rv-bar">
  <div class="rv-name"><b id="rv-screen">—</b><span class="mut" id="rv-app"></span></div>
  <nav class="rv-tabs" id="rv-tabs" aria-label="단계"></nav>
  <div class="rv-states" id="rv-states" role="group" aria-label="화면 상태"></div>
  <div class="seg rv-mode" id="rv-mode" role="group" aria-label="모드">
   <button type="button" data-mode="select" class="on" title="산출물을 눌러 컴포넌트를 고른다">선택</button>
   <button type="button" data-mode="interact" title="산출물을 그대로 조작한다">조작</button>
  </div>
  <div class="seg rv-view" role="group" aria-label="표시 범위">
   <button type="button" data-view="game" class="on" title="산출물의 #canvas(1280×720 게임 화면)만">게임 화면</button><button type="button" data-view="doc" title="산출물 문서의 내용 경계 전체">문서 전체</button>
  </div>
  <div class="seg rv-zoom" role="group" aria-label="배율">
   <button type="button" data-zoom="fit" class="on">맞춤</button><button type="button" data-zoom="1">100%</button>
  </div>
  <button type="button" class="rv-docktoggle" id="rv-docktoggle" aria-expanded="false" aria-controls="rv-dock" title="하단 도크(트리·컴포넌트·라이브러리) 열기/닫기">도크</button>
  <button type="button" class="rv-paneltoggle" id="rv-paneltoggle" aria-expanded="false" aria-controls="rv-panel">패널</button>
 </div>
 <div class="rv-msg hidden" id="rv-msg" role="status"></div>
 <div class="rv-body">
  <div class="rv-viewport" id="rv-viewport">
   <div class="rv-sizer" id="rv-sizer">
    <div class="rv-scaler" id="rv-scaler">
     <iframe id="rv-frame" title="설계 산출물"></iframe>
     <div class="rv-overlay" id="rv-overlay"><div class="rv-hl rv-hover hidden" id="rv-hover"><span></span></div></div>
    </div>
   </div>
  </div>
  <aside class="rv-panel" id="rv-panel" aria-label="피드백 패널">
   <div class="rv-guide hidden" id="rv-guide"></div>
   <section class="rv-sec" id="rv-target-sec"><h3>선택</h3><div id="rv-target" class="rv-target mut">산출물에서 컴포넌트를 누르거나 하단 도크 트리에서 고른다.</div></section>
   <section class="rv-sec" id="rv-form-sec">
    <h3>새 피드백</h3>
    <form id="rv-form" class="rv-form" autocomplete="off">
     <label class="rv-author">이름 <input id="rv-author" type="text" maxlength="40" placeholder="작성자 이름(브라우저에 기억)"></label>
     <div class="rv-kinds" id="rv-kinds" role="radiogroup" aria-label="종류"></div>
     <div class="rv-suggest hidden" id="rv-suggest"><span class="lb" id="rv-suggest-label"></span><button type="button" class="rv-x" id="rv-suggest-clear" title="교체 제안 지우기">지우기</button></div>
     <textarea id="rv-text" rows="3" maxlength="4000" placeholder="무엇이 문제인지, 어떻게 바뀌면 좋을지"></textarea>
     <div class="rv-formrow"><span class="mut" id="rv-formhint">컴포넌트를 먼저 고른다.</span><button type="submit" id="rv-submit" disabled>남기기</button></div>
    </form>
   </section>
   <section class="rv-sec"><h3>스레드</h3><div id="rv-thread"></div></section>
   <section class="rv-sec"><h3>피드백 색인 <span class="n" id="rv-compn"></span></h3><div id="rv-comps" class="rv-comps"></div></section>
   <section class="rv-sec rv-refsec"><h3>다른 단계·시안(참고)</h3><div id="rv-ref"></div></section>
  </aside>
 </div>
 <section class="rv-dock hidden" id="rv-dock" aria-label="컴포넌트 도크">
  <div class="rv-dock-grip" id="rv-dock-grip" role="separator" aria-orientation="horizontal" aria-label="도크 높이" title="끌어서 높이 조절"></div>
  <div class="rv-dock-head">
   <nav class="rv-dock-crumb" id="rv-dock-crumb" aria-label="경로"></nav>
   <span class="rv-dock-note hidden" id="rv-dock-note" role="status"></span>
   <span class="mut rv-dock-keys">↑ 부모 · ↓ 첫 자식 · ←→ 형제</span>
   <button type="button" class="rv-x" id="rv-dock-fold" aria-expanded="true" aria-controls="rv-dock-cols">접기</button>
  </div>
  <div class="rv-dock-cols" id="rv-dock-cols">
   <div class="rv-dock-col rv-dock-treecol"><h4>① 트리</h4><div id="rv-dock-tree" class="rv-tree" role="tree" aria-label="의미 노드 트리"></div></div>
   <div class="rv-dock-col rv-dock-view"><h4>② 컴포넌트</h4>
    <div id="rv-zoom" class="rv-zv" data-mode="none"><div class="rv-zoom-stage" id="rv-zoom-stage"><img id="rv-zoom-img" class="hidden" alt="확대(크롭)"><span class="mut rv-zoom-none" id="rv-zoom-none">확대 이미지 없음</span></div></div>
    <div class="rv-zrail">
     <table class="rv-props" id="rv-props"><tbody>
      <tr data-prop="area"><th>area</th><td>—</td></tr><tr data-prop="template"><th>template</th><td>—</td></tr>
      <tr data-prop="variant"><th>variant</th><td>—</td></tr><tr data-prop="new"><th>new</th><td>—</td></tr>
      <tr data-prop="size"><th>크기</th><td>—</td></tr><tr data-prop="pos"><th>좌표</th><td>—</td></tr><tr data-prop="src"><th>소스</th><td>—</td></tr>
     </tbody></table>
     <h5 class="rv-zh">같은 키 · 다른 상태·시안</h5>
     <div class="rv-strip" id="rv-strip"></div>
    </div>
   </div>
   <div class="rv-dock-col rv-dock-lib" id="rv-dock-lib" data-state="none"></div>
  </div>
 </section>
</div>
<script type="application/json" id="rv-registry">@@REGISTRY@@</script>@@CONFIG@@
<script src="assets/review.js"></script>
"""


def _config_html():
    """project.json publish.team_server(팀 공유 리뷰 서버 주소)가 있으면 #rv-config 로 심는다 — file:// 열람 때 링크로 쓴다."""
    team = ((C.project() or {}).get("publish") or {}).get("team_server")
    if not team:
        return ""
    cfg = json.dumps({"teamServer": team}, ensure_ascii=False).replace("</", "<\\/")
    return '<script type="application/json" id="rv-config">%s</script>' % cfg


def build_review(B, out):
    """catalog/review.html.tmp 를 쓴다. B = build_catalog 모듈(page·write 사용)."""
    body = BODY.replace("@@REGISTRY@@", _registry_json()).replace("@@CONFIG@@", _config_html())
    B.write(out, "review.html", B.page(TITLE, body, crumbs=[("앱 흐름", "app-flow.html")], wide=True))
    return os.path.join(out, "review.html.tmp")
