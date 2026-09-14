/* 共用的圖片放大檢視（lightbox）。
 *
 * **為什麼要收成一份**：2026-09-14 盤點時全站有 **13 份各自實作**
 * （`md2-` / `dd-` / `an-` / `ws-` / `p2i-` / `i2p-` / `bd-` / `as-` /
 *  `af-` / `dt-` / `page-` / `asset-` …），每一份的鍵盤操作、關閉方式、
 * 焦點處理都不太一樣，而且**有的根本沒有翻頁**。同一份東西寫在十三個地方，
 * 就會壞在十三個地方（本專案最常復發的那一類）。
 *
 * 用法：
 *
 *     window.jtLightbox.open(items, index)   // items: [{src, caption, load}]
 *
 * `load` 是選用的 `async () => 大圖網址`：**先用縮圖立刻開起來**，大圖回來
 * 再換掉。預覽圖多半是低解析度的（騎縫章的逐頁預覽是 78 dpi），直接開起來
 * 跟縮圖一樣大，等於沒有「看大圖」；而事先把每一頁都算一份高解析度的話，
 * 52 頁的文件會回到「每個請求 90 秒」那個老問題。
 *
 * 或宣告式（推薦）—— 容器上標 `data-lightbox`，裡面的 `<img>` 自動接線，
 * 翻頁範圍就是同一個容器裡的圖：
 *
 *     <div class="xxx-grid" data-lightbox>
 *       <img src="…" alt="第 1 頁">
 *     </div>
 *
 * 圖說取自 `data-caption`，沒有就用 `alt`。
 *
 * **樣式一律放 `platform.css`** —— CSP 的 style-src 沒有 unsafe-inline，
 * JS 動態注入的 `<style>` 會被整段擋掉，而且**不會有 JS 例外**，
 * 只是元件變成沒有樣式的 DOM 攤在頁尾（本專案踩過）。
 */
(function () {
  'use strict';
  if (window.jtLightbox) return;

  let box = null, imgEl = null, capEl = null, prevBtn = null, nextBtn = null;
  let items = [], idx = 0;

  function build() {
    if (box) return;
    box = document.createElement('div');
    box.className = 'jt-lightbox';
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    box.hidden = true;

    prevBtn = document.createElement('button');
    prevBtn.type = 'button';
    prevBtn.className = 'jt-lb-nav prev';
    prevBtn.textContent = '‹';
    nextBtn = document.createElement('button');
    nextBtn.type = 'button';
    nextBtn.className = 'jt-lb-nav next';
    nextBtn.textContent = '›';
    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'jt-lb-close';
    closeBtn.textContent = '×';

    imgEl = document.createElement('img');
    imgEl.className = 'jt-lb-img';
    imgEl.alt = '';
    capEl = document.createElement('div');
    capEl.className = 'jt-lb-cap';

    prevBtn.setAttribute('aria-label', tr('上一張'));
    nextBtn.setAttribute('aria-label', tr('下一張'));
    closeBtn.setAttribute('aria-label', tr('關閉'));
    box.setAttribute('aria-label', tr('放大檢視'));

    box.append(prevBtn, nextBtn, closeBtn, imgEl, capEl);
    document.body.appendChild(box);

    prevBtn.addEventListener('click', (e) => { e.stopPropagation(); step(-1); });
    nextBtn.addEventListener('click', (e) => { e.stopPropagation(); step(1); });
    closeBtn.addEventListener('click', (e) => { e.stopPropagation(); close(); });
    // 點背景關掉；點圖本身不關（要讓人看得久一點）
    box.addEventListener('click', (e) => { if (e.target === box) close(); });
    imgEl.addEventListener('click', (e) => e.stopPropagation());
  }

  function show() {
    const it = items[idx] || {};
    imgEl.src = it.src || '';
    imgEl.classList.toggle('is-loading', !!(it.load && !it.big));
    if (it.big) imgEl.src = it.big;
    else if (it.load) loadBig(it, idx);
    imgEl.alt = it.caption || '';
    capEl.textContent = items.length > 1
      ? `${it.caption || ''}${it.caption ? '  ' : ''}(${idx + 1}/${items.length})`
      : (it.caption || '');
    capEl.hidden = !capEl.textContent;
    const many = items.length > 1;
    prevBtn.hidden = !many;
    nextBtn.hidden = !many;
    prevBtn.disabled = idx <= 0;
    nextBtn.disabled = idx >= items.length - 1;
  }

  //: 去拿大圖。**回來時要確認使用者還停在同一張** —— 翻頁比載入快得多，
  //  不檢查的話會把上一張的大圖蓋到現在這張上面。
  async function loadBig(it, at) {
    try {
      const url = await it.load();
      if (!url) return;
      it.big = url;
      if (idx === at && box && !box.hidden) {
        imgEl.src = url;
        imgEl.classList.remove('is-loading');
      }
    } catch (e) {
      imgEl.classList.remove('is-loading');   // 拿不到就留著縮圖，不要變空白
    }
  }

  function step(d) {
    const n = idx + d;
    if (n < 0 || n >= items.length) return;
    idx = n;
    show();
  }

  function onKey(e) {
    if (!box || box.hidden) return;
    if (e.key === 'Escape') { close(); }
    else if (e.key === 'ArrowLeft') { step(-1); }
    else if (e.key === 'ArrowRight') { step(1); }
    else return;
    e.preventDefault();
  }

  function open(list, start) {
    build();
    items = (list || []).filter((x) => x && x.src);
    if (!items.length) return;
    idx = Math.min(Math.max(0, start | 0), items.length - 1);
    show();
    box.hidden = false;
    document.addEventListener('keydown', onKey);
  }

  function close() {
    if (!box) return;
    box.hidden = true;
    imgEl.src = '';               // 放開大圖，不要一直佔記憶體
    document.removeEventListener('keydown', onKey);
  }

  //: 宣告式接線。用事件委派，**之後才塞進去的縮圖也吃得到**
  //  （多數工具的預覽是上傳完才動態產生的 —— 逐個綁事件的寫法會漏掉它們）。
  document.addEventListener('click', (e) => {
    const img = e.target.closest && e.target.closest('[data-lightbox] img');
    if (!img) return;
    const host = img.closest('[data-lightbox]');
    const all = [...host.querySelectorAll('img')].filter((m) => m.getAttribute('src'));
    const list = all.map((m) => ({
      src: m.dataset.zoomSrc || m.currentSrc || m.src,
      caption: m.dataset.caption || m.alt || '',
    }));
    open(list, all.indexOf(img));
  });

  window.jtLightbox = { open, close };
})();
