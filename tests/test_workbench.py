from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from reconcile.audit import AuditStore
from reconcile.auth import AuthStore
from reconcile.storage import Store


def test_login_demo_review_and_navigation(tmp_path, monkeypatch):
    import reconcile.storage as storage
    import reconcile.auth as auth_mod
    import reconcile.audit as audit_mod
    import reconcile.ai as ai
    monkeypatch.setattr(storage, "Store", lambda path: Store(tmp_path / "ui.db"))
    monkeypatch.setattr(auth_mod, "build_auth", lambda path: AuthStore(tmp_path / "users.json"))
    monkeypatch.setattr(audit_mod, "build_audit", lambda path: AuditStore(tmp_path / "audit.db"))
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
    assert {"用户名", "角色", "创建时间", "最近操作时间", "最近操作"} <= set(table.columns)
    admin_row = table[table["用户名"] == "admin"].iloc[0]
    assert "+" not in str(admin_row["创建时间"])
    assert str(admin_row["最近操作时间"]) not in ("", "None")

    # 操作记录：登录、加载演示、提交复核都要能按账号追溯
    actions = [event["action"] for event in AuditStore(tmp_path / "audit.db").recent(50)]
    assert "登录" in actions
    assert "加载合成演示" in actions
    assert "提交复核结论" in actions
    assert all(event["actor"] == "admin" for event in AuditStore(tmp_path / "audit.db").recent(50))


def test_auth_combined_role(tmp_path):
    store = AuthStore(tmp_path / "users.json")
    store.register("combo", "pw1234", "录入复核")
    assert store.find("combo")["role"] == "录入复核"
    store.set_role("combo", "复核")
    assert store.find("combo")["role"] == "复核"
    with pytest.raises(ValueError):
        store.register("other", "pw1234", "管理员")


def test_stale_auth_module_roles_are_reloaded(tmp_path, monkeypatch):
    """模拟线上仍在运行的旧进程：认证模块缓存了旧角色清单时，注册页也要出现新角色。"""
    import reconcile.storage as storage
    import reconcile.auth as auth_mod
    import reconcile.audit as audit_mod
    import reconcile.ai as ai
    monkeypatch.setattr(storage, "Store", lambda path: Store(tmp_path / "ui.db"))
    monkeypatch.setattr(auth_mod, "build_auth", lambda path: AuthStore(tmp_path / "users.json"))
    monkeypatch.setattr(audit_mod, "build_audit", lambda path: AuditStore(tmp_path / "audit.db"))
    monkeypatch.setattr(ai.LocalAI, "health", lambda self: False)
    monkeypatch.setattr(auth_mod, "USER_ROLES", ("导入", "复核"))
    path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(path), default_timeout=20).run()
    assert not app.exception
    role_radio = next(radio for radio in app.radio if radio.label == "注册角色")
    assert "录入复核" in role_radio.options


def test_combined_role_can_import_review_and_see_entries(tmp_path, monkeypatch):
    import reconcile.storage as storage
    import reconcile.auth as auth_mod
    import reconcile.audit as audit_mod
    import reconcile.ai as ai
    monkeypatch.setattr(storage, "Store", lambda path: Store(tmp_path / "ui.db"))
    users = tmp_path / "users.json"
    AuthStore(users).register("combo", "combo123", "录入复核")
    monkeypatch.setattr(auth_mod, "build_auth", lambda path: AuthStore(users))
    monkeypatch.setattr(audit_mod, "build_audit", lambda path: AuditStore(tmp_path / "audit.db"))
    monkeypatch.setattr(ai.LocalAI, "health", lambda self: False)
    path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(path), default_timeout=20).run()
    assert not app.exception

    app.text_input[0].set_value("combo")
    app.text_input[1].set_value("combo123")
    next(b for b in app.button if b.label.startswith("登录")).click().run()
    assert not app.exception
    options = app.sidebar.radio[0].options
    # 录入 + 复核两侧页面都在，录入记录可查看他人录入；但没有用户与权限页
    assert {"导入与字段确认", "结果与人工复核", "录入记录", "AI 辅助与记录"} <= set(options)
    assert "用户与权限" not in options

    # 既能录入（加载演示、建任务），也能提交复核结论
    next(b for b in app.button if b.label == "加载合成演示并运行对账").click().run()
    assert not app.exception
    app.sidebar.radio[0].set_value("结果与人工复核").run()
    next(b for b in app.button if b.label == "保存复核结论").click().run()
    assert not app.exception
    assert any(r["actor"] == "combo" for r in app.session_state["task"].reviews)

    # 录入记录页汇总各账号的录入批次与明细
    app.sidebar.radio[0].set_value("录入记录").run()
    assert not app.exception
    batches = app.dataframe[0].value
    assert {"来源", "文件", "工作表", "记录数", "确认人", "确认时间"} <= set(batches.columns)
    assert int(batches["记录数"].sum()) == len(app.session_state["task"].records)
    detail = app.dataframe[1].value
    assert "录入人" in detail.columns
