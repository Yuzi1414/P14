from pathlib import Path

from streamlit.testing.v1 import AppTest

from reconcile.auth import AuthStore
from reconcile.storage import Store


def test_login_demo_review_and_navigation(tmp_path, monkeypatch):
    import reconcile.storage as storage
    import reconcile.auth as auth_mod
    import reconcile.ai as ai
    monkeypatch.setattr(storage, "Store", lambda path: Store(tmp_path / "ui.db"))
    monkeypatch.setattr(auth_mod, "build_auth", lambda path: AuthStore(tmp_path / "users.json"))
    monkeypatch.setattr(ai.LocalAI, "health", lambda self: False)
    path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(path), default_timeout=20).run()
    assert not app.exception

    # 用内置管理员登录：角色改版后只有 admin 能同时看到导入与复核两侧的页面
    app.text_input[0].set_value("admin")
    app.text_input[1].set_value("admin123")
    next(b for b in app.button if b.label.startswith("登录")).click().run()
    assert not app.exception
    assert "用户与权限" in app.sidebar.radio[0].options

    next(b for b in app.button if b.label == "加载合成演示并运行对账").click().run()
    assert not app.exception
    # 总览页的指标卡是自定义 HTML（st.markdown），不是 st.metric，所以直接核对任务数据
    loaded = app.session_state["task"]
    assert loaded is not None and len(loaded.records) == 45
    counts = [sum(g.status == status for g in loaded.groups) for status in ("已匹配", "未匹配", "异常差异")]
    assert counts == [4, 13, 2]

    app.sidebar.radio[0].set_value("结果与人工复核").run()
    assert not app.exception
    assert app.selectbox[0].value
    next(b for b in app.button if b.label == "保存复核结论").click().run()
    assert not app.exception
    # 操作人取自登录账号，不再手填
    assert any(r["actor"] == "admin" for r in app.session_state["task"].reviews)

    for page in ("导入与字段确认", "AI 辅助与记录", "交付与说明"):
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception, page

    # 用户与权限：账号时间要按北京时间渲染，不能把 +08:00 偏移原样显示出来
    app.sidebar.radio[0].set_value("用户与权限").run()
    assert not app.exception
    table = app.dataframe[0].value
    assert {"用户名", "角色", "创建时间", "最近操作时间"} <= set(table.columns)
    admin_row = table[table["用户名"] == "admin"].iloc[0]
    assert "+" not in str(admin_row["创建时间"])
    assert str(admin_row["最近操作时间"]) not in ("", "None")
