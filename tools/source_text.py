"""把原始碼裡的註解換成空白，給靜態守門用。

**這個專案被自己寫的註解騙過很多次**：說明裡引用「不可以用的寫法」當反例，
字串比對就判它違規；反過來也有 —— 註解裡提到防護的名字，掃描就以為
有呼叫防護。判準只要碰得到說明文字，遲早會錯一次，所以去註解的邏輯
只留這一份共用的，不要每支測試各抄一份（NSIS 那邊已經收成
`tools/nsis_source.py`，這份是 JS / HTML / Jinja 的對應物）。

**保留行號**：註解換成等長的空白（換行照留），這樣守門報出來的行號還是對的。

**寧可少去一點也不要多去**：多去（把真的程式碼當註解刪掉）會讓守門漏掉
真違規，那比誤報更糟 —— 誤報至少有人會來看。所以字串與樣板字面裡的
`//` 不動。
"""
from __future__ import annotations

import re

__all__ = ["strip_js_comments", "strip_markup_comments"]


def _blank(text: str) -> str:
    """換成等長空白，換行保留（行號才不會跑掉）。"""
    return re.sub(r"[^\n]", " ", text)


def strip_markup_comments(text: str) -> str:
    """去掉 HTML `<!-- -->` 與 Jinja `{# #}` 註解。"""
    for pat in (r"<!--.*?-->", r"\{#.*?#\}"):
        text = re.sub(pat, lambda m: _blank(m.group(0)), text, flags=re.S)
    return text


def strip_js_comments(text: str) -> str:
    """去掉 JS 的 `/* */` 與 `//` 註解（含行尾的）。

    逐字元走過，遇到引號 / 樣板字面就跳過整段 —— 不然
    `const u = 'https://…'` 會被當成註解起點，把後面整行吃掉。
    正規表示式做不到這件事（它分不出「在字串裡」）。
    """
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in "\"'`":                      # 字串 / 樣板字面：原樣抄過去
            quote = c
            out.append(c)
            i += 1
            while i < n:
                ch = text[i]
                out.append(ch)
                i += 1
                if ch == "\\" and i < n:     # 跳脫：連下一個字一起抄
                    out.append(text[i])
                    i += 1
                elif ch == quote:
                    break
            continue
        if c == "/" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "/":
                j = text.find("\n", i)
                j = n if j < 0 else j
                out.append(_blank(text[i:j]))
                i = j
                continue
            if nxt == "*":
                j = text.find("*/", i + 2)
                j = n if j < 0 else j + 2
                out.append(_blank(text[i:j]))
                i = j
                continue
        out.append(c)
        i += 1
    return "".join(out)
