# -*- coding: utf-8 -*-
"""测试 PDF 引擎回退链：detect_engine 优先级 + resolve_engine 显式引擎回退。

不依赖本机真实安装 LibreOffice / Word / WPS —— 全部用 monkeypatch 模拟。
"""
import build_pdf as bp


# ---------- detect_engine：优先级探测 ----------
def test_detect_engine_prefers_libreoffice(monkeypatch):
    monkeypatch.setattr(bp, "find_soffice", lambda: "/usr/bin/soffice")
    kind, payload = bp.detect_engine()
    assert kind == "libreoffice"
    assert payload == "/usr/bin/soffice"


def test_detect_engine_falls_to_docx2pdf(monkeypatch):
    monkeypatch.setattr(bp, "find_soffice", lambda: None)
    monkeypatch.setattr(bp, "find_docx2pdf", lambda: True)
    kind, _ = bp.detect_engine()
    assert kind == "docx2pdf"


def test_detect_engine_falls_to_wps_headless(monkeypatch):
    monkeypatch.setattr(bp, "find_soffice", lambda: None)
    monkeypatch.setattr(bp, "find_docx2pdf", lambda: False)
    monkeypatch.setattr(bp, "find_wps", lambda: ("/usr/bin/wps", "headless"))
    kind, payload = bp.detect_engine()
    assert kind == "wps"
    assert payload == ("/usr/bin/wps", "headless")


def test_detect_engine_skips_wps_subcmd(monkeypatch):
    """macOS/Windows 的 wpscli（subcmd 形态，需 VIP）不进 auto，回退纯 Python。"""
    monkeypatch.setattr(bp, "find_soffice", lambda: None)
    monkeypatch.setattr(bp, "find_docx2pdf", lambda: False)
    monkeypatch.setattr(bp, "find_wps", lambda: ("wpscli", "subcmd"))
    kind, _ = bp.detect_engine()
    assert kind == "reportlab"


def test_detect_engine_falls_to_reportlab(monkeypatch):
    monkeypatch.setattr(bp, "find_soffice", lambda: None)
    monkeypatch.setattr(bp, "find_docx2pdf", lambda: False)
    monkeypatch.setattr(bp, "find_wps", lambda: None)
    kind, _ = bp.detect_engine()
    assert kind == "reportlab"


# ---------- resolve_engine：显式引擎回退 ----------
def test_resolve_engine_auto_uses_detect(monkeypatch):
    monkeypatch.setattr(bp, "detect_engine", lambda: ("wps", ("/usr/bin/wps", "headless")))
    assert bp.resolve_engine("auto") == "wps"


def test_resolve_engine_explicit_libreoffice_unavailable(monkeypatch):
    monkeypatch.setattr(bp, "find_soffice", lambda: None)
    assert bp.resolve_engine("libreoffice") == "reportlab"


def test_resolve_engine_explicit_libreoffice_available(monkeypatch):
    monkeypatch.setattr(bp, "find_soffice", lambda: "/usr/bin/soffice")
    assert bp.resolve_engine("libreoffice") == "libreoffice"


def test_resolve_engine_explicit_docx2pdf_unavailable(monkeypatch):
    monkeypatch.setattr(bp, "find_docx2pdf", lambda: False)
    assert bp.resolve_engine("docx2pdf") == "reportlab"


def test_resolve_engine_explicit_wps_unavailable(monkeypatch):
    monkeypatch.setattr(bp, "find_wps", lambda: None)
    assert bp.resolve_engine("wps") == "reportlab"


def test_resolve_engine_reportlab_passes_through():
    # reportlab 是兜底，显式指定时无需任何探测，直接通过
    assert bp.resolve_engine("reportlab") == "reportlab"
