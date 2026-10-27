/* 리뷰 뷰어(catalog/review.html) — 손으로 관리하는 원본. catalog_assets.py 가 덮어쓰지 않는다.
   계약: ui-audit/feedback/CONTRACT.md 4.5 · 2절(registry states.steps) · 4.1(접은 상태) · 4.3(서버 API) · 5절(data-area) · 6절(권한).
   - 저장된 텍스트(원문·코멘트·요약·키·셀렉터 등)는 전부 textContent/createElement 로 넣는다. innerHTML 에 데이터 문자열 금지.
   - 산출물 파일은 건드리지 않는다. 오버레이는 부모 문서(iframe 위)에 그리고, 히트 테스트는 iframe 문서의 elementFromPoint 로 한다.
   - bbox 는 스케일 전 iframe 문서 좌표(CSS px). iframe 폭은 CLI 크롭 샷(4.4)과 같은 1920 으로 고정한다.
   - 개정 L(7.5): 하단 도크 = ① 의미 노드 트리 ② 확대 뷰·속성표·비교 띠 ③ 템플릿 라이브러리 카드. 선택은 노드 단위이고
     open 에 path(7.1)·suggest(kind=template) 를 넣는다. 라이브러리·키 데이터(7.4)는 <script> 지연 로드, 문자열은 전부 textContent. */
