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
/* 伺服器送來的**作業訊息**是先內插好的（`完成（3 份）`）——
 * 它在背景執行緒裡產生，那時候沒有 request、不知道使用者的語言，所以
 * 只能送中文，由這裡翻。但內插過的整句永遠查不到字典。
 *
 * 所以查不到時再試一次：把**連續數字換成 `{0}` `{1}`…** 之後查，
 * 查到就把數字填回去。`完成（3 份）` → 查 `完成（{0} 份）` → 
 * `Done ({0} file(s))` → `Done (3 file(s))`。
 *
 * **只在第一次查不到時才做**，而且字典裡沒有那把參數化的鍵就原樣回傳 ——
 * 也就是「最壞的情況跟現在一樣」，不會把不該動的句子改掉。
 *
 * **範圍是「變數全部是數字」的句子。** `已上傳 a.pdf（6379.1 KB）` 的第一個
 * 變數是檔名不是數字，換不出那把鍵 —— 那種要在**產生那句話的地方**自己包
 * `tr('已上傳 {0}（{1} KB）').replace(...)`。界線寫在
 * `tests/test_tr_number_pattern_fallback.py` 裡，不要以為這個退路什麼都接得住。
 */
(function () {
  window.__I18N__ = window.__I18N__ || {};
  var DIGITS = /\d[\d,.]*/g;

  function byNumberPattern(s) {
    var vals = [];
    var i = 0;
    var key = s.replace(DIGITS, function (m) { vals.push(m); return '{' + (i++) + '}'; });
    if (!vals.length || key === s) return null;
    var v = window.__I18N__[key];
    if (typeof v !== 'string' || !v) return null;
    return v.replace(/\{(\d+)\}/g, function (m, n) {
      return vals[Number(n)] !== undefined ? vals[Number(n)] : m;
    });
  }

  window.tr = function (s) {
    if (typeof s !== 'string') return s;
    var v = window.__I18N__[s];
    if (typeof v === 'string' && v) return v;
    return byNumberPattern(s) || s;
  };
})();
