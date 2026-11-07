from pathlib import Path

from streamlit.testing.v1 import AppTest

from reconcile.storage import Store


def test_overview_review_navigation_and_restart(tmp_path, monkeypatch):
    import reconcile.storage as storage
    import reconcile.ai as ai
    monkeypatch.setattr(storage, "Store", lambda path: Store(tmp_path / "ui.db"))
    monkeypatch.setattr(ai.LocalAI, "health", lambda self: False)
    path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(path), default_timeout=20).run()
    assert not app.exception
    app.button[0].click().run()
    assert not app.exception
    assert [m.value for m in app.metric][:3] == ["4", "13", "2"]
    app.sidebar.text_input[0].set_value("界面测试员").run()
    app.sidebar.radio[0].set_value("结果与人工复核").run()
    assert not app.exception
    assert app.selectbox[0].value
    next(b for b in app.button if b.label == "保存复核结论").click().run()
    assert not app.exception
    assert any(r["actor"] == "界面测试员" for r in app.session_state["task"].reviews)
    restored = AppTest.from_file(str(path), default_timeout=20).run()
    assert not restored.exception
    assert restored.session_state["task"].reviews
    for page in ("导入与字段确认", "本地 AI 与记录", "交付与说明"):
        restored.sidebar.radio[0].set_value(page).run()
        assert not restored.exception, page
