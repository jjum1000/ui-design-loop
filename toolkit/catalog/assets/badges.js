/* ui-audit app-flow 배지 숫자 채우기 — 손으로 관리하는 원본(catalog_assets.py 가 덮어쓰지 않음).
   출처: feedback/CONTRACT.md 4.6(배지) · 4.3(GET /api/feedback) · 4.1(counts 형태).
   채우는 대상: data-uia-count="<UIType 또는 app:<contentsType>>|<stage|*>|<open|fixed>" 를 가진 모든 요소.
   stage="*" 는 그 화면에 등록된 모든 stage 의 합, "open" 은 open+reopened 합(계약 3.2 "열린"), "fixed" 는 그대로.
   "app:<contentsType>" 키는 window.UIA_FEEDBACK.registry(또는 /api/feedback 응답의 registry) 에서 그 앱(app 필드)의
   화면들을 찾아 합한다.
   데이터 출처: http(s) 로 열렸으면 GET /api/feedback 을 먼저 시도해 최신값으로 채우고, 실패하면(네트워크 오류·
   4xx/5xx·JSON 파싱 실패) window.UIA_FEEDBACK(feedback/state.js, file:// 포함)으로 채운다. 둘 다 없으면 모든
   자리를 "—"로 둔다("집계 안 됨"과 "0건"을 구분한다). 텍스트는 전부 textContent 로만 쓴다(innerHTML 금지).
   외부 라이브러리를 쓰지 않는다. */
(function () {
  'use strict';

  var STATUS_GROUPS = { open: ['open', 'reopened'], fixed: ['fixed'] };

  function sumScreen(data, screen, stage, group) {
    var counts = (data && data.counts) || {};
    var byStage = counts[screen];
    if (!byStage) return 0;
    var stages = stage === '*' ? Object.keys(byStage) : [stage];
    var total = 0;
    for (var i = 0; i < stages.length; i++) {
      var s = byStage[stages[i]];
      if (!s) continue;
      for (var j = 0; j < group.length; j++) total += s[group[j]] || 0;
    }
    return total;
  }

  function countFor(data, key, stage, status) {
    var group = STATUS_GROUPS[status] || [status];
    if (key.indexOf('app:') === 0) {
      var contentsType = key.slice(4);
      var screens = (data && data.registry && data.registry.screens) || {};
      var total = 0;
      Object.keys(screens).forEach(function (ui) {
        if (screens[ui] && screens[ui].app === contentsType) {
          total += sumScreen(data, ui, stage, group);
        }
      });
      return total;
    }
    return sumScreen(data, key, stage, group);
  }

  function fill(data) {
    var hasData = !!(data && data.counts);
    var els = document.querySelectorAll('[data-uia-count]');
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      /* R2 LOW(한계, 보고에서 설명): split('|') 은 키 자체에 '|' 가 있으면 깨진다(두 번째 구분자부터 밀림).
         키를 quote 하지 않기로 했다 — UIType·app 값은 registry 의 screens 키/`app` 필드로, C# 쪽 식별자
         (enum 이름류)라 실제로 '|' 를 포함하지 않는다. catalog_flow_badges.py 에 같은 주석을 뒀다. */
      var parts = el.getAttribute('data-uia-count').split('|');
      if (!hasData) {
        el.textContent = '—';
        continue;
      }
      el.textContent = String(countFor(data, parts[0], parts[1], parts[2]));
    }
  }

  function boot() {
    var local = window.UIA_FEEDBACK || null;
    if (location.protocol === 'http:' || location.protocol === 'https:') {
      fetch('/api/feedback', { cache: 'no-store' })
        .then(function (r) {
          if (!r.ok) throw new Error('GET /api/feedback: HTTP ' + r.status);
          return r.json();
        })
        .then(fill)
        .catch(function () { fill(local); });
    } else {
      fill(local);
    }
  }

  document.addEventListener('DOMContentLoaded', boot);
})();
