"""按「學起來」時要**把後果講出來**。

## 為什麼不是「偵測到衝突就拒絕」

我本來要讓 `add_synonym()` 在「同一個標籤已經對應到別的 key」時拒絕 ——
**去看 `_build_synonym_index` 才發現前提是錯的**：一個標籤對應到多個
canonical key 是**刻意支援的**。台灣的表單常有一格同時管兩件事
（`發票聯數 & 種類` 同時屬於 發票種類 與 稅別），讓兩個欄位各自去勾自己的
選項。改掉會讓那類表單的勾選整排失效，**而且不會有任何測試變紅**。

所以真正該做的是**把後果講出來**：使用者按一次「學起來」會寫進**全站共用**
的對照表，他該知道這個標籤已經對應到誰。
"""
from __future__ import annotations

import pytest


def test_the_endpoint_reports_the_other_keys(client):
    from app.core.synonym_manager import synonym_manager

    label = "測試用的共用標籤"
    try:
        synonym_manager.add_synonym("invoice_type", label)
        r = client.post("/tools/pdf-fill/learn-synonym",
                        json={"key": "vat_status", "label": label})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert "invoice_type" in body.get("also_maps_to", []), (
            "沒有告訴使用者這個標籤已經對應到 invoice_type："
            f"{body}")
    finally:
        # 自己建的自己收 —— 這是全站共用的檔案
        with synonym_manager._lock:                     # noqa: SLF001
            data = synonym_manager._read()              # noqa: SLF001
            for k in ("invoice_type", "vat_status"):
                lst = (data.get("synonyms") or {}).get(k) or []
                if label in lst:
                    lst.remove(label)
            synonym_manager._write(data)                # noqa: SLF001


def test_a_label_that_is_new_reports_nothing(client):
    from app.core.synonym_manager import synonym_manager

    label = "完全沒用過的標籤名稱"
    try:
        r = client.post("/tools/pdf-fill/learn-synonym",
                        json={"key": "company_name", "label": label})
        assert r.json().get("also_maps_to") == []
    finally:
        with synonym_manager._lock:                     # noqa: SLF001
            data = synonym_manager._read()              # noqa: SLF001
            lst = (data.get("synonyms") or {}).get("company_name") or []
            if label in lst:
                lst.remove(label)
            synonym_manager._write(data)                # noqa: SLF001


def test_one_label_may_still_map_to_several_keys():
    """**不可以改成「偵測到就拒絕」** —— 那是刻意支援的功能。

    這一條跟 `tests/test_one_label_can_map_to_several_keys.py` 是同一件事，
    放在這裡是因為「把後果講出來」很容易被下一個人改寫成「擋下來」。
    """
    from app.core.synonym_manager import synonym_manager

    label = "一格管兩件事的標籤"
    try:
        assert synonym_manager.add_synonym("invoice_type", label) is True
        assert synonym_manager.add_synonym("vat_status", label) is True, (
            "第二個 key 被拒絕了 —— 一個標籤對應多個 key 是刻意支援的")
        assert set(synonym_manager.keys_for(label)) >= {"invoice_type", "vat_status"}
    finally:
        with synonym_manager._lock:                     # noqa: SLF001
            data = synonym_manager._read()              # noqa: SLF001
            for k in ("invoice_type", "vat_status"):
                lst = (data.get("synonyms") or {}).get(k) or []
                if label in lst:
                    lst.remove(label)
            synonym_manager._write(data)                # noqa: SLF001
