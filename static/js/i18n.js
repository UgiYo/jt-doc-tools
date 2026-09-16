/* 前端字串翻譯。
 *
 * 樣板的 `{{ tr('…') }}` 是**伺服器端渲染時**求值的，JS 執行期拿不到 ——
 * 按鈕文字、錯誤訊息、動態插進 DOM 的說明都得走這一支。
 *
 * 用法與樣板端一致：key 就是繁體中文原文。
 *
 *     btn.textContent = tr('開始轉換');
 *
 * 查不到就原樣回傳中文 —— 這一點很重要：
 *   * 繁體中文底下字典**是空的**（連載都不用載），所以零風險零成本；
 *   * 英文底下漏翻的字串會顯示中文，而不是顯示 key 或空白。
 *
 * 帶變數的句子**一律參數化**，不可以把內插後的整句當 key（內插值一變就查不到）：
 *
 *     tr('已選：{0}').replace('{0}', file.name)
 */
(function () {
  window.__I18N__ = window.__I18N__ || {};
  window.tr = function (s) {
    if (typeof s !== 'string') return s;
    var v = window.__I18N__[s];
    return (typeof v === 'string' && v) ? v : s;
  };
})();

/* 共用字型選擇器。
 * PDF 編輯器已採用可搜尋、分組的 fp-* picker；PPT 圖片文字編輯的文字列是
 * 動態 render 出來的，因此用 MutationObserver 自動升級 .pite-style select.font。
 * 圖片文字編輯器目前已有自己的 .font-picker，遇到已包裝的 select 會跳過，避免
 * 重複包兩層。原生 select 保留在 DOM 中，既有 change handler / undo 邏輯完全不變。
 */
(function () {
  function installStyle() {
    if (document.getElementById('jt-shared-font-picker-style')) return;
    var style = document.createElement('style');
    style.id = 'jt-shared-font-picker-style';
    style.textContent =
      '.fp-wrap{position:relative;display:inline-block;min-width:190px;max-width:300px;vertical-align:middle}' +
      '.fp-wrap>select{display:none!important}' +
      '.fp-trigger{width:100%;min-height:34px;display:flex;align-items:center;justify-content:space-between;gap:8px;padding:6px 9px;background:#fff;border:1px solid #cbd5e1;border-radius:6px;color:#0f172a;cursor:pointer;text-align:left}' +
      '.fp-cur{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '.fp-pop{position:absolute;z-index:9500;top:calc(100% + 4px);left:0;width:300px;max-width:min(360px,90vw);max-height:360px;display:flex;flex-direction:column;overflow:hidden;background:#fff;border:1px solid #cbd5e1;border-radius:8px;box-shadow:0 12px 30px rgba(15,23,42,.2)}' +
      '.fp-search-row{padding:8px;border-bottom:1px solid #f1f5f9}.fp-search{width:100%;box-sizing:border-box;padding:7px 9px;border:1px solid #cbd5e1;border-radius:6px}' +
      '.fp-list{overflow:auto;min-height:0}.fp-group{padding:5px 9px;background:#eff6ff;color:#1d4ed8;font-size:12px;font-weight:700;position:sticky;top:0}' +
      '.fp-item{padding:7px 10px;cursor:pointer;color:#0f172a}.fp-item:hover,.fp-item.is-active{background:#dbeafe}.fp-empty{padding:10px;color:#64748b}';
    document.head.appendChild(style);
  }
  function esc(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }
  function groupName(text) {
    return /noto|cjk|source han|han sans|han serif|jheng|ming|hei|song|kai|tc|sc|jp|kr/i.test(text)
      ? tr('開源 CJK 字型') : tr('西文開源字型');
  }
  function enhance(select) {
    if (!select || select.dataset.sharedFontPicker === '1' || select.closest('.font-picker') || select.closest('.fp-wrap')) return;
    select.dataset.sharedFontPicker = '1';
    installStyle();
    var wrap = document.createElement('span');
    wrap.className = 'fp-wrap';
    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(select);
    wrap.insertAdjacentHTML('beforeend',
      '<button type="button" class="fp-trigger"><span class="fp-cur">Auto</span><span class="fp-caret">▾</span></button>' +
      '<div class="fp-pop" hidden><div class="fp-search-row"><input type="search" class="fp-search" placeholder="' + esc(tr('搜尋字型名稱…')) + '"></div><div class="fp-list"></div></div>');
    var trigger = wrap.querySelector('.fp-trigger');
    var current = wrap.querySelector('.fp-cur');
    var pop = wrap.querySelector('.fp-pop');
    var search = wrap.querySelector('.fp-search');
    var list = wrap.querySelector('.fp-list');
    function optionText(value) {
      var found = Array.prototype.find.call(select.options, function (o) { return o.value === value; });
      return found ? found.textContent : 'Auto';
    }
    function sync() { current.textContent = optionText(select.value); }
    function draw() {
      var q = search.value.trim().toLowerCase();
      var options = Array.prototype.slice.call(select.options).filter(function (o) { return o.value; });
      if (q) options = options.filter(function (o) { return o.textContent.toLowerCase().indexOf(q) !== -1; });
      var html = '<div class="fp-item' + (select.value === '' ? ' is-active' : '') + '" data-value="">Auto</div>';
      [tr('開源 CJK 字型'), tr('西文開源字型')].forEach(function (g) {
        var items = options.filter(function (o) { return groupName(o.textContent) === g; });
        if (!items.length) return;
        html += '<div class="fp-group">' + esc(g) + '</div>';
        items.forEach(function (o) {
          html += '<div class="fp-item' + (select.value === o.value ? ' is-active' : '') + '" data-value="' + esc(o.value) + '">' + esc(o.textContent) + '</div>';
        });
      });
      if (q && !options.length) html += '<div class="fp-empty">' + esc(tr('找不到符合的字型')) + '</div>';
      list.innerHTML = html;
      Array.prototype.forEach.call(list.querySelectorAll('.fp-item'), function (item) {
        item.addEventListener('click', function () {
          select.value = item.dataset.value;
          select.dispatchEvent(new Event('change', {bubbles:true}));
          sync(); pop.hidden = true;
        });
      });
    }
    trigger.addEventListener('click', function (e) {
      e.stopPropagation(); pop.hidden = !pop.hidden;
      if (!pop.hidden) { search.value = ''; draw(); search.focus(); }
    });
    search.addEventListener('input', draw);
    select.addEventListener('change', sync);
    document.addEventListener('click', function (e) { if (!wrap.contains(e.target)) pop.hidden = true; });
    sync();
  }
  function scan(root) {
    if (!root || root.nodeType !== 1) return;
    if (root.matches && root.matches('.pite-style select.font')) enhance(root);
    if (root.querySelectorAll) Array.prototype.forEach.call(root.querySelectorAll('.pite-style select.font'), enhance);
  }
  function start() {
    scan(document.body);
    new MutationObserver(function (records) {
      records.forEach(function (r) { Array.prototype.forEach.call(r.addedNodes, scan); });
    }).observe(document.body, {childList:true, subtree:true});
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