(function () {
  'use strict';
  var W = 1920, H0 = 1080, HMAX = 8000;
  var KINDS = [['bug', '버그'], ['visual', '미감'], ['copy', '카피'], ['flow', '동선'], ['other', '기타'], ['template', '템플릿 교체']];
  var KIND_L = {}; KINDS.forEach(function (k) { KIND_L[k[0]] = k[1]; });
  var STATUS_L = { open: '열림', reopened: '다시 열림', claimed: '작업 중', fixed: '검토 대기', closed: '닫힘' };
  var TYPE_L = { open: '피드백', comment: '코멘트', claim: '작업 시작', release: '작업 해제', revision: '수정', close: '닫기', reopen: '다시 열기' };
  var BY_L = { user: '사용자', claude: 'Claude' };
  var STAGE_STATUS_L = { wip: '작업 중', done: '완료', confirmed: '확정' };
  var KEY_RE = /^[a-z0-9][a-z0-9-]*$/;
  var CALL_RE = /^[A-Za-z_$][\w$]*$/;
  var CALL_DENY = { eval: 1, Function: 1, setTimeout: 1, setInterval: 1, execScript: 1 };
  var SERVER_CMD = 'python ui-audit/scripts/review_server.py';
  /* 팀 공유 리뷰 서버(개정 A) — project.json publish.team_server 를 빌드가 review.html 의 #rv-config 에 심는다(없으면 null) */
  var TEAM_SERVER = (function () {
    try { return JSON.parse(document.getElementById('rv-config').textContent).teamServer || null; } catch (e) { return null; }
  })();

  var Q = new URLSearchParams(location.search);
  var SCREEN = Q.get('screen') || '', STAGE = Q.get('stage') || '', VER = Q.get('v') || '', FB = Q.get('fb') || '', STATE0 = Q.get('state') || '';
  var KEY0 = KEY_RE.test(Q.get('k') || '') ? Q.get('k') : '';  /* 7.5: 시안 이동 뒤 선택 유지 */
  var HTTP = /^https?:$/.test(location.protocol);

  var S = {
    data: { items: {}, revisions: {}, counts: {} }, hasData: false, registry: null, screen: null, stage: null,
    readOnly: true, roReason: '', access: false, doc: null, win: null, state: null, mode: 'select', zoom: 'fit',
    scale: 1, H: H0, sel: null, hoverPt: null, mo: null, raf: 0, listTimer: 0, pendingFb: FB, kind: 'visual', busy: false,
    /* 도크(7.5) */
    tree: null, byId: {}, elMap: null, treeOpen: {}, suggest: null, missingKey: null, fileState: null, frameDone: false,
    lib: { index: null, keys: null, idxSt: 'loading', keysSt: 'loading', cards: {}, base: null, stack: [], override: null, sig: '' },
    zf: { frame: null, win: null, doc: null, ready: false, state: null }
  };
  var $ = function (id) { return document.getElementById(id); };
  var vp, sizer, scaler, frame, overlay, hoverBox;

  /* ---------------------------------------------------------------- DOM 도우미 */
  function h(tag, attrs) {
    var el = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      var v = attrs[k];
      if (v == null || v === false) return;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (/^on[a-z]+$/.test(k) && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : String(v));
    });
    add.apply(null, [el].concat([].slice.call(arguments, 2)));
    return el;
  }
  function add(el) {
    for (var i = 1; i < arguments.length; i++) {
      var kid = arguments[i];
      if (kid == null || kid === false) continue;
      if (Array.isArray(kid)) { kid.forEach(function (k) { add(el, k); }); continue; }
      el.appendChild(typeof kid === 'string' || typeof kid === 'number' ? document.createTextNode(String(kid)) : kid);
    }
  }
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }
  function msg(text, kind) {
    var m = $('rv-msg');
    m.textContent = text || '';
    m.className = 'rv-msg' + (kind ? ' ' + kind : '') + (text ? '' : ' hidden');
  }
  function fmtAt(at) { return typeof at === 'string' && at.length >= 19 ? at.slice(5, 10) + ' ' + at.slice(11, 19) : String(at || ''); }
  function badge(status) { return h('span', { class: 'rv-badge st-' + status, text: STATUS_L[status] || status }); }
  function esc(s) { return window.CSS && CSS.escape ? CSS.escape(s) : String(s).replace(/["\\]/g, '\\$&'); }

  /* ---------------------------------------------------------------- 데이터 */
  function embeddedRegistry() {
    try { return JSON.parse($('rv-registry').textContent || '{}'); } catch (e) { return { screens: {} }; }
  }
  function loadStateJs() {
    return new Promise(function (res) {
      if (window.UIA_FEEDBACK) { res(window.UIA_FEEDBACK); return; }
      var s = document.createElement('script');
      s.src = '../feedback/state.js';
      s.onload = function () { res(window.UIA_FEEDBACK || null); };
      s.onerror = function () { res(null); };
      document.head.appendChild(s);
    });
  }
  function fetchApi() {
    return fetch('/api/feedback?screen=' + encodeURIComponent(SCREEN), { cache: 'no-store', headers: { Accept: 'application/json' } })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); });
  }
  function loadData() {
    if (HTTP) {
      return fetchApi().then(function (d) { S.readOnly = false; return d; }).catch(function (e) {
        S.readOnly = true; S.roReason = 'api';
        S.apiErr = e && e.message ? e.message : String(e);
        return loadStateJs();
      });
    }
    S.readOnly = true; S.roReason = 'file';
    return loadStateJs();
  }
  function setData(d) {
    S.hasData = !!d;
    d = d || {};
    S.data = { items: d.items || {}, revisions: d.revisions || {}, counts: d.counts || {},
      versionCounts: d.versionCounts && typeof d.versionCounts === 'object' ? d.versionCounts : null };
    if (d.registry && d.registry.screens) S.registry = d.registry;
  }
  /* 다시 받기. 성공 여부(true/false)로 끝나고 거부하지 않는다 — 메시지는 호출자가 정한다 */
  function refresh() {
    if (!HTTP || S.readOnly) return Promise.resolve(false);
    return fetchApi().then(function (d) {
      if (!d || typeof d !== 'object' || !d.items) throw new Error('응답 형식 오류');
      setData(d); renderAll(); return true;
    }).catch(function () { return false; });
  }
  function screenItems() {
    var out = [];
    Object.keys(S.data.items).forEach(function (k) { var it = S.data.items[k]; if (it && it.screen === SCREEN) out.push(it); });
    out.sort(function (a, b) { return String(a.openedAt || '').localeCompare(String(b.openedAt || '')) || String(a.id).localeCompare(String(b.id)); });
    return out;
  }
  /* 현재 대상 = (stage, version) — 개정 V. 같은 stage 의 다른 시안은 참고 */
  function isCur(it) { return !!it && it.stage === STAGE && it.version === VER; }
  function curItems() { return screenItems().filter(isCur); }
  function refItems() { return screenItems().filter(function (it) { return !isCur(it); }); }
  function isOpen(it) { return it.status === 'open' || it.status === 'reopened'; }
  /* 그 stage 의 시안 목록(등록부 순서, 첫 항목 = 기본 시안) */
  function variantsOf(name) { return (S.screen.stages || []).filter(function (s) { return s.stage === name; }); }
  /* (stage, version) 의 등록부 항목. version 이 없으면 기본 시안, 등록 안 된 version 이면 null */
  function stageOf(name, ver) {
    var vs = variantsOf(name);
    if (!ver) return vs[0] || null;
    return vs.filter(function (s) { return s.version === ver; })[0] || null;
  }
  function stageNames() {
    var seen = {}, out = [];
    (S.screen.stages || []).forEach(function (s) { if (!seen[s.stage]) { seen[s.stage] = 1; out.push(s.stage); } });
    return out;
  }
  function variantLabel(st) { return st ? (st.label || st.stage) : ''; }
  function reviewUrl(stage, ver, fb) {
    return 'review.html?screen=' + encodeURIComponent(SCREEN) + '&stage=' + encodeURIComponent(stage) +
      (ver ? '&v=' + encodeURIComponent(ver) : '') + (fb ? '&fb=' + encodeURIComponent(fb) : '');
  }
  /* 7.5: 시안·단계 이동 링크에 현재 선택 키(&k=)를 붙인다 */
  function kParam() { return S.sel && S.sel.component ? '&k=' + encodeURIComponent(S.sel.component) : ''; }
  function updateTabHrefs() {
    document.querySelectorAll('a.rv-tab[data-stage]').forEach(function (a) {
      var name = a.getAttribute('data-stage');
      a.setAttribute('href', reviewUrl(name, name === STAGE ? VER : null) + kParam());
    });
  }
  function stateDef(id) { return ((S.stage && S.stage.states) || []).filter(function (s) { return s.id === id; })[0] || null; }

  /* ---------------------------------------------------------------- 시작 */
  function init() {
    vp = $('rv-viewport'); sizer = $('rv-sizer'); scaler = $('rv-scaler'); frame = $('rv-frame');
    overlay = $('rv-overlay'); hoverBox = $('rv-hover');
    S.registry = embeddedRegistry();
    bindChrome();
    loadData().then(function (d) { setData(d); start(); });
  }

  function start() {
    var screens = (S.registry && S.registry.screens) || {};
    S.screen = screens[SCREEN] || null;
    if (!S.screen || !(S.screen.stages || []).length) { showIndex(screens); return; }
    var fbIt = FB ? S.data.items[FB] : null;
    if (!STAGE && fbIt) { STAGE = fbIt.stage; if (!VER && stageOf(fbIt.stage, fbIt.version)) VER = fbIt.version; }
    S.stage = stageOf(STAGE, VER) || stageOf(STAGE) || S.screen.stages[0];
    if (VER && S.stage.version !== VER) msg('시안 ' + VER + ' 은 등록부에 없다 — 기본 시안 ' + S.stage.version + ' 을 연다.', 'warn');
    STAGE = S.stage.stage; VER = S.stage.version;
    document.title = SCREEN + ' · ' + variantLabel(S.stage) + ' · 리뷰 뷰어';
    S.fileState = STATE0 && stateDef(STATE0) ? STATE0 : ((S.stage.states || [])[0] || {}).id || null;  /* file:// 도크 트리의 keys 상태 */
    renderKinds();
    guide();
    loadLib();
    frame.addEventListener('load', onFrameLoad);
    frame.src = '../' + S.stage.entry;
    renderAll();
    measure();
  }

  function showIndex(screens) {
    $('rv-screen').textContent = SCREEN ? SCREEN + ' — 등록부에 없음' : '리뷰할 화면을 고른다';
    var list = h('ul', { class: 'rv-index' });
    Object.keys(screens).sort().forEach(function (k) {
      var sc = screens[k];
      add(list, h('li', null, h('b', { text: k }), ' ', h('span', { class: 'mut', text: sc.label || '' }), ' ',
        (sc.stages || []).map(function (st) {
          return h('a', { class: 'tag', href: 'review.html?screen=' + encodeURIComponent(k) + '&stage=' + encodeURIComponent(st.stage) +
            '&v=' + encodeURIComponent(st.version), text: (st.label || st.stage) + ' · ' + st.version });
        })));
    });
    if (!list.firstChild) add(list, h('li', { class: 'mut', text: 'design/registry.json 에 등록된 화면이 없다.' }));
    clear(vp); add(vp, list);
    $('rv').classList.add('rv-noscreen');
  }

  function guide() {
    var g = $('rv-guide'), lines = [];
    if (S.readOnly) {
      $('rv-form-sec').classList.add('hidden');
      var url = 'http://127.0.0.1:8770/ui-audit/catalog/review.html' + location.search;
      if (S.roReason === 'file' && TEAM_SERVER) {
        var team = TEAM_SERVER + '/ui-audit/catalog/review.html' + location.search;
        lines.push(h('b', { text: '읽기 전용(file://)' }), ' — 피드백은 팀 서버에서 남긴다(로그가 한 곳에 모인다).');
        lines.push(h('div', { class: 'rv-cmd' }, '팀 서버: ', h('a', { href: team, text: team })));
      } else {
        lines.push(h('b', { text: '읽기 전용' }), ' — 서버 API 응답 없음(' + (S.apiErr || '?') + ').');
        lines.push(h('div', { class: 'rv-cmd' }, '서버 켜기: ', h('code', { text: SERVER_CMD }), ' → ', h('code', { text: url })));
      }
    }
    if (!S.hasData) lines.push(h('div', { class: 'warn', text: '피드백 데이터 없음' }));
    if (lines.length) { clear(g); add(g, lines); g.classList.remove('hidden'); } else g.classList.add('hidden');
  }

  /* ---------------------------------------------------------------- 상단 바 */
  /* 표시 모드(4.5): 'game' = 산출물 #canvas(1280×720)만, 'doc' = 문서 내용 경계. localStorage 로 기억(실패해도 동작) */
  var VIEW_KEY = 'uiaudit-review-view';
  function loadView() {
    var v = null;
    try { v = localStorage.getItem(VIEW_KEY); } catch (e) { v = null; }
    return v === 'doc' ? 'doc' : 'game';
  }
  function saveView(v) { try { localStorage.setItem(VIEW_KEY, v); } catch (e) { /* 저장 불가 — 이번 세션만 */ } }
  /* 작성자 이름(개정 A): 사용자 이벤트마다 author 로 보낸다. 브라우저별 기억(실패해도 이번 세션 입력값으로 동작) */
  var AUTHOR_KEY = 'uiaudit-review-author';
  function loadAuthor() { try { return localStorage.getItem(AUTHOR_KEY) || ''; } catch (e) { return ''; } }
  function saveAuthor(v) { try { localStorage.setItem(AUTHOR_KEY, v); } catch (e) { /* 이번 세션만 */ } }
  function author() { return $('rv-author').value.trim(); }
  /* 버튼 표시: 고른 모드(on) + 실제로 적용된 모드(game 을 골랐어도 #canvas 가 없으면 fallback) */
  function syncViewButtons() {
    document.querySelectorAll('.rv-view [data-view]').forEach(function (x) {
      var v = x.getAttribute('data-view');
      x.classList.toggle('on', v === S.view);
      if (v === 'game') {
        x.classList.toggle('fallback', S.view === 'game' && S.viewEff === 'doc');
        x.title = S.view === 'game' && S.viewEff === 'doc' ? '#canvas 없음 또는 DOM 접근 불가 — 문서 전체로 보인다' : '산출물의 #canvas(1280×720 게임 화면)만';
      }
    });
  }
  function bindChrome() {
    document.querySelectorAll('#rv-mode [data-mode]').forEach(function (b) {
      b.addEventListener('click', function () { if (!b.disabled) setMode(b.getAttribute('data-mode')); });
    });
    document.querySelectorAll('.rv-zoom [data-zoom]').forEach(function (b) {
      b.addEventListener('click', function () {
        S.zoom = b.getAttribute('data-zoom');
        document.querySelectorAll('.rv-zoom [data-zoom]').forEach(function (x) { x.classList.toggle('on', x === b); });
        measure(); schedule();
      });
    });
    S.view = loadView();
    document.querySelectorAll('.rv-view [data-view]').forEach(function (b) {
      b.addEventListener('click', function () {
        S.view = b.getAttribute('data-view');
        saveView(S.view);
        S.bounds = null;  /* 모드가 바뀌면 경계를 새로 잰다 */
        measure(); schedule(); vp.scrollTop = 0; vp.scrollLeft = 0;
      });
    });
    syncViewButtons();
    var pt = $('rv-paneltoggle');
    pt.addEventListener('click', function () {
      var open = !$('rv').classList.contains('panel-open');
      $('rv').classList.toggle('panel-open', open);
      pt.setAttribute('aria-expanded', open ? 'true' : 'false');
      measure(); schedule();
    });
    overlay.addEventListener('pointermove', function (e) { S.hoverPt = pt0(e); updateHover(); });
    overlay.addEventListener('pointerleave', function () { S.hoverPt = null; updateHover(); });
    overlay.addEventListener('click', function (e) { e.preventDefault(); var p = pt0(e); pickAt(p.x, p.y); });
    overlay.addEventListener('wheel', forwardWheel, { passive: false });
    $('rv-form').addEventListener('submit', function (e) { e.preventDefault(); submitOpen(); });
    $('rv-text').addEventListener('input', updateForm);
    S.formFiles = [];
    S.formPicker = attPicker(S.formFiles, $('rv-text'), $('rv-form-sec'));
    $('rv-form').insertBefore(S.formPicker.el, $('rv-form').querySelector('.rv-formrow'));
    $('rv-author').value = loadAuthor();
    $('rv-author').addEventListener('input', function () { saveAuthor(author()); updateForm(); });
    $('rv-suggest-clear').addEventListener('click', function () { setSuggest(null); });
    document.addEventListener('keydown', function (e) {
      var tg = e.target, typing = /^(TEXTAREA|INPUT|SELECT)$/.test((tg && tg.tagName) || '') || !!(tg && tg.isContentEditable);
      if (e.key === 'Escape' && S.sel && !typing) { setSel(null); return; }
      if (!typing && !e.altKey && !e.ctrlKey && !e.metaKey && /^Arrow(Up|Down|Left|Right)$/.test(e.key) && dockOpen()) {
        if (navSel(e.key)) e.preventDefault();
      }
    });
    bindDock();
    addEventListener('resize', function () { measure(); schedule(); });
  }
  function setMode(m) {
    S.mode = m;
    document.querySelectorAll('#rv-mode [data-mode]').forEach(function (x) { x.classList.toggle('on', x.getAttribute('data-mode') === m); });
    overlay.classList.toggle('interact', m !== 'select');
    S.hoverPt = null; updateHover();
  }
  function renderTabs() {
    var tabs = clear($('rv-tabs'));
    var vc = S.data.versionCounts ? S.data.versionCounts[SCREEN] || {} : null;  /* 구 서버면 null → 풀다운 숫자 생략 */
    stageNames().forEach(function (name) {
      var on = name === STAGE, vs = variantsOf(name), st = on ? S.stage : vs[0];
      var c = ((S.data.counts[SCREEN] || {})[name]) || null;  /* 탭 숫자 = stage 합(시안 합) */
      var openN = c ? (c.open || 0) + (c.reopened || 0) : null, fixN = c ? c.fixed || 0 : null;
      var wrap = h('span', { class: 'rv-tabwrap' + (on ? ' on' : ''), 'data-stage': name });
      add(wrap, h('a', { class: 'rv-tab' + (on ? ' on' : ''), href: reviewUrl(name, on ? VER : null) + kParam(),
        'aria-current': on ? 'page' : null, 'data-stage': name, title: variantLabel(st) + ' · ' + st.version + ' · ' + st.status },
        h('span', { class: 'lb', text: variantLabel(st) }), h('span', { class: 'v', text: st.version }),
        h('span', { class: 'stt', text: STAGE_STATUS_L[st.status] || st.status || '' }),
        h('span', { class: 'cnt', title: '열린 · 검토 대기(이 단계 시안 합)', text: (openN == null ? '—' : openN) + ' · ' + (fixN == null ? '—' : fixN) })));
      if (vs.length > 1) {
        var sel = h('select', { class: 'rv-variant', 'data-stage': name, 'aria-label': name + ' 시안', title: '시안 ' + vs.length + '개' });
        vs.forEach(function (v, i) {
          var cc = vc && vc[name] ? vc[name][v.version] : null;
          var openV = vc ? (cc ? (cc.open || 0) + (cc.reopened || 0) : 0) : null;
          var o = h('option', { value: v.version, text: variantLabel(v) + ' · ' + v.version + ' · ' + (STAGE_STATUS_L[v.status] || v.status || '') +
            (i === 0 ? ' · 기본' : '') + (openV == null ? '' : ' · 열린 ' + openV) });
          if (v.version === st.version) o.selected = true;
          add(sel, o);
        });
        sel.addEventListener('change', function () { location.href = reviewUrl(name, sel.value) + kParam(); });
        add(wrap, sel);
      }
      add(tabs, wrap);
    });
    $('rv-screen').textContent = SCREEN;
    $('rv-app').textContent = [S.screen.label, S.screen.app].filter(Boolean).join(' · ');
  }
  function renderStates() {
    var box = clear($('rv-states'));
    (S.stage.states || []).forEach(function (st) {
      add(box, h('button', { type: 'button', class: 'rv-state' + (st.id === S.state ? ' on' : ''), 'data-state': st.id,
        disabled: !S.access, title: S.access ? st.id : '산출물 DOM 접근 불가 — 상태 전환 불가', text: st.label || st.id,
        onclick: function () { enterState(st.id); } }));
    });
    document.querySelectorAll('#rv-mode [data-mode]').forEach(function (b) { b.disabled = !S.access; });
  }

  /* ---------------------------------------------------------------- iframe */
  function onFrameLoad() {
    var doc = null, win = null;
    try {
      win = frame.contentWindow;
      if (win && win.location.href === 'about:blank') return;
      doc = frame.contentDocument;
      if (!doc || !doc.body) doc = null;
    } catch (e) { doc = null; }
    if (S.mo) { try { S.mo.disconnect(); } catch (e) { /* 이전 문서 */ } S.mo = null; }
    S.doc = doc; S.win = doc ? win : null; S.access = !!doc; S.frameDone = true;
    S.tree = null; S.elMap = null;
    if (!S.access) {
      msg('산출물 DOM 에 접근할 수 없다(file:// 등) — 산출물 클릭·상태 전환 없이, 도크 트리는 키 데이터로 보인다.', 'warn');
      overlay.classList.add('noaccess');
      renderStates(); measure(); applyFb(); renderAll(); applyKey0();
      return;
    }
    overlay.classList.remove('noaccess');
    try {
      S.mo = new win.MutationObserver(schedule);
      S.mo.observe(doc.documentElement, { subtree: true, childList: true, attributes: true, characterData: true });
      doc.addEventListener('scroll', schedule, true);
      win.addEventListener('resize', schedule);
    } catch (e) { /* 관찰 실패 — 수동 갱신만 */ }
    var target = null, fbIt = S.pendingFb ? S.data.items[S.pendingFb] : null;
    if (STATE0 && stateDef(STATE0)) target = STATE0;
    else if (isCur(fbIt) && fbIt.state && stateDef(fbIt.state)) target = fbIt.state;
    else if ((S.stage.states || []).length) target = S.stage.states[0].id;
    STATE0 = '';
    if (target) enterState(target, true); else { renderStates(); measure(); }
    applyFb();
    renderAll();
    applyKey0();
  }

  /* fb 파라미터: 현재 stage 의 피드백이면 선택. 다른 stage 면 선택하지 않고(단계 사이 같은 키 = 다른 컴포넌트일 수 있다)
     그 stage 탭으로 가는 링크를 안내한다(자동 이동은 하지 않는다). 없는 id 면 그렇게 알린다. */
  function applyFb() {
    var id = S.pendingFb;
    if (!id) return;
    S.pendingFb = '';
    var it = S.data.items[id];
    if (it && it.screen === SCREEN && isCur(it)) { S.fbNotice = null; selectItem(it, true); return; }
    S.fbNotice = { id: id, item: it && it.screen === SCREEN ? it : null };
    renderTarget();
  }

  /* 등록부 steps 를 win 에서 순서대로 호출(eval 금지). 실패 사유 문자열 또는 null. 본 iframe·확대 iframe 이 같이 쓴다 */
  function runSteps(win, st) {
    var fail = null;
    (st.steps || []).some(function (step) {
      var name = step && step.call, fn = null;
      if (typeof name !== 'string' || !CALL_RE.test(name) || CALL_DENY[name]) { fail = '허용되지 않는 호출 ' + name; return true; }
      try { fn = win[name]; } catch (e) { fn = null; }
      if (typeof fn !== 'function') {
        if (step.optional) return false;
        fail = name + '() 없음'; return true;
      }
      try { fn.apply(win, Array.isArray(step.args) ? step.args.slice() : []); } catch (e) { fail = name + '(): ' + (e && e.message ? e.message : e); return true; }
      return false;
    });
    return fail;
  }
  function enterState(id, keepFb) {
    var st = stateDef(id);
    if (!st || !S.access) return false;
    var fail = runSteps(S.win, st);
    if (fail) { S.state = null; msg('상태 진입 실패 — ' + (st.label || id) + ': ' + fail, 'bad'); }
    else { S.state = id; if ($('rv-msg').classList.contains('bad')) msg(''); }
    try {
      Q.set('state', id);
      if (!keepFb) Q.delete('fb');
      history.replaceState(null, '', '?' + Q.toString());
    } catch (e) { /* file:// 등 */ }
    reanchorAfterState();
    renderStates();
    measure();
    schedule(true);
    return !fail;
  }

  /* 표시 범위(4.5): iframe 문서는 1920 폭 그대로 두고, 보이는 내용 경계(문서 좌표 합집합)만 잘라 보인다.
     scaler = scale(s) translate(-B.x, -B.y) → 문서 점 p 는 화면에서 (p - B)·s. 오버레이는 scaler 안이라 히트 테스트·bbox 는 그대로 문서 좌표. */
  function measure() {
    if (!frame) return;
    if (S.access) {
      try {
        var b = S.doc.body, cs = S.win.getComputedStyle(b);
        var mt = parseFloat(cs.marginTop) || 0, mb = parseFloat(cs.marginBottom) || 0;
        var hh = Math.max(b.scrollHeight + mt + mb, b.getBoundingClientRect().bottom + (S.win.scrollY || 0) + mb);
        S.H = Math.min(HMAX, Math.max(H0, Math.ceil(hh)));
      } catch (e) { /* 측정 실패 — 이전 높이 유지 */ }
      frame.style.width = W + 'px'; frame.style.height = S.H + 'px';  /* 경계는 이 크기에서 잰다 */
      var cb = S.view === 'game' ? canvasBounds() : null;
      S.viewEff = cb ? 'game' : 'doc';
      if (cb) S.bounds = cb;  /* 게임 화면: #canvas 사각형 그대로(상태 전환·재렌더로 옮겨지면 다음 측정에서 따라간다) */
      else {
        var nb = null;
        try { nb = contentBounds(); } catch (e) { nb = null; }
        if (!nb) nb = { x: 0, y: 0, w: W, h: S.H };
        var ob = S.bounds;  /* 2px 이하 흔들림(타이머 글자 폭 등)은 무시 — 잘림 위치가 떨지 않게 */
        if (!ob || ob.game || Math.abs(ob.x - nb.x) > 2 || Math.abs(ob.y - nb.y) > 2 || Math.abs(ob.w - nb.w) > 2 || Math.abs(ob.h - nb.h) > 2) S.bounds = nb;
      }
    } else {
      S.bounds = null; S.viewEff = 'doc';
    }
    syncViewButtons();
    var vw = Math.max(200, vp.clientWidth - 2), vh = Math.max(120, vp.clientHeight - 2);
    var B = S.bounds || { x: 0, y: 0, w: W, h: 0 };
    /* 맞춤: 문서 전체 = 폭 기준, 게임 화면 = 1280×720 이 폭·높이 안에 다 들어오게(작은 배율) */
    var fit = S.viewEff === 'game' ? Math.min(vw / B.w, vh / B.h) : vw / B.w;
    var s = S.zoom === 'fit' ? Math.max(0.2, Math.min(2, fit)) : 1;
    S.scale = s;
    if (!S.access) { S.H = Math.max(H0, Math.floor((vp.clientHeight - 2) / s)); B.h = S.H; }
    frame.style.width = W + 'px'; frame.style.height = S.H + 'px';
    scaler.style.width = W + 'px'; scaler.style.height = S.H + 'px';
    scaler.style.transform = 'scale(' + s + ') translate(' + (-B.x) + 'px,' + (-B.y) + 'px)';
    overlay.style.setProperty('--inv', String(1 / s));  /* 라벨·테두리는 축소와 무관하게 같은 화면 크기로 */
    sizer.style.width = Math.round(B.w * s) + 'px'; sizer.style.height = Math.round(B.h * s) + 'px';
  }

  /* 보이는 내용의 문서 좌표 경계. 그리는 요소(이미지·폼·배경·테두리·그림자) + 글자(텍스트 노드 범위)의 합집합.
     크기 0·display none·visibility hidden·opacity 0·조상 overflow 로 잘린 부분·문서 밖은 뺀다.
     문서 폭의 98% 이상을 덮는 요소(배경만 칠한 .page 같은 전체폭 래퍼·전체 화면 덮개)는 자식·글자로만 잡는다. */
  var PAINT_TAGS = { IMG: 1, svg: 1, SVG: 1, CANVAS: 1, VIDEO: 1, IFRAME: 1, INPUT: 1, SELECT: 1, TEXTAREA: 1, HR: 1 };
  var BOUNDS_PAD = 4;
  function alphaOf(c) {
    if (!c || c === 'transparent') return 0;
    var m = /rgba?\(([^)]+)\)/.exec(c);
    if (!m) return 1;
    var p = m[1].split(/[\s,\/]+/).filter(Boolean);
    return p.length > 3 ? parseFloat(p[3]) : 1;
  }
  function paints(el, cs) {
    if (PAINT_TAGS[el.tagName]) return true;
    if (el.ownerSVGElement) return false;  /* svg 안쪽은 svg 루트로 잡는다 */
    if (cs.backgroundImage !== 'none' || alphaOf(cs.backgroundColor) > 0 || cs.boxShadow !== 'none') return true;
    return ['Top', 'Right', 'Bottom', 'Left'].some(function (sd) {
      return parseFloat(cs['border' + sd + 'Width']) > 0 && cs['border' + sd + 'Style'] !== 'none' && alphaOf(cs['border' + sd + 'Color']) > 0;
    });
  }
  /* 게임 화면 = 산출물 #canvas 의 문서 좌표 사각형(shoot.py 와 같은 계약). 없거나 크기 0 이면 null → 문서 전체로 */
  function canvasBounds() {
    var c = null;
    try { c = S.doc.getElementById('canvas'); } catch (e) { c = null; }
    if (!c) return null;
    var r = c.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return null;
    var sx = S.win.scrollX || 0, sy = S.win.scrollY || 0;
    return { x: Math.round(r.left + sx), y: Math.round(r.top + sy), w: Math.round(r.width), h: Math.round(r.height), game: true };
  }
  function contentBounds() {
    var doc = S.doc, win = S.win, root = doc.documentElement, sx = win.scrollX || 0, sy = win.scrollY || 0;
    var info = new Map(), box = { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity };
    function inter(a, b) { return a ? (b ? [Math.max(a[0], b[0]), Math.max(a[1], b[1]), Math.min(a[2], b[2]), Math.min(a[3], b[3])] : a) : b; }
    function st(el) {  /* {cs, hide, own: 이 요소에 걸리는 조상 클립, kids: 자식에 걸리는 클립} */
      var v = info.get(el);
      if (v) return v;
      var p = el.parentElement, pv = p && p !== root ? st(p) : { hide: false, kids: null };
      var cs = win.getComputedStyle(el);
      var hide = pv.hide || cs.display === 'none' || parseFloat(cs.opacity) === 0;
      var kids = pv.kids;
      if (cs.overflowX !== 'visible' || cs.overflowY !== 'visible') {
        var r = el.getBoundingClientRect();
        kids = inter(kids, [r.left, r.top, r.right, r.bottom]);
      }
      v = { cs: cs, hide: hide, own: pv.kids, kids: kids };
      info.set(el, v);
      return v;
    }
    function addRect(r, clip) {
      var l = r.left, t = r.top, rr = r.right, bb = r.bottom;
      if (clip) { l = Math.max(l, clip[0]); t = Math.max(t, clip[1]); rr = Math.min(rr, clip[2]); bb = Math.min(bb, clip[3]); }
      l += sx; rr += sx; t += sy; bb += sy;
      l = Math.max(l, 0); t = Math.max(t, 0); rr = Math.min(rr, W); bb = Math.min(bb, S.H);
      if (rr - l <= 0 || bb - t <= 0) return;
      box.x0 = Math.min(box.x0, l); box.y0 = Math.min(box.y0, t); box.x1 = Math.max(box.x1, rr); box.y1 = Math.max(box.y1, bb);
    }
    [].forEach.call(doc.body.querySelectorAll('*'), function (el) {
      var v = st(el);
      if (v.hide || v.cs.visibility === 'hidden' || !paints(el, v.cs)) return;
      var r = el.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0 || r.width >= W * 0.98) return;
      addRect(r, v.own);
    });
    var tw = doc.createTreeWalker(doc.body, 4 /* SHOW_TEXT */), range = doc.createRange(), tn;
    while ((tn = tw.nextNode())) {
      if (!/\S/.test(tn.data) || !tn.parentElement) continue;
      var pv = st(tn.parentElement);
      if (pv.hide || pv.cs.visibility === 'hidden' || /^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE)$/.test(tn.parentElement.tagName)) continue;
      range.selectNodeContents(tn);
      addRect(range.getBoundingClientRect(), pv.kids);
    }
    if (box.x1 <= box.x0 || box.y1 <= box.y0) return null;
    var x = Math.max(0, Math.floor(box.x0 - BOUNDS_PAD)), y = Math.max(0, Math.floor(box.y0 - BOUNDS_PAD));
    return { x: x, y: y, w: Math.min(W, Math.ceil(box.x1 + BOUNDS_PAD)) - x, h: Math.min(S.H, Math.ceil(box.y1 + BOUNDS_PAD)) - y };
  }

  /* 산출물 DOM 이 바뀌면(innerHTML 재렌더·타이머·상태 전환) 다음 프레임에 하이라이트·크기, 조금 뒤 목록을 다시 계산 */
  function schedule(listNow) {
    if (!S.raf) S.raf = requestAnimationFrame(function () { S.raf = 0; measure(); drawSel(); updateHover(); if (dockOpen()) fitZoom(); });
    clearTimeout(S.listTimer);
    S.listTimer = setTimeout(function () { renderComps(); }, listNow === true ? 0 : 250);
  }

  /* ---------------------------------------------------------------- 히트 테스트·선택 */
  function pt0(e) {
    var r = overlay.getBoundingClientRect();
    return { x: (e.clientX - r.left) / S.scale, y: (e.clientY - r.top) / S.scale };
  }
  function areaEls(key) {
    if (!S.access) return [];
    try { return [].slice.call(S.doc.querySelectorAll('[data-area="' + esc(key) + '"]')); } catch (e) { return []; }
  }
  function visible(el) {
    try {
      var r = el.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) return false;
      return el.ownerDocument.defaultView.getComputedStyle(el).visibility !== 'hidden';
    } catch (e) { return false; }
  }
  function resolve(leaf) {
    if (!leaf || leaf.nodeType !== 1 || leaf === S.doc.documentElement) return null;
    var a = leaf.closest('[data-area]');
    if (a && !KEY_RE.test(a.getAttribute('data-area') || '')) a = null;  /* 계약 형식이 아닌 키는 서버가 거부 → 키 없음으로 */
    var t = leaf.closest('[data-template]');
    if (a) {
      return { kind: 'area', el: a, component: a.getAttribute('data-area'), idx: a.hasAttribute('data-idx') ? a.getAttribute('data-idx') : null,
        template: t && a.contains(t) ? t.getAttribute('data-template') : null };
    }
    if (t) return { kind: 'nokey', el: t, template: t.getAttribute('data-template') };
    return { kind: 'nokey', el: leaf, template: null };
  }
  function docBox(el) {
    var r = el.getBoundingClientRect(), sx = S.win.scrollX || 0, sy = S.win.scrollY || 0;
    return { x: Math.round(r.left + sx), y: Math.round(r.top + sy), w: Math.round(r.width), h: Math.round(r.height) };
  }
  var VOLATILE = { on: 1, cur: 1, active: 1, selected: 1, sel: 1, hl: 1, pulse: 1, show: 1, preview: 1, flash: 1, emphasis: 1, hover: 1 };
  function stableClass(el) {
    for (var i = 0; i < el.classList.length; i++) {
      var c = el.classList[i];
      if (/^[A-Za-z][\w-]*$/.test(c) && !VOLATILE[c]) return c;
    }
    return null;
  }
  function uniqueId(el) {
    try { return el.id && S.doc.querySelectorAll('#' + esc(el.id)).length === 1; } catch (e) { return false; }
  }
  function selectorOf(el, plain) {
    var parts = [], cur = el;
    while (cur && cur.nodeType === 1 && cur !== S.doc.documentElement) {
      if (cur === S.doc.body) { parts.unshift('body'); break; }
      if (uniqueId(cur)) { parts.unshift('#' + esc(cur.id)); break; }
      var tag = cur.tagName.toLowerCase(), cls = plain ? null : stableClass(cur), seg = tag + (cls ? '.' + esc(cls) : '');
      var p = cur.parentElement;
      if (p) {
        var same = [].filter.call(p.children, function (c) { return c.tagName === cur.tagName && (!cls || c.classList.contains(cls)); });
        if (same.length > 1 || plain) seg += ':nth-child(' + ([].indexOf.call(p.children, cur) + 1) + ')';
      }
      parts.unshift(seg);
      cur = p;
    }
    var s = parts.join(' > ');
    var ok = false;
    try { ok = S.doc.querySelector(s) === el; } catch (e) { ok = false; }
    if (!ok && !plain) return selectorOf(el, true);
    while (s.length > 500 && parts.length > 1) { parts.shift(); s = parts.join(' > '); }
    return s;
  }
  function pickAt(x, y) {
    if (!S.access || S.mode !== 'select') return;
    var leaf = null;
    try { leaf = S.doc.elementFromPoint(x, y); } catch (e) { leaf = null; }
    var r = leaf ? resolve(leaf) : null;
    if (!r) return;
    /* 클릭 규칙은 4.5 그대로(가장 가까운 data-area → data-template → 셀렉터). 고른 요소가 의미 노드면 노드로 선택(7.5) */
    if (!S.elMap || !S.elMap.has(r.el)) buildTree();
    var node = S.elMap ? S.elMap.get(r.el) : null;
    if (node) { setSel(selOfNode(node)); return; }
    var box = docBox(r.el);
    if (r.kind === 'area') {
      setSel({ kind: 'area', component: r.component, idx: r.idx, template: r.template, bbox: box, nth: areaEls(r.component).indexOf(r.el) });
    } else {
      setSel(selOfKeyless(r.el, r.template, box));
    }
  }
  function setSel(sel, scroll) {
    var prev = S.sel;
    if (!sel || !prev || (sel.nid || sel.selector || sel.component) !== (prev.nid || prev.selector || prev.component)) S.suggest = null;  /* 대상이 바뀌면 교체 제안은 버린다 */
    S.sel = sel;
    if (sel) { S.missingKey = null; openDock(); }
    try {
      if (sel && sel.component) Q.set('k', sel.component); else Q.delete('k');
      history.replaceState(null, '', '?' + Q.toString());
    } catch (e) { /* file:// 등 */ }
    updateTabHrefs();
    drawSel();
    if (scroll) revealSel();
    renderTarget(); renderThread(); renderComps(); renderSuggest(); updateForm();
  }
  function selElements() {
    var sel = S.sel;
    if (!sel || !S.access) return [];
    if (sel.el && sel.el.isConnected) return [sel.el];
    if (sel.kind === 'node' && sel.selector) {
      try { var ne = S.doc.querySelector(sel.selector); if (ne) return [ne]; } catch (e) { /* 깨진 셀렉터 */ }
      return [];
    }
    if (sel.kind === 'area') {
      var list = areaEls(sel.component);
      if (sel.idx != null) list = list.filter(function (e) { return e.getAttribute('data-idx') === sel.idx; });
      if (sel.nth != null && sel.nth >= 0) return list[sel.nth] ? [list[sel.nth]] : list.slice(0, 1);
      return list.filter(visible);
    }
    if (sel.selector) {
      try { var el = S.doc.querySelector(sel.selector); if (el) return [el]; } catch (e) { /* 깨진 셀렉터 */ }
    }
    return [];
  }
  function boxEl(cls, x, y, w, hh, label) {
    var b = h('div', { class: 'rv-hl ' + cls });
    b.style.left = x + 'px'; b.style.top = y + 'px'; b.style.width = Math.max(1, w) + 'px'; b.style.height = Math.max(1, hh) + 'px';
    if (label) add(b, h('span', { text: label }));
    b.classList.toggle('in', y < 24 / S.scale);  /* 문서 맨 위면 라벨을 상자 안쪽으로 */
    return b;
  }
  function selLabel(sel) {
    if (!sel) return '';
    if (sel.kind === 'area') return sel.component + (sel.idx != null ? ' #' + sel.idx : '');
    if (sel.kind === 'node') return (sel.component ? sel.component + ' › ' : '키 없음 · ') + (sel.label || sel.template || '');
    if (sel.kind === 'item') return '키 없음 · ' + sel.id;
    return '키 없음' + (sel.template ? ' · ' + sel.template : '');
  }
  /* 부모(점선)·자식(얇은 선) — 7.5 하이라이트 */
  function drawKin() {
    var n = curNode(), par = null, kids = [];
    if (n) { par = n.parent; kids = flatKids(n); }
    else if (S.sel && S.sel.kind === 'nokey') par = S.byId[S.sel.parentId] || null;
    if (par && !par.root && par.el && visible(par.el)) {
      var r = par.el.getBoundingClientRect();
      overlay.appendChild(boxEl('rv-par', r.left, r.top, r.width, r.height, null));
    }
    kids.slice(0, 80).forEach(function (k) {
      if (!k.el || !visible(k.el)) return;
      var kr = k.el.getBoundingClientRect();
      overlay.appendChild(boxEl('rv-kid', kr.left, kr.top, kr.width, kr.height, null));
    });
  }
  function drawSel() {
    [].slice.call(overlay.querySelectorAll('.rv-sel, .rv-par, .rv-kid')).forEach(function (n) { n.remove(); });
    if (!S.sel || !S.access) return;
    drawKin();
    var els = selElements(), label = selLabel(S.sel);
    if (els.length) {
      els.forEach(function (el, i) {
        if (!visible(el)) return;
        var r = el.getBoundingClientRect();
        overlay.appendChild(boxEl('rv-sel', r.left, r.top, r.width, r.height, i === 0 ? label : null));
      });
    } else if (S.sel.bbox && S.sel.kind !== 'area') {
      var bb = S.sel.bbox, sx = S.win.scrollX || 0, sy = S.win.scrollY || 0;
      overlay.appendChild(boxEl('rv-sel rv-ghost', bb.x - sx, bb.y - sy, bb.w, bb.h, label + ' (기록된 bbox)'));
    }
  }
  function updateHover() {
    if (!S.hoverPt || !S.access || S.mode !== 'select') { hoverBox.classList.add('hidden'); return; }
    var leaf = null;
    try { leaf = S.doc.elementFromPoint(S.hoverPt.x, S.hoverPt.y); } catch (e) { leaf = null; }
    var r = leaf ? resolve(leaf) : null;
    if (!r) { hoverBox.classList.add('hidden'); return; }
    var rect = r.el.getBoundingClientRect();
    hoverBox.style.left = rect.left + 'px'; hoverBox.style.top = rect.top + 'px';
    hoverBox.style.width = Math.max(1, rect.width) + 'px'; hoverBox.style.height = Math.max(1, rect.height) + 'px';
    hoverBox.classList.toggle('nokey', r.kind !== 'area');
    hoverBox.classList.toggle('in', rect.top < 24 / S.scale);
    hoverBox.querySelector('span').textContent = r.kind === 'area' ? r.component + (r.idx != null ? ' #' + r.idx : '') : '키 없음' + (r.template ? ' · ' + r.template : '');
    hoverBox.setAttribute('data-key', r.kind === 'area' ? r.component : '');
    hoverBox.classList.remove('hidden');
  }
  function revealSel() {
    var els = selElements().filter(visible), r = null;
    if (els.length) r = els[0].getBoundingClientRect();
    else if (S.sel && S.sel.bbox && S.access) r = { left: S.sel.bbox.x, top: S.sel.bbox.y, width: S.sel.bbox.w, height: S.sel.bbox.h };
    if (!r) return;
    var B = S.bounds || { x: 0, y: 0 };  /* 잘라낸 표시 범위 기준 */
    var s = S.scale, top = (r.top - B.y) * s, left = (r.left - B.x) * s, bh = r.height * s, bw = r.width * s;
    if (top < vp.scrollTop || top + bh > vp.scrollTop + vp.clientHeight) vp.scrollTop = Math.max(0, top - Math.max(16, (vp.clientHeight - bh) / 2));
    if (left < vp.scrollLeft || left + bw > vp.scrollLeft + vp.clientWidth) vp.scrollLeft = Math.max(0, left - 16);
  }
  /* 선택 모드에서도 산출물 안 스크롤 영역(목록 등)은 휠로 움직이게 */
  function forwardWheel(e) {
    if (!S.access) return;
    var p = pt0(e), el = null;
    try { el = S.doc.elementFromPoint(p.x, p.y); } catch (x) { el = null; }
    for (; el && el !== S.doc.body && el !== S.doc.documentElement; el = el.parentElement) {
      var cs = el.ownerDocument.defaultView.getComputedStyle(el);
      if (/(auto|scroll)/.test(cs.overflowY) && el.scrollHeight > el.clientHeight + 1) {
        var before = el.scrollTop;
        el.scrollTop += e.deltaY;
        if (el.scrollTop !== before) { e.preventDefault(); return; }
      }
    }
  }
  /* 피드백(목록·fb 파라미터)에서 대상으로: 그 상태로 진입 → 키면 bbox 에 가장 가까운 같은 키 요소, 키 없음이면 셀렉터/bbox */
  function selectItem(it, scroll) {
    if (!isCur(it)) return;  /* 다른 단계·시안 피드백은 이 산출물의 컴포넌트에 앵커하지 않는다 */
    if (it.state && it.state !== S.state && S.access && stateDef(it.state)) enterState(it.state);
    /* path(7.1) 가 있으면 마지막 노드의 셀렉터로 그 의미 노드를 찾는다 */
    var last = Array.isArray(it.path) && it.path.length ? it.path[it.path.length - 1] : null;
    if (S.access && last && typeof last.selector === 'string') {
      var pe = null;
      try { pe = S.doc.querySelector(last.selector); } catch (e) { pe = null; }
      buildTree();
      var pn = pe && S.elMap ? S.elMap.get(pe) : null;
      if (pn) { var ps = selOfNode(pn); ps.focus = it.id; setSel(ps, scroll); return; }
    }
    if (it.component) {
      var nth = null, list = [];
      if (S.access) {
        list = areaEls(it.component);
        if (it.idx != null) list = list.filter(function (e) { return e.getAttribute('data-idx') === it.idx; });
        if (it.bbox && list.length > 1) {
          var best = Infinity, cx = it.bbox.x + it.bbox.w / 2, cy = it.bbox.y + it.bbox.h / 2;
          list.forEach(function (e, i) { var b = docBox(e), d = Math.abs(b.x + b.w / 2 - cx) + Math.abs(b.y + b.h / 2 - cy); if (d < best) { best = d; nth = i; } });
        } else if (list.length) nth = 0;
      }
      if (nth != null && list[nth]) {
        buildTree();
        var an = S.elMap ? S.elMap.get(list[nth]) : null;
        if (an) { var as = selOfNode(an); as.focus = it.id; setSel(as, scroll); return; }
      }
      setSel({ kind: 'area', component: it.component, idx: it.idx, template: it.template, bbox: it.bbox, nth: nth, focus: it.id }, scroll);
    } else {
      setSel({ kind: 'item', id: it.id, template: it.template, selector: it.selector, bbox: it.bbox, focus: it.id }, scroll);
    }
  }

  /* ---------------------------------------------------------------- 패널 */
  function renderAll() {
    if (!S.screen) return;
    renderTabs(); renderStates(); renderTarget(); renderThread(); renderComps(); renderRef(); updateForm();
  }
  function renderKinds() {
    var box = clear($('rv-kinds'));
    KINDS.forEach(function (k) {
      add(box, h('button', { type: 'button', role: 'radio', 'data-kind': k[0], class: k[0] === S.kind ? 'on' : '', 'aria-checked': k[0] === S.kind ? 'true' : 'false',
        text: k[1], onclick: function () { setKind(k[0]); } }));
    });
  }
  /* kind=template 이 아니면 suggest 금지(7.1) — 다른 종류를 고르면 교체 제안을 지운다 */
  function setKind(kind) {
    S.kind = kind;
    if (kind !== 'template') S.suggest = null;
    [].slice.call($('rv-kinds').children).forEach(function (b) { var on = b.getAttribute('data-kind') === S.kind; b.classList.toggle('on', on); b.setAttribute('aria-checked', on ? 'true' : 'false'); });
    renderSuggest(); updateForm();
  }
  function setSuggest(sg) {
    S.suggest = sg;
    if (sg) setKind('template'); else { renderSuggest(); updateForm(); }
  }
  function renderSuggest() {
    var chip = $('rv-suggest');
    chip.classList.toggle('hidden', !S.suggest);
    $('rv-suggest-label').textContent = S.suggest ? '교체 제안: ' + (S.suggest.from || '—') + ' → ' + S.suggest.template : '';
  }
  function bboxText(b) { return b ? b.x + ',' + b.y + ' ' + b.w + '×' + b.h : ''; }
  function fbNoticeEl(n) {
    var box = h('div', { class: 'rv-fbnote', id: 'rv-fbnote' });
    if (!n.item) { add(box, h('b', { text: n.id }), ' — 이 화면에 그런 피드백이 없다.'); return box; }
    var st = stageOf(n.item.stage, n.item.version);
    if (!st) {  /* 등록부에서 빠진 시안 — 열 곳이 없다 */
      add(box, h('b', { text: n.id }), ' 은 등록부에 없는 시안(' + n.item.stage + ' ' + n.item.version + ')의 피드백이라 선택하지 않는다.');
      return box;
    }
    add(box, h('b', { text: n.id }), ' 은 ' + variantLabel(st) + '(' + st.version + ') 피드백이라 여기서는 선택하지 않는다. ',
      h('a', { class: 'rv-fblink', href: reviewUrl(st.stage, st.version, n.id), text: '그 시안에서 열기 ›' }));
    return box;
  }
  function renderTarget() {
    var t = clear($('rv-target')), sel = S.sel;
    t.classList.toggle('mut', !sel);
    if (!sel) {
      t.textContent = S.access ? '산출물에서 컴포넌트를 누르거나 하단 도크 트리에서 고른다.' : '하단 도크 트리에서 컴포넌트를 고르면 그 스레드가 보인다.';
      if (S.missingKey) add(t, h('div', { class: 'rv-fbnote', text: '이 상태엔 ' + S.missingKey + ' 없음' }));
      if (S.fbNotice) add(t, fbNoticeEl(S.fbNotice));
      return;
    }
    var head = h('div', { class: 'rv-tline' });
    if (sel.component) add(head, h('b', { class: 'rv-key', text: sel.component }), sel.idx != null ? h('span', { class: 'tag', text: '#' + sel.idx }) : null);
    else add(head, h('span', { class: 'rv-nokey', text: '키 없음' }), sel.kind === 'item' ? h('b', { text: sel.id }) : null);
    if (sel.kind === 'node' && sel.component && sel.label) add(head, h('span', { class: 'rv-sub mono', text: '› ' + sel.label }));
    if (sel.template) add(head, h('span', { class: 'tag c', text: sel.template }));
    if (S.state) add(head, h('span', { class: 'tag', text: '상태 ' + S.state }));
    add(head, h('button', { type: 'button', class: 'rv-x', title: '선택 해제(Esc)', text: '해제', onclick: function () { setSel(null); } }));
    add(t, head);
    if (sel.path && sel.path.length > 1) add(t, h('div', { class: 'mono mut rv-tpath', id: 'rv-target-path', text: '경로: ' + sel.path.map(pathItemLabel).join(' › ') }));
    if (sel.selector && sel.kind !== 'area') add(t, h('div', { class: 'mono rv-selector', text: sel.selector }));
    if (sel.bbox) add(t, h('div', { class: 'mono mut', text: 'bbox ' + bboxText(sel.bbox) }));
  }
  function threadItems() {
    var sel = S.sel, items = curItems();
    if (!sel) return items;
    if (sel.kind === 'area') return items.filter(function (it) { return it.component === sel.component; });
    if (sel.kind === 'item') return items.filter(function (it) { return it.id === sel.id; });
    if (sel.kind === 'node') return items.filter(function (it) { return (it.component || null) === (sel.component || null) && !!it.selector && it.selector === sel.selector; });
    return items.filter(function (it) { return it.component == null && it.selector && it.selector === sel.selector; });
  }
  function renderThread() {
    var act = document.activeElement;  /* 다시 그리기 전 인라인 폼 포커스·커서를 기억 */
    if (S.inline && act && act.tagName === 'TEXTAREA' && act.closest && act.closest('#rv-thread .rv-inline')) {
      S.inline.focus = true; S.inline.s0 = act.selectionStart; S.inline.s1 = act.selectionEnd;
    }
    fillThread(clear($('rv-thread')));
    if (S.inline && S.inline.focus) {
      var ta = $('rv-thread').querySelector('.rv-inline[data-for="' + esc(S.inline.id) + '"] textarea');
      if (ta) { ta.focus(); try { ta.setSelectionRange(S.inline.s0, S.inline.s1); } catch (e) { /* 범위 밖 */ } }
      S.inline.focus = false;
    }
  }
  function fillThread(box) {
    var items = threadItems();
    if (!S.sel) add(box, h('div', { class: 'mut rv-hint', text: '선택 없음 — 이 시안(' + VER + ')의 피드백 전체 ' + items.length + '건' }));
    if (!items.length) { add(box, h('div', { class: 'mut rv-empty', text: S.sel ? '이 컴포넌트에 남긴 피드백 없음' : '피드백 없음' })); return; }
    items.forEach(function (it) { add(box, itemCard(it, false)); });
    var f = S.sel && S.sel.focus && box.querySelector('[data-id="' + esc(S.sel.focus) + '"]');
    if (f) f.classList.add('focus');
  }
  function itemMeta(it) {
    var bits = [];
    if (it.state) bits.push('상태 ' + it.state);
    bits.push((it.stage === 'wire' ? '와이어 ' : it.stage === 'mockup' ? '목업 ' : it.stage + ' ') + it.version);
    if (it.idx != null) bits.push('#' + it.idx);
    if (it.template) bits.push(it.template);
    return bits.join(' · ');
  }
  function itemCard(it, ref) {
    var card = h(ref ? 'details' : 'article', { class: 'rv-item' + (ref ? ' rv-refitem' : ''), 'data-id': it.id, 'data-status': it.status });
    var head = h(ref ? 'summary' : 'header', { class: 'rv-ihead' }, badge(it.status), h('b', { class: 'rv-id', text: it.id }),
      h('span', { class: 'tag', text: KIND_L[it.kind] || it.kind }),
      it.component ? h('span', { class: 'rv-key', text: it.component }) : h('span', { class: 'rv-nokey', text: '키 없음' }),
      h('span', { class: 'mut rv-meta', text: itemMeta(it) }));
    if (ref) add(head, h('div', { class: 'rv-snip', text: it.text }));
    add(card, head);
    if (it.component == null && it.selector) add(card, h('div', { class: 'mono mut rv-selector', text: it.selector }));
    var ol = h('ol', { class: 'rv-hist' });
    (it.history || []).forEach(function (ev) { add(ol, eventRow(ev, it)); });
    add(card, ol);
    if (!ref && !S.readOnly) add(card, actions(it));
    if (!ref && !it.component && S.access) {
      add(card, h('button', { type: 'button', class: 'rv-link', text: '산출물에서 위치 보기', onclick: function () { selectItem(it, true); } }));
    }
    return card;
  }
  function eventRow(ev, it) {
    var li = h('li', { class: 'ev ev-' + ev.type, 'data-type': ev.type },
      h('div', { class: 'evh' }, h('b', { text: TYPE_L[ev.type] || ev.type }),
        h('span', { class: 'by by-' + ev.by, text: ev.by === 'user' && ev.author ? ev.author : BY_L[ev.by] || ev.by }),
        h('time', { text: fmtAt(ev.at), datetime: ev.at })));
    if (ev.type === 'open' || ev.type === 'comment') {
      add(li, h('p', { class: 'rv-text', text: ev.text }));
      if (Array.isArray(ev.attachments) && ev.attachments.length) add(li, attsRow(ev.attachments));
    }
    else if (ev.type === 'claim') add(li, h('p', { class: 'mut', text: '묶음 ' + ev.claim + ((ev.ids || []).length > 1 ? ' · 함께: ' + ev.ids.filter(function (x) { return x !== it.id; }).join(', ') : '') }));
    else if (ev.type === 'release') add(li, h('p', { class: 'rv-text' }, h('span', { class: 'mut', text: '사유: ' }), ev.text));
    else if (ev.type === 'reopen') add(li, h('p', { class: 'rv-text' }, h('span', { class: 'mut', text: '사유: ' }), ev.text));
    else if (ev.type === 'close') { if (ev.text) add(li, h('p', { class: 'rv-text', text: ev.text })); }
    else if (ev.type === 'revision') add(li, revisionBody(ev, it));
    return li;
  }
  function revisionBody(ev, it) {
    var box = h('div', { class: 'rv-rev' });
    add(box, h('p', { class: 'rv-text', text: ev.summary }));
    var meta = h('div', { class: 'rv-revmeta' }, h('span', { class: 'tag', text: ev.rev }));
    if (ev.newVersion) add(meta, h('span', { class: 'tag y', text: '새 버전 ' + ev.newVersion }));
    var others = (ev.ids || []).filter(function (x) { return x !== it.id; });
    if (others.length) add(meta, h('span', { class: 'mut', text: '함께 고침: ' + others.join(', ') }));
    add(box, meta);
    if ((ev.files || []).length) add(box, h('ul', { class: 'rv-files mono' }, ev.files.map(function (f) { return h('li', { text: f }); })));
    if (ev.diff && !safePath(ev.diff)) add(box, h('div', { class: 'warn rv-badpath', text: 'diff 경로 이상: ' + String(ev.diff).slice(0, 120) }));
    else if (ev.diff) {
      var pre = h('pre', { class: 'rv-diff hidden' });
      var row = h('div', { class: 'rv-difflinks' }, h('a', { href: '../' + ev.diff, target: '_blank', rel: 'noopener', class: 'rv-difflink', text: 'diff 보기' }));
      if (HTTP) {
        add(row, h('button', { type: 'button', class: 'rv-link', text: '패널에서 펼치기', onclick: function (e) {
          var b = e.currentTarget;
          if (!pre.classList.contains('hidden')) { pre.classList.add('hidden'); b.textContent = '패널에서 펼치기'; return; }
          b.textContent = '접기';
          if (pre.getAttribute('data-loaded')) { pre.classList.remove('hidden'); return; }
          fetch('../' + ev.diff, { cache: 'no-store' }).then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.text(); })
            .then(function (t) { pre.textContent = t; pre.setAttribute('data-loaded', '1'); pre.classList.remove('hidden'); })
            .catch(function (x) { pre.textContent = 'diff 를 못 읽음: ' + (x && x.message ? x.message : x); pre.classList.remove('hidden'); });
        } }));
      }
      add(box, row, pre);
    }
    var shot = (ev.shots || []).filter(function (s) { return s && s.id === it.id; })[0];
    if (shot) {
      add(box, h('div', { class: 'rv-shots' }, ['before', 'after'].map(function (k) {
        var p = shot[k];
        if (p && !safePath(p)) return h('figure', { class: 'rv-shot' }, h('div', { class: 'warn rv-noshot rv-badpath', text: '경로 이상' }), h('figcaption', { text: k === 'before' ? '전' : '후' }));
        return h('figure', { class: 'rv-shot' }, p ? h('a', { href: '../' + p, target: '_blank', rel: 'noopener' }, h('img', { src: '../' + p, alt: k === 'before' ? '수정 전' : '수정 후', loading: 'lazy' }))
          : h('div', { class: 'mut rv-noshot', text: '샷 없음' }), h('figcaption', { text: k === 'before' ? '전' : '후' }));
      })));
    } else if (Array.isArray(ev.shots)) add(box, h('div', { class: 'mut rv-noshot', text: '전/후 샷 없음' }));
    return box;
  }
  /* 그 status 에서 허용되는 사용자 행동(6절: comment·close·reopen) */
  function allowedActs(it) {
    var a = ['comment'];
    if (it.status !== 'closed') a.push('close');
    if (it.status === 'fixed' || it.status === 'closed') a.push('reopen');
    return a;
  }
  /* 열린 인라인 폼(코멘트·닫기·다시 열기)은 S.inline = {id, kind, text, focus, s0, s1} 로 들고 있어서
     스레드가 다시 그려져도(iframe load·refresh·선택 변경) 열림·입력값·포커스가 돌아온다. 취소·저장 성공 때만 지운다. */
  function actions(it) {
    var wrap = h('div', { class: 'rv-actions' }), inline = h('div', { class: 'rv-inline hidden', 'data-for': it.id });
    function close() { inline.classList.add('hidden'); clear(inline); }
    function open(kind, restore) {
      if (!restore) {  /* 초안을 추적하는 폼은 하나 — 다른 카드에 열린 폼은 닫는다 */
        [].slice.call(document.querySelectorAll('#rv-thread .rv-inline:not(.hidden)')).forEach(function (n) {
          if (n !== inline) { n.classList.add('hidden'); clear(n); }
        });
      }
      clear(inline); inline.classList.remove('hidden');
      inline.setAttribute('data-kind', kind);
      var need = kind !== 'close';
      var ta = h('textarea', { rows: 2, maxlength: 4000, placeholder: kind === 'comment' ? '코멘트' : kind === 'reopen' ? '다시 여는 사유(필수)' : '닫는 메모(선택)' });
      var go = h('button', { type: 'button', class: 'rv-go', text: kind === 'comment' ? '코멘트 남기기' : kind === 'reopen' ? '다시 열기' : '닫기' });
      var cancel = h('button', { type: 'button', class: 'rv-link', text: '취소', onclick: function () { S.inline = null; close(); } });
      if (restore) ta.value = restore.text || '';
      var files = (restore && restore.files) || [];  /* 개정 F — 코멘트 첨부도 초안과 함께 보존 */
      var picker = kind === 'comment' ? attPicker(files, ta, inline) : null;
      if (!picker) { inline.ondragenter = inline.ondragleave = inline.ondragover = inline.ondrop = null; inline.classList.remove('rv-dropping'); }
      S.inline = { id: it.id, kind: kind, text: ta.value, focus: !!(restore && restore.focus),
        s0: restore ? restore.s0 : null, s1: restore ? restore.s1 : null, files: files };
      function sync() { go.disabled = S.busy || (need && !ta.value.trim()); }
      ta.addEventListener('input', function () { if (S.inline && S.inline.id === it.id) S.inline.text = ta.value; sync(); });
      sync();
      go.addEventListener('click', function () {
        var text = ta.value.trim(), body = { type: kind, id: it.id };
        if (need && !text) return;
        if (text) body.text = text;
        var draft = S.inline;
        S.inline = null;  /* 저장 성공 뒤 refresh 가 폼을 되살리지 않게 */
        post(body, go, picker ? files.slice() : null).then(function (ok) {
          if (ok) close();
          else if (!S.inline) S.inline = draft;  /* 실패 = 초안 유지 */
        });
      });
      add(inline, ta, picker && picker.el, h('div', { class: 'rv-formrow' }, cancel, go));
      if (!restore) ta.focus();
    }
    var acts = allowedActs(it), LBL = { comment: '코멘트', close: '닫기', reopen: '다시 열기' };
    acts.forEach(function (k) { add(wrap, h('button', { type: 'button', 'data-act': k, text: LBL[k], onclick: function () { open(k); } })); });
    if (S.inline && S.inline.id === it.id) {
      if (acts.indexOf(S.inline.kind) >= 0) open(S.inline.kind, S.inline);
      else S.inline = null;  /* status 가 바뀌어 그 행동이 더는 없다(예: 이미 닫힘) */
    }
    return h('div', null, wrap, inline);
  }

  function visibleKeys() {
    var out = [], seen = {};
    if (!S.access) return out;
    var els = [];
    try { els = [].slice.call(S.doc.querySelectorAll('[data-area]')); } catch (e) { els = []; }
    els.forEach(function (el) {
      var k = el.getAttribute('data-area');
      if (!KEY_RE.test(k || '') || !visible(el)) return;
      if (!seen[k]) { seen[k] = { key: k, n: 0 }; out.push(seen[k]); }
      seen[k].n++;
    });
    return out;
  }
  function keyCounts() {
    var byKey = {};
    curItems().forEach(function (it) {
      if (it.component == null) return;
      var c = byKey[it.component] || (byKey[it.component] = { open: 0, fixed: 0, total: 0, items: [] });
      c.total++; if (isOpen(it)) c.open++; if (it.status === 'fixed') c.fixed++; c.items.push(it);
    });
    return byKey;
  }
  function counts(c) {
    if (!c) return null;
    return h('span', { class: 'rv-cnts' }, c.open ? h('span', { class: 'rv-c open', title: '열린', text: String(c.open) }) : null,
      c.fixed ? h('span', { class: 'rv-c fixed', title: '검토 대기', text: String(c.fixed) }) : null,
      h('span', { class: 'rv-c total', title: '전체', text: String(c.total) }));
  }
  /* 오른쪽 패널 '피드백 색인' = 지금 안 보이는 키·키 없음 피드백만. 보이는 키 목록은 도크 트리로 흡수(7.5) — 트리 행에 같은 숫자 배지 */
  function renderComps() {
    if (!S.screen) return;
    buildTree(); refreshSel();
    var box = clear($('rv-comps')), items = curItems(), byKey = keyCounts(), nokey = [];
    items.forEach(function (it) { if (it.component == null) nokey.push(it); });
    var vis = visibleKeys(), visSet = {};
    vis.forEach(function (v) { visSet[v.key] = 1; });
    function row(key, sub, c, onclick) {
      var on = S.sel && S.sel.component === key;
      return h('button', { type: 'button', class: 'rv-comp' + (on ? ' on' : ''), 'data-key': key, onclick: onclick },
        h('span', { class: 'rv-key', text: key }), sub ? h('span', { class: 'mut', text: sub }) : null, counts(c));
    }
    var hidden = Object.keys(byKey).filter(function (k) { return !visSet[k]; });
    $('rv-compn').textContent = hidden.length + nokey.length ? String(hidden.length + nokey.length) : '';
    if (!hidden.length && !nokey.length) add(box, h('div', { class: 'mut rv-empty', text: '보이는 키는 하단 도크 트리에 있다(숫자 배지 = 피드백).' }));
    if (hidden.length) {
      var g2 = h('div', { class: 'rv-cgroup', 'data-group': 'hidden' }, h('div', { class: 'rv-ghead', text: S.access ? '피드백은 있지만 지금 안 보이는 키' : '피드백이 있는 키' }));
      hidden.forEach(function (k) {
        var st = byKey[k].items.map(function (it) { return it.state; }).filter(Boolean)[0];
        add(g2, row(k, st ? '상태 ' + st : '', byKey[k], function () { selectItem(byKey[k].items[0], true); }));
      });
      add(box, g2);
    }
    if (nokey.length) {
      var g3 = h('div', { class: 'rv-cgroup', 'data-group': 'nokey' }, h('div', { class: 'rv-ghead', text: '키 없음 피드백 ' + nokey.length }));
      nokey.forEach(function (it) {
        var on = S.sel && S.sel.kind === 'item' && S.sel.id === it.id;
        add(g3, h('button', { type: 'button', class: 'rv-comp' + (on ? ' on' : ''), 'data-item': it.id, onclick: function () { selectItem(it, true); } },
          h('span', { class: 'rv-nokey', text: '키 없음' }), h('b', { text: it.id }), badge(it.status),
          h('span', { class: 'mut rv-ell', text: it.template || it.selector || '' })));
      });
      add(box, g3);
    }
    renderDock();
  }
  function renderRef() {
    var box = clear($('rv-ref')), items = refItems();
    if (!items.length) { add(box, h('div', { class: 'mut rv-empty', text: '다른 단계·시안 피드백 없음' })); return; }
    add(box, h('div', { class: 'mut rv-hint', text: '이월하지 않는다 — 참고용, 읽기 전용' }));
    items.forEach(function (it) {
      var st = stageOf(it.stage, it.version);
      var card = itemCard(it, true), sum = card.querySelector('summary');
      sum.insertBefore(h('span', { class: 'tag', text: st ? variantLabel(st) : it.stage + ' ' + it.version + '(미등록)' }), sum.firstChild);
      if (st) add(card, h('a', { class: 'rv-link rv-reflink', href: reviewUrl(st.stage, st.version, it.id), text: '그 시안에서 열기 ›' }));
      add(box, card);
    });
  }

  /* ---------------------------------------------------------------- 하단 도크(7.5) — ① 트리 */
  var IDX_RE = /^[A-Za-z0-9][A-Za-z0-9_.-]*$/;
  var SLUG_RE = /^[a-z0-9][a-z0-9_.-]*$/;
  var SCREEN_RE = /^[A-Za-z][A-Za-z0-9_]*$/;
  var LIB_CMD = 'python ui-audit/scripts/catalog_library.py --build';
  var SEM_ATTRS = ['data-area', 'data-template', 'data-variant', 'data-new'];
  var PATH_MAX = 12, STR_MAX = 200, DOCK_KEY = 'uiaudit-review-dock-h', DOCK_HMIN = 140, ZOOM_TRIES = 3, ZOOM_MAX = 6, SCRIPT_TIMEOUT = 15000;
  function hasOwn(o, k) { return !!o && Object.prototype.hasOwnProperty.call(o, k); }
  function isSem(el) {
    for (var i = 0; i < SEM_ATTRS.length; i++) if (el.hasAttribute(SEM_ATTRS[i])) return true;
    return false;
  }
  function semNode(el, parent) {
    var a = el.getAttribute('data-area');
    return { el: el, parent: parent, kids: [], area: a && KEY_RE.test(a) ? a : null, template: el.getAttribute('data-template'),
      variant: el.getAttribute('data-variant'), nw: el.getAttribute('data-new'), idx: el.getAttribute('data-idx') };
  }
  function nodeLabel(n) {
    return n.area || n.template || (n.nw ? '새 요소: ' + n.nw.slice(0, 24) : n.variant || '의미 노드');
  }
  function sigOf(n) { return [n.area || '', n.template || '', n.variant || ''].join('|'); }
  /* 노드 id = 부모 id + 서명 + 같은 서명 형제 안 순번 — 재렌더(innerHTML)로 요소가 바뀌어도 구조가 같으면 같은 id */
  function finishTree(node, byId) {
    var seen = {}, cnt = {}, groups = {};
    node.kids.forEach(function (k) { var s = sigOf(k); cnt[s] = (cnt[s] || 0) + 1; });
    node.entries = [];
    node.kids.forEach(function (k) {
      var s = sigOf(k);
      seen[s] = (seen[s] || 0) + 1;
      k.id = node.id + '/' + s + '.' + seen[s];
      k.depth = node.root ? 0 : node.depth + 1;
      byId[k.id] = k;
      if (cnt[s] > 1 && (k.area || k.template) && !k.fromKeys) {
        var g = groups[s];
        if (!g) {
          g = groups[s] = { group: true, id: node.id + '/' + s + '*', parent: node, members: [], area: k.area, template: k.template, variant: k.variant };
          byId[g.id] = g;
          node.entries.push(g);
        }
        k.grp = g; k.inst = g.members.length + 1;
        g.members.push(k);
      } else node.entries.push(k);
      finishTree(k, byId);
    });
  }
  function flatKids(n) {
    var out = [];
    (n && n.entries || []).forEach(function (e) { if (e.group) out = out.concat(e.members); else out.push(e); });
    return out;
  }
  /* 트리 = 산출물 DOM 의 보이는 의미 노드(DOM 접근 가능) 또는 keys 데이터의 현재 상태 키를 parent 로 엮은 것(file://) */
  function buildTree() {
    var root = { id: 'root', root: true, parent: null, kids: [], depth: -1, el: null };
    var map = new Map(), byId = { root: root };
    if (S.access) {
      root.el = S.doc.body;
      (function walk(el, par) {
        for (var c = el.firstElementChild; c; c = c.nextElementSibling) {
          if (isSem(c) && visible(c)) { var n = semNode(c, par); par.kids.push(n); map.set(c, n); walk(c, n); }
          else walk(c, par);
        }
      })(S.doc.body, root);
    } else keysTree(root);
    finishTree(root, byId);
    S.tree = root; S.byId = byId; S.elMap = map;
  }
  function curTarget() { return STAGE + '/' + VER; }
  function keysState(stateId) {
    var K = S.lib.keys, t = K && K.targets ? K.targets[curTarget()] : null, st = t && t.states ? t.states[stateId] : null;
    return st && st.keys && typeof st.keys === 'object' ? st.keys : null;
  }
  function keysTree(root) {
    var keys = keysState(S.fileState);
    if (!keys) return;
    var nodes = {};
    Object.keys(keys).forEach(function (k) {
      if (!KEY_RE.test(k)) return;
      var v = keys[k] || {};
      nodes[k] = { area: k, template: v.template || null, variant: v.variant || null, nw: v['new'] || null, idx: null, kids: [],
        count: v.count || 1, bbox: v.bbox || null, crop: v.crop || null, el: null, fromKeys: true, parentKey: v.parent };
    });
    Object.keys(nodes).forEach(function (k) {
      var n = nodes[k], p = n.parentKey && n.parentKey !== k && nodes[n.parentKey] ? nodes[n.parentKey] : root;
      for (var x = p; x && !x.root; x = x.parent) if (x === n) { p = root; break; }  /* 순환 방지 */
      n.parent = p; p.kids.push(n);
    });
  }
  function curNode() { return S.sel && S.sel.nid && S.byId ? S.byId[S.sel.nid] || null : null; }
  function compOf(n) { for (var x = n; x && !x.root; x = x.parent) if (x.area) return x; return null; }
  /* 7.1: template = 선택 노드 자신, 없으면 선택 노드와 component 사이에서 가장 가까운 것(component 가 없으면 끝까지) */
  function tplOf(n, c) {
    for (var x = n; x && !x.root; x = x.parent) { if (x.template) return x.template; if (x === c) break; }
    return null;
  }
  function ancestorTpl(n) { for (var x = n && n.parent; x && !x.root; x = x.parent) if (x.template) return x.template; return null; }
  function cut(s) { return typeof s === 'string' && s.length > STR_MAX ? s.slice(0, STR_MAX) : s; }
  function pathItem(n) {
    var p = {};
    if (n.area) p.area = n.area;
    if (n.template) p.template = cut(n.template);
    if (n.variant) p.variant = cut(n.variant);
    if (n.idx != null && IDX_RE.test(n.idx)) p.idx = n.idx;
    if (n.el) p.selector = selectorOf(n.el);
    return p;
  }
  function pathItemLabel(p) {
    var lb = p.area || p.template || ('selector:' + String(p.selector || '').slice(0, 40));
    var extra = [p.area ? p.template : null, p.variant, p.idx != null ? '#' + p.idx : null].filter(Boolean);
    return lb + (extra.length ? '[' + extra.join(' · ') + ']' : '');
  }
  /* 7.1 path: 바깥 → 선택 노드, 안쪽 12단만. component 가 잘려 나가면 서버가 거부하므로 path 를 빼고 보낸다 */
  function pathOf(n, tail, comp) {
    var chain = [];
    for (var x = n; x && !x.root; x = x.parent) chain.unshift(pathItem(x));
    if (tail) chain.push(tail);
    if (chain.length > PATH_MAX) chain = chain.slice(chain.length - PATH_MAX);
    if (comp && !chain.some(function (p) { return p.area === comp; })) return null;
    return chain.length ? chain : null;
  }
  function selOfNode(n) {
    var c = compOf(n), box = n.el ? docBox(n.el) : n.bbox ? { x: n.bbox.x, y: n.bbox.y, w: n.bbox.w, h: n.bbox.h } : null;
    var cidx = c && c.idx != null && IDX_RE.test(c.idx) ? c.idx : null;
    return { kind: n.area ? 'area' : 'node', nid: n.id, el: n.el || null, label: nodeLabel(n), component: c ? c.area : null, idx: cidx,
      template: tplOf(n, c), bbox: box, selector: n.el ? selectorOf(n.el) : null, path: n.el ? pathOf(n, null, c ? c.area : null) : null,
      nth: n.el && n.area ? areaEls(n.area).indexOf(n.el) : null };
  }
  /* 키 없는 요소 직접 클릭: 가장 가까운 의미 조상 밑에 회색 '키 없음' 노드로 임시로 붙는다(7.5) */
  function selOfKeyless(el, template, box) {
    var p = null;
    for (var x = el.parentElement; x && x !== S.doc.body; x = x.parentElement) { if (S.elMap && S.elMap.get(x)) { p = S.elMap.get(x); break; } }
    var selector = selectorOf(el);
    return { kind: 'nokey', template: template, selector: selector, bbox: box, parentId: p ? p.id : 'root',
      path: pathOf(p, { selector: selector }, null) };
  }
  /* 같은 상태 안 재렌더: 같은 id 의 노드가 새 요소면 선택을 그 요소로 옮긴다(제안·포커스는 유지) */
  function refreshSel() {
    var n = curNode();
    if (!n || !S.sel || S.sel.el === n.el || !n.el) return;
    var ns = selOfNode(n);
    ns.focus = S.sel.focus;
    S.sel = ns;
  }
  /* 상태 전환(7.5): 같은 노드·같은 키가 새 상태에 있으면 선택 유지, 없으면 "이 상태엔 <키> 없음" */
  function reanchorAfterState() {
    var old = S.sel;
    S.zf.state = null; S.zf.failN = 0;  /* 확대 뷰는 다음 동기화 때 steps 재실행(사용자가 상태를 다시 고르면 실패 횟수도 처음부터) */
    if (!old) return;
    buildTree();
    var n = old.nid ? S.byId[old.nid] : null;
    if (!n && old.component) n = findKey(old.component);
    if (n && !n.group) { var ns = selOfNode(n); ns.focus = old.focus; S.sel = ns; }
    else if ((old.kind === 'nokey' || old.kind === 'item') && old.selector && safeQuery(old.selector)) { /* 키 없는 대상의 셀렉터가 새 상태에도 있다 */ }
    else { S.sel = null; S.missingKey = old.component || old.label || old.selector || '선택 대상'; S.suggest = null; }
    try { if (S.sel && S.sel.component) Q.set('k', S.sel.component); else Q.delete('k'); history.replaceState(null, '', '?' + Q.toString()); } catch (e) { /* file:// */ }
    renderTarget(); renderThread(); renderSuggest(); updateForm(); updateTabHrefs();
  }
  function safeQuery(s) { try { return S.doc.querySelector(s); } catch (e) { return null; } }
  function findKey(k) {
    var found = null;
    (function dfs(n) {
      (n.kids || []).some(function (c) { if (c.area === k) { found = c; return true; } dfs(c); return !!found; });
    })(S.tree || { kids: [] });
    return found;
  }
  /* URL &k= — 로드 뒤 그 키가 있으면 선택해 도크를 연다(한 번만) */
  function applyKey0() {
    if (!KEY0 || S.sel || !S.frameDone) return;
    if (!S.access && S.lib.keysSt === 'loading') return;  /* file:// 은 keys 데이터가 와야 트리가 생긴다 */
    var k = KEY0;
    KEY0 = '';
    buildTree();
    var n = findKey(k);
    if (n) setSel(selOfNode(n), true);
    else { S.missingKey = k; openDock(); renderTarget(); renderDock(); }
  }
  function selectNodeId(id) {
    var n = S.byId[id];
    if (!n) return;
    if (n.group) n = n.members[0];
    setSel(selOfNode(n), true);
  }
  function navSel(key) {
    var n = curNode(), t = null;
    if (!n) {
      if (key === 'ArrowUp' && S.sel && S.sel.kind === 'nokey') { t = S.byId[S.sel.parentId]; if (t && t.root) t = null; }
    } else if (key === 'ArrowUp') t = n.parent && !n.parent.root ? n.parent : null;
    else if (key === 'ArrowDown') t = flatKids(n)[0] || null;
    else {
      var sib = flatKids(n.parent), i = sib.indexOf(n);
      t = sib[i + (key === 'ArrowLeft' ? -1 : 1)] || null;
    }
    if (!t) return false;
    var hadFocus = document.activeElement && document.activeElement.closest && document.activeElement.closest('#rv-dock-tree');
    setSel(selOfNode(t), true);
    if (hadFocus) { var row = treeRow(t.id); if (row) row.focus(); }
    return true;
  }
  function treeRow(id) {
    var rows = $('rv-dock-tree').querySelectorAll('.rv-node[data-node]');
    for (var i = 0; i < rows.length; i++) if (rows[i].getAttribute('data-node') === id) return rows[i];
    return null;
  }
  /* 트리 칸의 스크롤 컨테이너(넓은 화면 = 열, 1280 미만 = 세로로 쌓인 도크 본문) */
  function treeScroller() {
    var col = $('rv-dock-tree').closest('.rv-dock-col'), cols = $('rv-dock-cols');
    return col && getComputedStyle(col).overflowY !== 'visible' ? col : cols;
  }
  function renderTree() {
    var box = $('rv-dock-tree'), sc = treeScroller(), top = sc.scrollTop, sel = S.sel, onPath = {}, byKey = keyCounts();
    clear(box);
    var start = curNode() || (sel && sel.kind === 'nokey' ? S.byId[sel.parentId] : null);
    for (var x = start; x; x = x.parent) { onPath[x.id] = 1; if (x.grp) onPath[x.grp.id] = 1; }
    if (!S.tree || !S.tree.kids.length) {
      var why = S.access ? '보이는 의미 노드(data-area·data-template·data-variant·data-new)가 없다.'
        : S.lib.keysSt === 'loading' ? '키 데이터를 읽는 중…' : '키 데이터 없음 — ' + LIB_CMD;
      add(box, h('div', { class: 'mut rv-empty', text: why }));
      return;
    }
    function emit(e, depth, hide) {
      var isG = !!e.group, kids = isG ? e.members : e.entries, has = !!(kids && kids.length);
      var open = has && (hasOwn(S.treeOpen, e.id) ? S.treeOpen[e.id] : isG ? !!onPath[e.id] : true);
      var on = !isG && !!sel && sel.nid === e.id;
      var label = isG ? nodeLabel(e) + ' ×' + e.members.length : e.grp ? (e.idx != null ? e.idx : '#' + e.inst) : nodeLabel(e);
      if (!isG && e.fromKeys && e.count > 1) label += ' ×' + e.count;
      var row = h('div', { class: 'rv-node' + (isG ? ' group' : '') + (on ? ' on' : '') + (onPath[e.id] && !on ? ' path' : ''),
        role: 'treeitem', 'data-node': e.id, 'aria-level': depth + 1, 'aria-selected': on ? 'true' : 'false',
        'aria-expanded': has ? (open ? 'true' : 'false') : null, tabindex: on ? '0' : '-1', 'data-area': e.area || null,
        'data-template': e.template || null, 'data-count': isG ? e.members.length : null, hidden: hide });
      row.style.setProperty('--d', depth);  /* 들여쓰기·안내선은 CSS(--d) */
      add(row, has ? h('button', { type: 'button', class: 'rv-tw', 'data-tw': e.id, tabindex: '-1', 'aria-label': open ? '접기' : '펼치기', text: open ? '▾' : '▸' })
        : h('span', { class: 'rv-tw0' }),
        h('span', { class: 'rv-nl' + (e.area && !e.grp ? ' k' : '') + (!e.area && !e.template && e.nw ? ' nw' : ''), text: label }));
      if (!e.grp && e.area && e.template) add(row, h('span', { class: 'tag c', text: e.template }));
      if (!e.grp && e.variant) add(row, h('span', { class: 'mut rv-nv', text: e.variant.slice(0, 40) }));
      if (e.area && !e.grp) add(row, counts(byKey[e.area]));
      add(box, row);
      if (has) kids.forEach(function (k) { emit(k, depth + 1, hide || !open); });
      if (!isG && sel && sel.kind === 'nokey' && sel.parentId === e.id) keylessRow(depth + 1, hide || !open);
    }
    function keylessRow(depth, hide) {
      var r = h('div', { class: 'rv-node keyless on', role: 'treeitem', 'data-node': 'keyless', 'aria-level': depth + 1, 'aria-selected': 'true',
        tabindex: '0', hidden: hide }, h('span', { class: 'rv-tw0' }), h('span', { class: 'rv-nl', text: '키 없음' }),
        h('span', { class: 'mut rv-nv mono', text: String(sel.selector || '').slice(-60) }));
      r.style.setProperty('--d', depth);
      add(box, r);
    }
    S.tree.entries.forEach(function (e) { emit(e, 0, false); });
    if (sel && sel.kind === 'nokey' && sel.parentId === 'root') keylessRow(0, false);
    sc.scrollTop = top;
    var cur = box.querySelector('.rv-node.on');  /* 선택 행이 안 보이면 트리 칸 안에서만 스크롤(문서는 건드리지 않는다) */
    if (cur && !cur.hidden) {
      var cr = cur.getBoundingClientRect(), br = sc.getBoundingClientRect();
      if (cr.top < br.top || cr.bottom > br.bottom) sc.scrollTop += cr.top - br.top - sc.clientHeight / 3;
    }
  }
  function renderCrumb() {
    var box = clear($('rv-dock-crumb')), chain = [];
    for (var x = curNode() || (S.sel && S.sel.kind === 'nokey' ? S.byId[S.sel.parentId] : null); x && !x.root; x = x.parent) chain.unshift(x);
    add(box, h('button', { type: 'button', class: 'rv-crumb', 'data-node': 'root', text: '화면' }));
    chain.forEach(function (n) {
      add(box, h('span', { class: 'sep', text: '›' }), h('button', { type: 'button', class: 'rv-crumb' + (S.sel && S.sel.nid === n.id ? ' on' : ''),
        'data-node': n.id, text: nodeLabel(n) + (n.inst ? ' ' + (n.idx != null ? n.idx : '#' + n.inst) : '') }));
    });
    if (S.sel && S.sel.kind === 'nokey') add(box, h('span', { class: 'sep', text: '›' }), h('span', { class: 'rv-crumb keyless', 'data-node': 'keyless', text: '키 없음' }));
    var note = $('rv-dock-note');
    note.textContent = S.missingKey ? '이 상태엔 ' + S.missingKey + ' 없음' : '';
    note.classList.toggle('hidden', !S.missingKey);
  }

  /* ---------------------------------------------------------------- 도크 ② 컴포넌트 뷰어 */
  function safePath(p) { return typeof p === 'string' && p.length > 0 && p.length < 400 && !/[:\\]/.test(p) && p.charAt(0) !== '/' && !/(^|\/)\.\.(\/|$)/.test(p); }
  function selKey() { var n = curNode(); return n && n.area ? n.area : S.sel ? S.sel.component || null : null; }
  function cropFor() {
    var k = selKey(), keys = keysState(S.state || S.fileState), v = k && keys ? keys[k] : null;
    return v && safePath(v.crop) ? '../' + v.crop : null;
  }
  function srcFor(k) {
    var K = S.lib.keys, t = K && K.targets ? K.targets[curTarget()] : null, s = k && t && t.src ? t.src[k] : null;
    return Array.isArray(s) && s.length ? s.filter(function (x) { return typeof x === 'string'; }).join(', ') : null;
  }
  function renderProps() {
    var sel = S.sel, n = curNode(), v = {};
    if (sel) {
      v.area = n ? n.area : sel.component;
      v.template = n ? n.template : sel.template;
      v.variant = n ? n.variant : null;
      v['new'] = n ? n.nw : null;
      if (sel.bbox) { v.size = sel.bbox.w + '×' + sel.bbox.h; v.pos = sel.bbox.x + ',' + sel.bbox.y; }
      v.src = srcFor(n ? n.area : null);
      if (sel.kind === 'nokey') v.area = '키 없음';
    }
    [].forEach.call($('rv-props').querySelectorAll('tr[data-prop]'), function (tr) {
      var val = v[tr.getAttribute('data-prop')];
      tr.querySelector('td').textContent = val == null || val === '' ? '—' : String(val);
    });
  }
  /* 비교 띠: keys 데이터에서 같은 키(와이어↔목업은 keymap)가 있는 다른 상태·다른 시안·다른 단계의 크롭 */
  function reviewUrlK(stage, ver, state, key) {
    return 'review.html?screen=' + encodeURIComponent(SCREEN) + '&stage=' + encodeURIComponent(stage) + '&v=' + encodeURIComponent(ver) +
      '&state=' + encodeURIComponent(state) + '&k=' + encodeURIComponent(key);
  }
  function mappedKey(key, fromStage, toStage) {
    var K = S.lib.keys, map = K && K.keymap && K.keymap.map && typeof K.keymap.map === 'object' ? K.keymap.map : {};
    if (fromStage === toStage) return key;
    if (fromStage === 'wire') return typeof map[key] === 'string' ? map[key] : key;
    var back = Object.keys(map).filter(function (w) { return map[w] === key; })[0];
    return back || key;
  }
  function renderStrip() {
    var box = clear($('rv-strip')), key = selKey(), K = S.lib.keys;
    if (!S.sel) return;
    if (!K || !K.targets) { add(box, h('div', { class: 'mut rv-empty', text: S.lib.keysSt === 'loading' ? '비교 데이터를 읽는 중…' : '비교 데이터 없음 — ' + LIB_CMD })); return; }
    if (!key) { add(box, h('div', { class: 'mut rv-empty', text: '키 없는 대상 — 비교 없음' })); return; }
    var curSt = S.state || S.fileState, n = 0;
    (S.screen.stages || []).forEach(function (st) {
      var tk = st.stage + '/' + st.version, t = K.targets[tk];
      if (!t || !t.states) return;
      var k = mappedKey(key, STAGE, st.stage);
      (st.states || []).forEach(function (sd) {
        if (tk === curTarget() && sd.id === curSt) return;
        var ks = t.states[sd.id] && t.states[sd.id].keys, v = ks ? ks[k] : null;
        if (!v || !KEY_RE.test(k)) return;
        n++;
        add(box, h('a', { class: 'rv-strip-item', href: reviewUrlK(st.stage, st.version, sd.id, k), 'data-target': tk, 'data-state': sd.id,
          title: variantLabel(st) + ' · ' + (sd.label || sd.id) + (k !== key ? ' · 키 ' + k : '') },
          safePath(v.crop) ? h('img', { src: '../' + v.crop, alt: k, loading: 'lazy' }) : h('span', { class: 'mut rv-strip-none', text: '없음' }),
          h('span', { class: 'cap', text: st.version + ' · ' + sd.id })));
      });
    });
    if (!n) add(box, h('div', { class: 'mut rv-empty', text: '다른 상태·시안·단계에 같은 키 없음' }));
  }
  /* 확대 뷰: live = 두 번째 iframe 을 같은 상태로 진입시켜 bbox(+16px)에 맞춘다. 같은 상태 안 이동은 transform 만 */
  function zoomEnsure() {
    if (S.zf.frame || !S.access) return;
    var f = h('iframe', { id: 'rv-zoom-frame', title: '확대 뷰', tabindex: '-1', 'aria-hidden': 'true' });
    f.addEventListener('load', function () {
      var w = null, d = null;
      try { w = f.contentWindow; if (w.location.href === 'about:blank') return; d = f.contentDocument; } catch (e) { d = null; }
      S.zf.win = d && d.body ? w : null; S.zf.doc = d && d.body ? d : null; S.zf.ready = !!S.zf.doc; S.zf.state = null;
      syncZoom();
    });
    f.style.width = W + 'px'; f.style.height = S.H + 'px';
    $('rv-zoom-stage').appendChild(f);
    S.zf.frame = f;
    f.src = frame.src;
  }
  function zoomMode(mode, note) {
    var none = $('rv-zoom-none');
    $('rv-zoom').setAttribute('data-mode', mode);
    $('rv-zoom-img').classList.toggle('hidden', mode !== 'crop');
    none.classList.toggle('hidden', mode !== 'none');
    none.classList.toggle('warn', !!note);
    none.textContent = note || '확대 이미지 없음';
    if (S.zf.frame) S.zf.frame.classList.toggle('hidden', mode !== 'live');
  }
  function syncZoom() {
    var img = $('rv-zoom-img'), sel = S.sel, mode = 'none', crop = null;
    if (sel && S.access) mode = 'live';
    else if (sel) { crop = cropFor(); if (crop) mode = 'crop'; }
    zoomMode(mode);
    if (mode === 'crop') { if (img.getAttribute('src') !== crop) img.setAttribute('src', crop); }
    else if (img.hasAttribute('src')) img.removeAttribute('src');
    if (mode !== 'live' || $('rv-dock').classList.contains('folded')) return;  /* 접힌 도크에선 확대 iframe 을 만들거나 재진입하지 않는다 */
    zoomEnsure();
    if (!S.zf.ready) return;
    if (S.state && S.zf.state !== S.state) {
      /* 실패하면 S.zf.state 를 커밋하지 않는다 → 다음 동기화(선택 이동·재렌더)에서 다시 진입. 같은 상태 연속 실패는 ZOOM_TRIES 번까지 */
      if (S.zf.failState !== S.state) { S.zf.failState = S.state; S.zf.failN = 0; S.zf.err = null; }
      if (S.zf.failN >= ZOOM_TRIES) { zoomMode('none', '확대 재진입 실패 — ' + S.zf.err + ' (' + ZOOM_TRIES + '회 시도 후 중단, 상태 버튼을 다시 누르면 재시도)'); return; }
      var fail = runSteps(S.zf.win, stateDef(S.state) || { steps: [] });
      if (fail) {
        S.zf.failN++; S.zf.err = fail;
        S.zf.frame.setAttribute('data-error', fail);
        zoomMode('none', '확대 재진입 실패 — ' + fail + (S.zf.failN >= ZOOM_TRIES ? ' (' + ZOOM_TRIES + '회 시도 후 중단, 상태 버튼을 다시 누르면 재시도)' : ' (다음 선택 때 다시 시도)'));
        return;
      }
      S.zf.state = S.state; S.zf.failN = 0; S.zf.err = null;
      S.zf.frame.setAttribute('data-state', S.state);
      S.zf.frame.removeAttribute('data-error');
      fitZoom();
      zoomSettle();
      return;
    }
    fitZoom();
  }
  /* data-ready="<state>" = 확대 iframe 이 그 상태의 이미지 디코드를 마치고 두 프레임을 그린 뒤.
     steps 직후(data-state)에는 아직 첫 페인트 전이라, 큰 이미지를 가진 산출물은 그 뒤 프레임에서 메인 스레드를 오래 잡는다 */
  function zoomSettle() {
    var f = S.zf.frame, token = (S.zf.settle || 0) + 1, imgs = [];
    S.zf.settle = token;
    f.removeAttribute('data-ready');
    try { imgs = [].slice.call(S.zf.doc.images || []); } catch (e) { imgs = []; }
    Promise.all(imgs.map(function (im) { return im.decode ? im.decode().catch(function () { return null; }) : null; })).then(function () {
      requestAnimationFrame(function () { requestAnimationFrame(function () {
        if (S.zf.settle === token && S.zf.frame === f) f.setAttribute('data-ready', S.zf.state || '');
      }); });
    });
  }
  function fitZoom() {
    var f = S.zf.frame, sel = S.sel, stage = $('rv-zoom-stage'), bb = null;
    if (!f || !sel || !S.zf.doc) return;
    if (sel.selector) {
      try {
        var el = S.zf.doc.querySelector(sel.selector), r = el ? el.getBoundingClientRect() : null;
        if (r && r.width > 0 && r.height > 0) bb = { x: r.left + (S.zf.win.scrollX || 0), y: r.top + (S.zf.win.scrollY || 0), w: r.width, h: r.height };
      } catch (e) { bb = null; }
    }
    if (!bb) bb = sel.bbox;
    var sw = stage.clientWidth, sh = stage.clientHeight;
    if (!bb || !sw || !sh) return;
    var pad = 16, x = bb.x - pad, y = bb.y - pad, w = bb.w + pad * 2, hh = bb.h + pad * 2;
    var s = Math.min(sw / w, sh / hh, ZOOM_MAX);  /* 작은 컴포넌트는 칸에 맞춰 키운다(상한 ZOOM_MAX) */
    var tx = (sw - w * s) / 2 - x * s, ty = (sh - hh * s) / 2 - y * s;
    f.style.height = Math.max(S.H, Math.ceil(bb.y + bb.h + pad * 4)) + 'px';
    f.style.transform = 'translate(' + tx.toFixed(2) + 'px,' + ty.toFixed(2) + 'px) scale(' + s.toFixed(4) + ')';
    f.setAttribute('data-fit', [Math.round(x), Math.round(y), Math.round(w), Math.round(hh)].join(','));
  }

  /* ---------------------------------------------------------------- 도크 ③ 라이브러리 */
  /* <script> 삽입 로드(file:// 호환). src 는 호출자가 패턴·실존을 확인한 값만 */
  function loadScript(src) {
    return new Promise(function (res) {
      var s = document.createElement('script'), done = false, timer = 0;
      function end(ok) { if (done) return; done = true; clearTimeout(timer); s.onload = s.onerror = null; s.remove(); res(ok); }
      s.src = src;
      s.onload = function () { end(true); };
      s.onerror = function () { end(false); };
      timer = setTimeout(function () { end(false); }, SCRIPT_TIMEOUT);  /* 응답이 안 오면 error 와 같은 안내 */
      document.head.appendChild(s);
    });
  }
  function loadLib() {
    loadScript('library/index.js').then(function (ok) {
      var d = ok ? window.UIA_LIB_INDEX : null;
      S.lib.index = d && d.templates && typeof d.templates === 'object' ? d : null;
      S.lib.idxSt = S.lib.index ? 'ready' : 'error';
      renderDock();
    });
    if (!SCREEN_RE.test(SCREEN)) { S.lib.keysSt = 'error'; return; }
    loadScript('library/keys-' + SCREEN + '.js').then(function (ok) {
      var all = ok ? window.UIA_LIB_KEYS : null, d = hasOwn(all, SCREEN) ? all[SCREEN] : null;
      S.lib.keys = d && d.targets && typeof d.targets === 'object' ? d : null;
      S.lib.keysSt = S.lib.keys ? 'ready' : 'error';
      if (!S.access) renderComps(); else renderDock();
      applyKey0();
    });
  }
  function validSlug(s) { return typeof s === 'string' && SLUG_RE.test(s) && !!S.lib.index && hasOwn(S.lib.index.templates, s); }
  function loadCard(slug) {
    if (!validSlug(slug) || hasOwn(S.lib.cards, slug)) return;
    var cached = window.UIA_LIB && hasOwn(window.UIA_LIB, slug) ? window.UIA_LIB[slug] : null;
    if (cached) { S.lib.cards[slug] = cached; return; }
    S.lib.cards[slug] = 'loading';
    loadScript('library/' + encodeURIComponent(slug) + '.js').then(function (ok) {
      var d = ok && window.UIA_LIB && hasOwn(window.UIA_LIB, slug) ? window.UIA_LIB[slug] : null;
      S.lib.cards[slug] = d && typeof d === 'object' ? d : 'error';
      S.lib.sig = '';
      renderLib();
    });
  }
  /* 7.5: slug = 선택 노드 template → (data-new 면 '새 요소') → 조상 template → 와이어면 mockupUse */
  function libTarget() {
    var sel = S.sel, n = curNode();
    if (!sel) return null;
    if (S.lib.override && S.lib.override.nid === sel.nid) return { slug: S.lib.override.slug };
    var own = n ? n.template : sel.kind === 'nokey' ? null : sel.template;
    if (own) return { slug: own, own: true };
    if (n && n.nw) return { nw: n.nw, anc: ancestorTpl(n) };
    var anc = n ? ancestorTpl(n) : sel.template;
    if (anc) return { slug: anc };
    var K = S.lib.keys, key = selKey(), mu = K && K.mockupUse ? K.mockupUse[curTarget()] : null, u = key && mu ? mu[key] : null;
    if (STAGE === 'wire' && u && typeof u.template === 'string' && u.template) return { slug: u.template, use: u };
    return { none: true };
  }
  function libState(st) { $('rv-dock-lib').setAttribute('data-state', st); }
  function renderLib() {
    var box = $('rv-dock-lib'), sel = S.sel, t = libTarget(), n = curNode();
    var sig = JSON.stringify([sel ? sel.nid || sel.selector || sel.component : null, t, S.lib.idxSt, S.lib.stack, S.readOnly, n ? n.variant : null,
      S.lib.stack.length ? typeof S.lib.cards[S.lib.stack[S.lib.stack.length - 1]] : null]);
    if (sig === S.lib.sig) return;  /* 같은 내용이면 다시 그리지 않는다(노드 트리가 클 수 있다) */
    S.lib.sig = sig;
    clear(box);
    add(box, h('h4', { text: '③ 라이브러리' }));
    if (!sel) { libState('none'); add(box, h('div', { class: 'mut rv-empty', text: '컴포넌트를 고르면 그 템플릿 카드가 보인다.' })); return; }
    if (S.lib.idxSt === 'loading') { libState('loading'); add(box, h('div', { class: 'mut rv-empty', text: '라이브러리 인덱스를 읽는 중…' })); return; }
    if (S.lib.idxSt === 'error') { libErr(box, '라이브러리 인덱스(library/index.js)를 못 읽었다.'); return; }
    if (t.none) { S.lib.base = null; S.lib.stack = []; libState('none'); add(box, h('div', { class: 'mut rv-empty', text: '이 노드와 조상에 템플릿이 없다.' })); return; }
    if (t.nw) {
      S.lib.base = null; S.lib.stack = [];
      libState('none');
      add(box, h('div', { class: 'rv-lnew' }, h('b', { text: '새 요소 — 템플릿 없음' }), h('p', { class: 'rv-text', text: t.nw }),
        t.anc ? h('button', { type: 'button', class: 'rv-link rv-lib-anc', 'data-slug': t.anc, text: '조상 템플릿 ' + t.anc + ' 카드 보기' }) : null));
      return;
    }
    if (S.lib.base !== t.slug || !S.lib.stack.length) { S.lib.base = t.slug; S.lib.stack = [t.slug]; }
    if (t.use) add(box, h('div', { class: 'rv-lib-use', id: 'rv-lib-use', text: '목업에서 사용: ' + t.slug + ' (' + (t.use.version || '?') + ' · ' + (t.use.state || '?') + ')' }));
    var cur = S.lib.stack[S.lib.stack.length - 1];
    var crumb = h('div', { class: 'rv-lib-crumb', id: 'rv-lib-crumb' });
    S.lib.stack.forEach(function (s, i) {
      if (i) add(crumb, h('span', { class: 'sep', text: '›' }));
      add(crumb, h('button', { type: 'button', class: 'rv-lcrumb' + (i === S.lib.stack.length - 1 ? ' on' : ''), 'data-i': i, text: s }));
    });
    if (S.lib.stack.length > 1) add(crumb, h('button', { type: 'button', class: 'rv-x', id: 'rv-lib-back', text: '‹ 뒤로' }));
    add(box, crumb);
    if (!validSlug(cur)) { libState('missing'); add(box, h('div', { class: 'warn rv-empty', text: '템플릿 인덱스에 없음: ' + cur })); return; }
    loadCard(cur);
    var card = S.lib.cards[cur];
    if (card === 'loading') { libState('loading'); add(box, h('div', { class: 'mut rv-empty', text: cur + ' 카드를 읽는 중…' })); return; }
    if (!card || card === 'error') { libErr(box, cur + ' 카드 데이터(library/' + cur + '.js)를 못 읽었다.'); return; }
    libState('ready');
    var matchVar = S.lib.stack.length === 1 && t.own && n && n.variant ? n.variant : null;
    add(box, cardEl(cur, S.lib.index.templates[cur] || {}, card, matchVar));
  }
  function libErr(box, what) {
    libState('error');
    add(box, h('div', { class: 'rv-fbnote' }, h('b', { text: what }), h('div', { class: 'rv-cmd' }, '라이브러리 빌드: ', h('code', { text: LIB_CMD }))));
  }
  function num(v) { return typeof v === 'number' && isFinite(v) ? String(v) : '—'; }
  function cardEl(slug, meta, d, matchVar) {
    var c = h('div', { class: 'rv-lcard', id: 'rv-lib-card', 'data-slug': slug });
    var head = h('div', { class: 'rv-lhead' });
    if (safePath(meta.thumb)) add(head, h('img', { class: 'rv-lthumb', src: '../' + meta.thumb, alt: slug, loading: 'lazy' }));
    var info = h('div', { class: 'rv-linfo' }, h('b', { class: 'rv-lname', text: String(d.name || meta.name || slug) }), h('code', { text: slug }),
      h('div', { class: 'mut', text: '사용 ' + num(meta.usage) + ' · 화면 ' + num(meta.screens) + (meta.tier ? ' · ' + meta.tier : '') + (meta.kind ? ' · ' + meta.kind : '') }));
    if (safePath(meta.page)) add(info, h('a', { class: 'rv-link', href: '../' + meta.page, target: '_blank', rel: 'noopener', text: '카탈로그 페이지 ›' }));
    add(head, info);
    add(c, head);
    var scr = (Array.isArray(d.screens) ? d.screens : []).filter(function (s) { return s && typeof s.slug === 'string'; });
    if (scr.length) {
      add(c, h('div', { class: 'rv-lscreens' }, h('span', { class: 'mut', text: '쓰는 화면 ' }), scr.map(function (s) {
        return safePath(s.page) ? h('a', { class: 'tag', href: '../' + s.page, target: '_blank', rel: 'noopener', text: s.slug }) : h('span', { class: 'tag', text: s.slug });
      })));
    }
    /* 노드 트리(1.1 라이브러리 축) — 중첩 템플릿 ▸ 로 그 카드에 들어간다 */
    var nodes = h('div', { class: 'rv-lnodes', id: 'rv-lib-nodes' }), matched = false;
    (Array.isArray(d.nodes) ? d.nodes : []).forEach(function (nd) {
      if (!nd || typeof nd !== 'object') return;
      var depth = Math.max(0, Math.min(30, parseInt(nd.depth, 10) || 0)), name = String(nd.name == null ? '' : nd.name);
      var isMatch = !!matchVar && !matched && (name === matchVar || (typeof nd.path === 'string' && nd.path.slice(-(matchVar.length + 1)) === '/' + matchVar));
      if (isMatch) matched = true;
      var row = h('div', { class: 'rv-lnode' + (isMatch ? ' match' : '') + (nd.active === false ? ' off' : ''), 'data-depth': depth, title: typeof nd.path === 'string' ? nd.path : '' },
        h('span', { class: 'nm', text: name }), h('span', { class: 'mut sz', text: num(nd.w) + '×' + num(nd.h) }));
      row.style.setProperty('--d', depth);
      if (nd.template && validSlug(nd.template)) add(row, h('button', { type: 'button', class: 'rv-drill', 'data-slug': nd.template, title: nd.template + ' 카드로', text: '▸ ' + nd.template }));
      else if (nd.template) add(row, h('span', { class: 'tag', text: String(nd.template) }));
      add(nodes, row);
    });
    if (!nodes.firstChild) add(nodes, h('div', { class: 'mut rv-empty', text: '배치 데이터 없음' }));
    if (d.truncated && typeof d.truncated === 'object') add(nodes, h('div', { class: 'mut rv-empty', text: '잘림: ' + num(d.truncated.kept) + '개 표시 · ' + num(d.truncated.dropped) + '개 생략' }));
    add(c, h('h5', { text: '노드' }));
    if (matchVar) add(c, matched ? h('div', { class: 'mut rv-lmatch', text: '대응: variant ' + matchVar }) : h('div', { class: 'warn rv-lmatch', id: 'rv-lib-nomatch', text: '대응 없음 — variant ' + matchVar }));
    add(c, nodes);
    var kit = h('div', { class: 'rv-lkit', id: 'rv-lib-kit' });
    (Array.isArray(d.kit) ? d.kit : []).forEach(function (k) {
      if (!k || typeof k !== 'object') return;
      add(kit, h('div', { class: 'rv-lkrow' }, h('b', { text: String(k.group || '') + ' / ' + String(k.element || '') }), ' ',
        h('code', { text: String(k.kitClass || '') }), k.slice && k.slice !== '-' ? h('span', { class: 'mut', text: ' · 9-slice ' + String(k.slice) }) : null,
        k.note ? h('div', { class: 'mut', text: String(k.note) }) : null));
    });
    if (!kit.firstChild) add(kit, h('div', { class: 'mut rv-empty', text: '키트에 없음' }));
    add(c, h('h5', { text: '키트' }), kit);
    var rules = h('ul', { class: 'rv-lrules', id: 'rv-lib-rules' });
    (Array.isArray(d.rules) ? d.rules : []).forEach(function (r) {
      if (r && typeof r === 'object') add(rules, h('li', null, h('span', { class: 'mono mut', text: String(r.file || '') + ':' + num(r.line) + ' ' }), String(r.text || '')));
    });
    if (!rules.firstChild) add(rules, h('li', { class: 'mut', text: '규칙 언급 없음' }));
    add(c, h('h5', { text: '규칙' }), rules);
    var alts = h('div', { class: 'rv-lalts', id: 'rv-lib-alts' });
    (Array.isArray(meta.alts) ? meta.alts : []).forEach(function (a) {
      if (!validSlug(a)) return;
      var am = S.lib.index.templates[a] || {};
      add(alts, h('div', { class: 'rv-alt', 'data-slug': a }, h('code', { text: a }), h('span', { class: 'mut', text: String(am.name || '') + ' · 사용 ' + num(am.usage) }),
        h('button', { type: 'button', class: 'rv-suggest', 'data-slug': a, 'data-from': slug, disabled: S.readOnly,
          title: S.readOnly ? '읽기 전용 — 서버를 켜야 제안을 남긴다' : '이 템플릿으로 교체 제안(작성 폼을 채운다)', text: '교체 제안' })));
    });
    if (!alts.firstChild) add(alts, h('div', { class: 'mut rv-empty', text: '대안 없음(키트 묶음 없음)' }));
    add(c, h('h5', { text: '대안' }), alts);
    return c;
  }

  /* ---------------------------------------------------------------- 도크 틀 */
  function dockOpen() { var d = $('rv-dock'); return !!d && d.getAttribute('data-open') === '1'; }
  function setDockOpen(open) {
    var d = $('rv-dock');
    if (dockOpen() === open) return;
    d.classList.toggle('hidden', !open);
    if (open) d.setAttribute('data-open', '1'); else d.removeAttribute('data-open');
    $('rv-docktoggle').setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open) renderDock();
    measure(); schedule();
  }
  function openDock() { setDockOpen(true); }
  function setDockH(px) {
    var max = Math.max(DOCK_HMIN, Math.round(innerHeight * 0.7));
    px = Math.max(DOCK_HMIN, Math.min(max, Math.round(px)));
    $('rv-dock').style.setProperty('--dock-h', px + 'px');
    return px;
  }
  function bindDock() {
    var d = $('rv-dock'), grip = $('rv-dock-grip');
    try { var saved = parseInt(localStorage.getItem(DOCK_KEY), 10); if (saved > 0) setDockH(saved); } catch (e) { /* 저장소 없음 — 기본 높이 */ }
    $('rv-docktoggle').addEventListener('click', function () { setDockOpen(!dockOpen()); });
    $('rv-dock-fold').addEventListener('click', function () {
      var folded = !d.classList.contains('folded');
      d.classList.toggle('folded', folded);
      this.setAttribute('aria-expanded', folded ? 'false' : 'true');
      this.textContent = folded ? '펼치기' : '접기';
      if (!folded) renderDock();
      measure(); schedule();
    });
    var dragging = false;
    grip.addEventListener('pointerdown', function (e) {
      if (dragging || d.classList.contains('folded')) return;  /* 진행 중 드래그가 있으면 리스너를 겹쳐 달지 않는다 */
      dragging = true;
      e.preventDefault();
      var y0 = e.clientY, h0 = d.getBoundingClientRect().height, last = h0;
      try { grip.setPointerCapture(e.pointerId); } catch (x) { /* 캡처 불가 */ }
      function mv(ev) { last = setDockH(h0 + (y0 - ev.clientY)); measure(); }
      function up() {
        grip.removeEventListener('pointermove', mv); grip.removeEventListener('pointerup', up); grip.removeEventListener('pointercancel', up);
        dragging = false;
        try { localStorage.setItem(DOCK_KEY, String(last)); } catch (x) { /* 이번 세션만 */ }
        measure(); schedule();
      }
      grip.addEventListener('pointermove', mv); grip.addEventListener('pointerup', up); grip.addEventListener('pointercancel', up);
    });
    /* 도크 안 클릭은 위임 하나로(재렌더해도 리스너가 쌓이지 않는다) */
    d.addEventListener('click', function (e) {
      var t = e.target && e.target.closest ? e.target : null, x;
      if (!t) return;
      if ((x = t.closest('.rv-tw'))) {
        var id = x.getAttribute('data-tw'), row = x.closest('.rv-node');
        S.treeOpen[id] = !(row && row.getAttribute('aria-expanded') === 'true');
        renderTree(); return;
      }
      if ((x = t.closest('#rv-dock-tree .rv-node[data-node]'))) { if (x.getAttribute('data-node') !== 'keyless') selectNodeId(x.getAttribute('data-node')); return; }
      if ((x = t.closest('.rv-crumb[data-node]'))) {
        var nid = x.getAttribute('data-node');
        if (nid === 'root') setSel(null); else if (nid !== 'keyless') selectNodeId(nid);
        return;
      }
      if ((x = t.closest('button.rv-drill[data-slug]'))) { var ds = x.getAttribute('data-slug'); if (validSlug(ds)) { S.lib.stack = S.lib.stack.concat([ds]); renderLib(); } return; }
      if ((x = t.closest('#rv-lib-back'))) { if (S.lib.stack.length > 1) { S.lib.stack = S.lib.stack.slice(0, -1); renderLib(); } return; }
      if ((x = t.closest('.rv-lcrumb[data-i]'))) { S.lib.stack = S.lib.stack.slice(0, (parseInt(x.getAttribute('data-i'), 10) || 0) + 1); renderLib(); return; }
      if ((x = t.closest('.rv-lib-anc[data-slug]'))) { if (S.sel && validSlug(x.getAttribute('data-slug'))) { S.lib.override = { nid: S.sel.nid, slug: x.getAttribute('data-slug') }; renderLib(); } return; }
      if ((x = t.closest('button.rv-suggest[data-slug]'))) {
        if (S.readOnly || !validSlug(x.getAttribute('data-slug'))) return;
        setSuggest({ template: x.getAttribute('data-slug'), from: x.getAttribute('data-from') });
        if (window.matchMedia && matchMedia('(max-width: 1279.98px)').matches && !$('rv').classList.contains('panel-open')) $('rv-paneltoggle').click();
        $('rv-text').focus();
      }
    });
  }
  function renderDock() {
    if (!S.screen || !dockOpen()) return;
    renderCrumb(); renderTree(); renderProps(); renderStrip(); syncZoom(); renderLib();
  }
  function updateForm() {
    var btn = $('rv-submit'), hint = $('rv-formhint'), text = $('rv-text').value.trim();
    var needSuggest = S.kind === 'template' && !S.suggest;
    var noAnchor = !!S.sel && !S.sel.component && !(S.sel.selector && S.sel.bbox);
    if (!author()) hint.textContent = '이름을 먼저 적는다.';
    else if (!S.sel) hint.textContent = '컴포넌트를 먼저 고른다.';
    else if (noAnchor) hint.textContent = '키 없는 대상은 셀렉터·bbox 가 있어야 한다.';
    else if (needSuggest) hint.textContent = '라이브러리에서 [교체 제안]을 누른다.';
    else hint.textContent = '대상: ' + selLabel(S.sel) + (S.state ? ' · 상태 ' + S.state : '');
    btn.disabled = S.readOnly || S.busy || !author() || !S.sel || !text || text.length > 4000 || noAnchor || needSuggest;
  }
  function submitOpen() {
    var sel = S.sel, text = $('rv-text').value.trim();
    if (!sel || !text || S.readOnly) return;
    if (S.kind === 'template' && !S.suggest) return;
    var body = { type: 'open', screen: SCREEN, stage: STAGE, version: VER, kind: S.kind, text: text,
      component: sel.component || null };
    if (body.component && sel.idx != null) body.idx = String(sel.idx);
    if (sel.template) body.template = sel.template;
    if (sel.selector && (body.component === null || sel.path)) body.selector = sel.selector;
    if (sel.bbox) body.bbox = { x: sel.bbox.x, y: sel.bbox.y, w: sel.bbox.w, h: sel.bbox.h };
    if (S.state) body.state = S.state;
    if (sel.path && sel.path.length) body.path = sel.path.map(function (p) { return Object.assign({}, p); });
    if (S.kind === 'template' && S.suggest) body.suggest = { template: S.suggest.template };
    post(body, $('rv-submit'), S.formFiles.slice()).then(function (ok) {
      if (!ok) return;
      $('rv-text').value = '';
      S.formFiles.length = 0; S.formPicker.render();
      if (S.kind === 'template') setKind('visual');  /* 제안은 한 번 쓰면 끝 */
      updateForm();
    });
  }
  /* ---------------------------------------------------------------- 첨부 이미지(개정 F, 9.4) */
  var ATT_TYPES = { 'image/png': 1, 'image/jpeg': 1, 'image/gif': 1, 'image/webp': 1 };
  var ATT_MAX = 6, ATT_BYTES = 10 * 1024 * 1024, ATT_NAME_MAX = 120;
  var ATT_RE = /^feedback\/attachments\/[0-9a-f]{20}\.(png|jpg|gif|webp)$/;
  function hasFiles(e) { return !!e.dataTransfer && [].indexOf.call(e.dataTransfer.types || [], 'Files') >= 0; }
  /* 드롭 영역 밖에 파일을 떨어뜨리면 브라우저가 그 파일로 이동해 초안이 날아간다 — 문서 단위로 막는다(영역 안은 attPicker 가 처리) */
  document.addEventListener('dragover', function (e) { if (hasFiles(e)) e.preventDefault(); });
  document.addEventListener('drop', function (e) { if (hasFiles(e)) e.preventDefault(); });
  /* files = 고른 File 배열(호출자 소유 — 초안 보존용). [이미지 첨부] 버튼·칩 줄을 만들고 ta 붙여넣기(클립보드 이미지)와
     zone(없으면 ta) 위 드래그 앤 드롭을 받는다 */
  function attPicker(files, ta, zone) {
    var input = h('input', { type: 'file', accept: Object.keys(ATT_TYPES).join(','), multiple: true, class: 'hidden', tabindex: '-1', 'aria-hidden': 'true' });
    var chips = h('div', { class: 'rv-att-chips' });
    var btn = h('button', { type: 'button', class: 'rv-att-add', text: '이미지 첨부',
      title: 'png·jpg·gif·webp, 10MB 이하, 최대 6장 — 끌어다 놓기·입력칸 붙여넣기(Ctrl+V)도 된다', onclick: function () { input.click(); } });
    function changed() { render(); }
    function addFiles(list) {
      var bad = [];
      [].forEach.call(list, function (f) {
        if (!ATT_TYPES[f.type]) bad.push(f.name + ': png·jpg·gif·webp 아님');
        else if (f.size > ATT_BYTES) bad.push(f.name + ': 10MB 초과');
        else if (files.length >= ATT_MAX) bad.push(f.name + ': 최대 ' + ATT_MAX + '장');
        else files.push(f);
      });
      if (bad.length) msg('첨부 안 됨 — ' + bad.join(' · '), 'warn');
      changed();
    }
    function render() {
      [].forEach.call(chips.querySelectorAll('img[data-url]'), function (im) { URL.revokeObjectURL(im.getAttribute('data-url')); });
      clear(chips);
      files.forEach(function (f, i) {
        var url = URL.createObjectURL(f);
        add(chips, h('span', { class: 'rv-att-chip', title: f.name }, h('img', { src: url, 'data-url': url, alt: '' }),
          h('span', { class: 'nm', text: f.name }),
          h('button', { type: 'button', class: 'rv-x', text: '빼기', 'aria-label': f.name + ' 빼기',
            onclick: function () { files.splice(i, 1); changed(); } })));
      });
      btn.disabled = files.length >= ATT_MAX;
    }
    input.addEventListener('change', function () { addFiles(input.files); input.value = ''; });
    ta.addEventListener('paste', function (e) {
      var cd = e.clipboardData, items = cd ? [].slice.call(cd.items || []) : [];
      var imgs = items.filter(function (it) { return it.kind === 'file' && /^image\//.test(it.type); })
        .map(function (it) { return it.getAsFile(); }).filter(Boolean);
      if (!imgs.length) return;
      if (!cd.getData('text/plain')) e.preventDefault();  /* 이미지만 있으면 글자 붙여넣기는 없다 */
      addFiles(imgs);
    });
    zone = zone || ta;
    /* on* 프로퍼티로 단다 — 인라인 폼은 같은 zone 에서 여러 번 열리므로 매번 교체돼야 옛 files 로 가지 않는다.
       dragenter/leave 는 자식 요소마다 오므로 깊이로 센다 */
    var depth = 0;
    zone.classList.remove('rv-dropping');
    zone.ondragenter = function (e) { if (!hasFiles(e) || S.readOnly) return; depth++; zone.classList.add('rv-dropping'); };
    zone.ondragleave = function (e) { if (!hasFiles(e)) return; if (--depth <= 0) { depth = 0; zone.classList.remove('rv-dropping'); } };
    zone.ondragover = function (e) { if (hasFiles(e) && !S.readOnly) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; } };
    zone.ondrop = function (e) {
      if (!hasFiles(e)) return;
      e.preventDefault(); depth = 0; zone.classList.remove('rv-dropping');
      if (!S.readOnly) addFiles(e.dataTransfer.files);
    };
    render();
    return { el: h('div', { class: 'rv-att' }, btn, input, chips), render: render };
  }
  /* 고른 순서대로 POST /api/attachments → [{path, name}] (같은 path 는 한 번만). 하나라도 실패하면 reject */
  function uploadAll(files) {
    var out = [];
    return files.reduce(function (p, f) {
      return p.then(function () {
        return fetch('/api/attachments', { method: 'POST', headers: { 'Content-Type': f.type }, body: f })
          .then(function (r) {
            return r.json().catch(function () { return null; }).then(function (j) {
              if (r.ok && j && j.ok === true && j.attachment && ATT_RE.test(j.attachment.path)) return j.attachment.path;
              throw new Error('첨부 업로드 실패 — ' + f.name + ': ' + (j && typeof j.error === 'string' && j.error ? j.error : 'HTTP ' + r.status));
            });
          })
          .then(function (path) {
            if (out.some(function (a) { return a.path === path; })) return;
            var a = { path: path }, nm = String(f.name || '').trim().slice(0, ATT_NAME_MAX);
            if (nm) a.name = nm;
            out.push(a);
          });
      });
    }, Promise.resolve()).then(function () { return out; });
  }
  function attsRow(atts) {
    return h('div', { class: 'rv-atts' }, atts.map(function (a) {
      var p = a && a.path;
      if (typeof p !== 'string' || !ATT_RE.test(p)) return h('span', { class: 'warn rv-badpath', text: '첨부 경로 이상' });
      var label = a.name && typeof a.name === 'string' ? a.name : p.split('/').pop();
      var img = h('img', { src: '../' + p, alt: label, loading: 'lazy' }), nm = h('span', { class: 'nm', text: label });
      var link = h('a', { class: 'rv-att-item', href: '../' + p, target: '_blank', rel: 'noopener', title: label }, img, nm);
      img.addEventListener('error', function () { link.classList.add('missing'); img.remove(); nm.textContent = label + ' (이 PC 에 없음)'; });
      return link;
    }));
  }
  function post(body, btn, files) {
    if (S.readOnly || S.busy) return Promise.resolve(false);
    if (!author()) { msg('이름을 먼저 적는다(새 피드백 칸 맨 위).', 'bad'); $('rv-author').focus(); return Promise.resolve(false); }
    body.author = author();
    S.busy = true; if (btn) btn.disabled = true;
    var up = files && files.length ? uploadAll(files).then(function (atts) { body.attachments = atts; }) : Promise.resolve();
    return up.then(function () { return fetch('/api/feedback', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); })
      .then(function (r) {
        return r.json().catch(function () { return null; }).then(function (j) {
          /* 성공 = 2xx + JSON 본문 + ok === true + event (4.3). 빈 본문·비JSON 200 은 실패로 본다 */
          if (r.ok && j && typeof j === 'object' && j.ok === true && j.event && typeof j.event === 'object') return j;
          var why = j && typeof j === 'object' && typeof j.error === 'string' && j.error ? j.error
            : r.ok ? '서버 응답 형식 오류(HTTP ' + r.status + ')' : 'HTTP ' + r.status;
          throw new Error(why);
        });
      })
      .then(function (j) {
        var id = j.event.id || (Array.isArray(j.event.ids) ? j.event.ids[0] : null);
        var saved = (TYPE_L[body.type] || body.type) + ' 저장됨' + (id ? ' — ' + id : '');
        msg(saved, 'ok');
        if (body.type === 'open' && id && S.sel) S.sel.focus = id;
        return refresh().then(function (fresh) {
          if (!fresh) msg(saved + ' · 최신 목록을 못 받음, 새로고침', 'warn');  /* 저장은 성공 — 재조회 실패만 약하게 알린다 */
          return true;
        });
      })
      .catch(function (e) { msg('저장 실패: ' + (e && e.message ? e.message : e), 'bad'); return false; })
      .then(function (ok) { S.busy = false; updateForm(); if (btn && btn.id !== 'rv-submit') btn.disabled = false; syncInlines(); return ok; });
  }
  /* busy 동안 다시 그려진 인라인 폼의 보내기 버튼은 disabled 로 태어난다 — busy 가 풀리면 다시 맞춘다 */
  function syncInlines() {
    [].slice.call(document.querySelectorAll('#rv-thread .rv-inline:not(.hidden)')).forEach(function (n) {
      var ta = n.querySelector('textarea'), go = n.querySelector('.rv-go');
      if (ta && go) go.disabled = S.busy || (n.getAttribute('data-kind') !== 'close' && !ta.value.trim());
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
