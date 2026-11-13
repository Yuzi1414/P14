"""Local Streamlit workbench. Financial logic lives in reconcile/, not UI callbacks."""
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import shutil
from pathlib import Path

import pandas as pd
import streamlit as st

from reconcile.ai import AIError, AIWorker, LocalAI
from reconcile import ai as ai_runtime
from reconcile.auth import USER_ROLES, build_auth
from reconcile.demo import load_demo
from reconcile.engine import candidate_records
from reconcile.exporter import group_rows, money, record_rows, workbook_bytes
from reconcile.importer import fingerprint, normalize, read_sheet, sheet_names, suggest_mapping
from reconcile.models import FIELDS, SOURCES, Task
from reconcile.service import accept_candidate, create_task, record_review
from reconcile.storage import Store, build_store, review_status, timestamp

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="P14 · 账务核对工作台", page_icon="▦", layout="wide")
st.markdown("""<style>
/* ===== Design tokens ===== */
.stApp {background:#F4F6F3;}
.block-container {max-width:1400px; padding-top:1.6rem; padding-bottom:3rem;}
html, body, [class*="css"], [data-testid="stAppViewContainer"] {font-family:'Segoe UI','Microsoft YaHei',system-ui,-apple-system,sans-serif;}

/* ===== Typography ===== */
h1,h2,h3 {font-family:'Segoe UI','Microsoft YaHei',sans-serif; letter-spacing:-.02em; color:#16261F;}
h1 {font-size:2.35rem !important; font-weight:750 !important; letter-spacing:-.03em;}
h2 {font-size:1.5rem !important; font-weight:700 !important;}
h3 {font-size:1.15rem !important; font-weight:650 !important;}

/* ===== Sidebar (deep-green brand panel) ===== */
[data-testid='stSidebar'] {background:linear-gradient(180deg,#0C2A22 0%,#0E3328 100%); border-right:0;}
[data-testid='stSidebar'] > div {padding-top:1.2rem;}
[data-testid='stSidebar'] * {color:#DCEAE2;}
[data-testid='stSidebar'] .eyebrow {color:#6FB8A0;}
[data-testid='stSidebar'] h1 {color:#FFFFFF !important; font-size:1.6rem !important;}
[data-testid='stSidebar'] .stCaption, [data-testid='stSidebar'] p, [data-testid='stSidebar'] small {color:#9DBDB0;}
[data-testid='stSidebar'] .stRadio>div {gap:.2rem;}
[data-testid='stSidebar'] .stRadio label {display:block; padding:.55rem .8rem; border-radius:10px; margin:0; transition:background .15s,color .15s;}
[data-testid='stSidebar'] .stRadio label:hover {background:rgba(255,255,255,.07);}
[data-testid='stSidebar'] div[role="radiogroup"] label:has(input:checked) {background:#176B5B; color:#fff; font-weight:600; box-shadow:0 2px 8px rgba(0,0,0,.25);}
[data-testid='stSidebar'] [data-testid="stTextInput"] input {background:#ffffff; border:1px solid rgba(0,0,0,.18); color:#000000; border-radius:10px;}
[data-testid='stSidebar'] [data-testid="stTextInput"] input::placeholder {color:#6E8E80;}
[data-testid='stSidebar'] hr {border-color:rgba(255,255,255,.12);}
/* 账号设置：浅底卡片上用深色文字，避免白底浅字看不清 */
[data-testid='stSidebar'] [data-testid='stExpander'] {background:#ffffff;}
[data-testid='stSidebar'] [data-testid='stExpander'] * {color:#111111 !important;}
[data-testid='stSidebar'] [data-testid='stExpander'] [data-testid="stTextInput"] input {color:#000000 !important;}
[data-testid='stSidebar'] [data-testid='stExpander'] [data-testid="stTextInput"] input::placeholder {color:#6B6B6B !important;}
[data-testid='stSidebar'] [data-testid='stExpander'] .stButton>button,
[data-testid='stSidebar'] [data-testid='stExpander'] .stButton>button * {color:#ffffff !important;}
[data-testid='stSidebar'] [data-testid='stExpander'] .stCheckbox label p,
[data-testid='stSidebar'] [data-testid='stExpander'] .stCheckbox label {color:#111111 !important;}
.sidebar-brand {display:flex; align-items:center; gap:.75rem; padding:.25rem .2rem 1rem;}
.sidebar-logo {width:40px; height:40px; border-radius:11px; background:linear-gradient(135deg,#22A97F,#0F5B4C); display:flex; align-items:center; justify-content:center; color:#fff; font:700 18px 'Segoe UI'; box-shadow:0 4px 12px rgba(0,0,0,.3);}
.sidebar-brand-t {line-height:1.15;}
.sidebar-brand-t b {display:block; color:#fff; font-size:1.05rem; letter-spacing:.01em;}
.sidebar-brand-t span {color:#6FB8A0; font:600 10px Consolas,monospace; letter-spacing:.14em;}
.ai-dot {display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:6px; vertical-align:middle;}
.ai-dot.on {background:#3DD68C; box-shadow:0 0 0 3px rgba(61,214,140,.18);}
.ai-dot.off {background:#E05548; box-shadow:0 0 0 3px rgba(224,85,72,.18);}

/* ===== Main surface / components ===== */
[data-testid='stDataFrame'] {border:1px solid #E2E7E0; border-radius:14px; overflow:hidden; box-shadow:0 1px 2px rgba(22,38,31,.04),0 4px 14px rgba(22,38,31,.05);}
[data-testid='stDataFrame'] thead tr th {background:#F0F3EF !important; color:#3A4A41 !important; font-weight:600; font-size:.85rem;}
[data-testid='stMetric'] {background:#fff; border:1px solid #E2E7E0; border-radius:14px; padding:20px 22px; box-shadow:0 1px 2px rgba(22,38,31,.04),0 6px 16px rgba(22,38,31,.06);}
[data-testid='stMetricValue'] {font-family:'Segoe UI',Consolas,monospace; color:#176B5B; font-weight:750; font-size:1.9rem;}
[data-testid='stMetricLabel'] {color:#5B6B61; font-weight:600;}
.stButton>button {border-radius:11px; font-weight:600; padding:.5rem 1.1rem; transition:transform .1s,box-shadow .15s;}
.stButton>button:hover {transform:translateY(-1px); box-shadow:0 4px 12px rgba(23,107,91,.18);}
.stButton>button[kind="primary"] {background:#176B5B; border-color:#176B5B;}
[data-testid="stDownloadButton"]>button {border-radius:11px; font-weight:600;}
[data-testid="stExpander"] {border:1px solid #E2E7E0 !important; border-radius:14px !important; background:#fff; box-shadow:0 1px 2px rgba(22,38,31,.03);}
[data-testid="stForm"] {border:1px solid #E2E7E0; border-radius:14px; background:#fff; padding:.4rem 1rem 1rem; box-shadow:0 1px 2px rgba(22,38,31,.03);}
.stTabs [data-baseweb="tab-list"] {gap:.4rem;}
.stTabs [data-baseweb="tab"] {border-radius:9px;}
[data-testid="stAlert"], .stAlert {border-radius:12px;}

/* ===== Custom: eyebrow / hero / cards / notes ===== */
.eyebrow {font:600 12px Consolas,monospace; letter-spacing:.16em; color:#176B5B; margin-bottom:.6rem;}
.hero-note {color:#66736A; line-height:1.8; max-width:880px; margin-bottom:20px; font-size:.98rem;}
.hero {background:linear-gradient(135deg,#0C2A22 0%,#135545 60%,#176B5B 100%); border-radius:20px; padding:2.2rem 2.4rem; color:#fff; box-shadow:0 10px 30px rgba(12,42,34,.25); margin-bottom:1.6rem; position:relative; overflow:hidden;}
.hero::after {content:""; position:absolute; right:-80px; top:-80px; width:280px; height:280px; border-radius:50%; background:radial-gradient(circle,rgba(255,255,255,.10),transparent 65%);}
.hero-eyebrow {font:600 11px Consolas,monospace; letter-spacing:.2em; color:#7FD4B8; margin-bottom:.7rem;}
.hero h1 {color:#fff !important; font-size:2.5rem !important; margin:0 0 .5rem;}
.hero p {color:#C7DCD2; font-size:1.02rem; max-width:640px; line-height:1.7; margin:0;}
.hero-meta {display:flex; flex-wrap:wrap; gap:.5rem; margin-top:1.3rem;}
.hero-meta span {font-size:.82rem; color:#0C2A22; background:rgba(255,255,255,.92); padding:.32rem .75rem; border-radius:999px; font-weight:600;}
.step {padding:22px 24px; background:#fff; border:1px solid #E2E7E0; border-radius:14px; min-height:186px; box-shadow:0 1px 2px rgba(22,38,31,.04),0 4px 14px rgba(22,38,31,.04); margin:8px 0 22px; transition:transform .15s,box-shadow .15s;}
.step:hover {transform:translateY(-2px); box-shadow:0 6px 20px rgba(22,38,31,.08);}
.step .step-no {font:700 13px Consolas,monospace; color:#176B5B; letter-spacing:.08em;}
.step b {display:block; margin:10px 0 8px; font-size:18px; color:#16261F;}
.step p {font-size:13.5px; color:#66736A; line-height:1.6; margin:0;}
.mcard {background:#fff; border:1px solid #E2E7E0; border-radius:14px; padding:18px 20px; box-shadow:0 1px 2px rgba(22,38,31,.04),0 6px 16px rgba(22,38,31,.06); display:flex; align-items:center; gap:14px;}
.mcard .micon {width:42px; height:42px; border-radius:12px; display:flex; align-items:center; justify-content:center; font-size:20px; flex:0 0 auto;}
.mcard .mval {font-family:'Segoe UI',Consolas,monospace; font-size:1.9rem; font-weight:750; line-height:1; color:#16261F;}
.mcard .mlab {font-size:.82rem; color:#5B6B61; font-weight:600; margin-top:3px;}
.footer {border-top:1px solid #D5DBD1; padding-top:16px; margin-top:32px; color:#8A978F; font-size:12px;}
button {border-radius:11px !important;}
@media(max-width:768px){h1{font-size:1.9rem !important;} .hero{padding:1.6rem 1.4rem;} .hero h1{font-size:1.9rem !important;} .block-container{padding-top:1rem;}}
</style>""", unsafe_allow_html=True)


# ===================== 登录 / 注册 / 权限门禁 =====================
# 线上（Render 免费实例）磁盘是临时的，runtime/users.json 每次重启都会被清空，
# 表现为「注册的账号第二天就失效」。因此配置了 SUPABASE_URL / SUPABASE_KEY
# 时账号改存 Supabase；本地未配置环境变量时仍用 runtime/users.json，行为不变。
auth = build_auth(ROOT / "runtime" / "users.json")

# 刷新(F5)会新建 Streamlit 会话并清空 session_state，导致掉线。
# 这里用 URL 查询参数保存一个「用户名 + 签名」令牌，刷新后据此自动恢复登录；
# 签名绑定当前密码哈希，改密码/移除账号后旧令牌自动失效。
# 密钥优先取环境变量 SESSION_SECRET——否则每次重启重新生成，旧令牌全部失效。
_SECRET_FILE = ROOT / "runtime" / ".session_secret"


def _session_secret():
    env_value = (os.getenv("SESSION_SECRET") or "").strip()
    if env_value:
        return env_value
    try:
        if _SECRET_FILE.exists():
            value = _SECRET_FILE.read_text(encoding="utf-8").strip()
            if value:
                return value
    except OSError:
        pass
    value = secrets.token_hex(32)
    try:
        _SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SECRET_FILE.write_text(value, encoding="utf-8")
    except OSError:
        pass
    return value


_SECRET = _session_secret()
_TOKEN_KEY = "s"
_DEVICE_KEY = "d"


def _device_id():
    """本机（本浏览器入口）标识，用于把对账数据按设备隔离。

    首次打开时生成 8 位十六进制标识并写回地址栏（?d=），之后刷新、切页都沿用；
    换一台电脑或用不带 d 的地址打开会拿到新标识，看到的是空白工作台。
    """
    raw = st.query_params.get(_DEVICE_KEY)
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    raw = (raw or "").strip()
    if re.fullmatch(r"[0-9a-f]{8}", raw):
        return raw
    value = secrets.token_hex(4)
    st.query_params[_DEVICE_KEY] = value
    st.rerun()


def _sign_user(user):
    msg = (str(user.get("username", "")) + "|" + str(user.get("password_hash", ""))).encode("utf-8")
    return hmac.new(_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()[:32]


def _make_token(user):
    return user["username"] + "." + _sign_user(user)


def _verify_token(token):
    if not token or "." not in token:
        return None
    name, _, sig = token.partition(".")
    user = auth.find(name)
    if not user or user.get("status") != "active":
        return None
    if not hmac.compare_digest(sig, _sign_user(user)):
        return None
    return dict(user)


def _persist_login(user):
    st.session_state.user = user
    try:
        st.query_params[_TOKEN_KEY] = _make_token(user)
    except Exception:
        pass


def _clear_login():
    st.session_state.pop("user", None)
    try:
        # 只清登录令牌，保留本机标识，否则退出再登录会换一台“新设备”，看不到本机数据
        keep_device = st.query_params.get(_DEVICE_KEY)
        st.query_params.clear()
        if keep_device:
            st.query_params[_DEVICE_KEY] = keep_device
    except Exception:
        pass


# 会话内的任务相关状态：切换账号时必须清空，否则同一浏览器会话里新账号会残留上一账号的任务
_TASK_STATE_KEYS = ("task", "staged", "import_logs", "mapping_ai", "seen_jobs", "current_job", "active_job")


def _clear_task_state():
    for key in _TASK_STATE_KEYS:
        st.session_state.pop(key, None)


def _touch_active():
    """业务操作成功后刷新当前账号的「最近操作时间」；打点失败不阻断主流程。"""
    try:
        auth.touch(current_user["username"])
    except Exception:
        pass


def _all_task_keys(slug, tag):
    """列出该账号在云端的所有任务键（各设备一条），用于注销时清理。"""
    try:
        from reconcile.storage import _supabase_conf, TABLE, TIMEOUT
        import httpx
        url, key = _supabase_conf()
        if not url or not key:
            return []
        resp = httpx.get(
            url.rstrip("/") + f"/rest/v1/{TABLE}",
            params={"select": "task_key", "task_key": f"like.{slug}_{tag}_%"},
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=TIMEOUT,
        )
        if resp.status_code >= 400:
            return []
        return [row["task_key"] for row in resp.json()]
    except Exception:
        return []


LOGIN_CSS = """<style>
.st-key-loginbox{
    width:min(470px,92vw);
    margin:8vh auto 0 auto;
    padding:34px 32px 20px;
    background:#ffffff;
    border:1px solid #E2E7E0;
    border-radius:20px;
    box-shadow:0 22px 60px rgba(12,42,34,.13),0 2px 6px rgba(22,38,31,.05);
}
.login-head{display:flex;align-items:center;gap:14px;margin-bottom:16px;}
.login-logo{width:50px;height:50px;flex:0 0 auto;border-radius:15px;background:linear-gradient(135deg,#22A97F,#0F5B4C);display:flex;align-items:center;justify-content:center;color:#fff;font:700 22px 'Segoe UI','Microsoft YaHei',sans-serif;box-shadow:0 8px 18px rgba(15,91,76,.32);}
.login-title b{display:block;font-size:1.32rem;color:#16261F;letter-spacing:.01em;line-height:1.2;}
.login-title span{color:#7C8B82;font:600 10.5px Consolas,monospace;letter-spacing:.16em;}
.login-sub{color:#66736A;font-size:.92rem;line-height:1.7;margin:0 0 18px;}
.st-key-loginbox .stTabs [data-baseweb="tab-list"]{justify-content:center;gap:.4rem;border-bottom:1px solid #EDF1EC;}
.st-key-loginbox .stTabs [data-baseweb="tab"]{font-weight:600;}
.st-key-loginbox [data-testid="stForm"]{border:none;background:transparent;box-shadow:none;padding:.2rem 0 0;}
</style>"""


def render_auth_gate():
    st.markdown(LOGIN_CSS, unsafe_allow_html=True)
    with st.container(key="loginbox"):
        st.markdown(
            '<div class="login-head"><div class="login-logo">核</div>'
            '<div class="login-title"><b>账务核对工作台</b><span>P14 / FINANCE OPS</span></div></div>',
            unsafe_allow_html=True,
        )
        st.markdown('<p class="login-sub">银行流水 · 学生收费 · 财务往来 三方对账。账号分「导入」与「复核」两种角色：导入负责导入表格并建立对账，复核只查看结果并提交复核结论。注册即开通。</p>', unsafe_allow_html=True)
        tab_login, tab_register = st.tabs(["登录", "注册"])
        with tab_login:
            with st.form("login_form"):
                u = st.text_input("用户名")
                p = st.text_input("密码", type="password")
                submitted = st.form_submit_button("登录", type="primary", use_container_width=True)
            if submitted:
                try:
                    logged = auth.login(u, p)
                    _clear_task_state()
                    _persist_login(logged)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        with tab_register:
            with st.form("register_form"):
                u = st.text_input("注册用户名", key="reg_u")
                p = st.text_input("设置密码", type="password", key="reg_p")
                p2 = st.text_input("确认密码", type="password", key="reg_p2")
                reg_role = st.radio("注册角色", list(USER_ROLES), horizontal=True, key="reg_role",
                                    captions=["只能导入表格并建立对账，看不到复核按钮",
                                              "只能查看对账结果并提交复核结论，不能修改数据"])
                submitted = st.form_submit_button("注册并登录", type="primary", use_container_width=True, key="reg_submit")
            if submitted:
                if p != p2:
                    st.error("两次输入的密码不一致")
                elif not u.strip():
                    st.error("用户名不能为空")
                else:
                    try:
                        auth.register(u, p, reg_role)
                        logged = auth.login(u, p)
                        _clear_task_state()
                        _persist_login(logged)
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))


# 刷新后 session_state 被清空：尝试用 URL 里的令牌自动恢复登录态
if "user" not in st.session_state:
    restored = _verify_token(st.query_params.get(_TOKEN_KEY))
    if restored:
        st.session_state.user = restored

if "user" not in st.session_state:
    render_auth_gate()
    st.stop()
current_user = st.session_state["user"]

# 角色决定权限：admin 全部；导入 只能导入/建对账；复核 只能看结果并提交复核结论。
# 旧版注册的账号 role 仍是「用户」，视为未分配角色，必须由管理员指定后才能进入工作台。
ROLE_LABELS = {"admin": "管理员", "导入": "导入", "复核": "复核"}
_role = current_user.get("role")
if _role not in ROLE_LABELS:
    st.markdown(LOGIN_CSS, unsafe_allow_html=True)
    with st.container(key="loginbox"):
        st.markdown(
            '<div class="login-head"><div class="login-logo">核</div>'
            '<div class="login-title"><b>账号尚未分配角色</b><span>P14 / FINANCE OPS</span></div></div>',
            unsafe_allow_html=True,
        )
        st.warning(f"账号「{current_user['username']}」还没有分配「导入」或「复核」角色，暂时无法进入工作台。"
                   "请联系管理员在「用户与权限」里指定角色后重新登录。")
        if st.button("退出登录", use_container_width=True):
            _clear_login()
            _clear_task_state()
            st.rerun()
    st.stop()

can_import = _role in ("admin", "导入")     # 导入表格、建立/替换对账任务
can_review = _role in ("admin", "复核")     # 查看结果、提交复核结论
can_manage = _role == "admin"               # 用户与角色管理


def _pages():
    base = ["对账总览"]
    if can_import:
        base.append("导入与字段确认")
    if can_review:
        base += ["结果与人工复核", "AI 辅助与记录"]
    base.append("交付与说明")
    if can_manage:
        base.append("用户与权限")
    return base


@st.cache_resource
def worker():
    return AIWorker()


@st.cache_data(ttl=10)
def ai_info():
    return ai_runtime.status()


# 角色拆成「导入 / 复核」后，两方必须看到同一份对账数据：导入建立任务，复核在其中提交结论。
# 因此任务库改为共享工作区（不再按账号+设备各存一份），账号只决定能进入哪些页面。
_uname = current_user["username"]
_slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", _uname).strip("_") or "user"
_tag = hashlib.sha256(_uname.encode("utf-8")).hexdigest()[:8]
_device = _device_id()
_task_key = "workspace"
task_db_path = ROOT / "runtime" / "tasks" / "workspace.db"
store = build_store(task_db_path, _task_key)
# 兼容改造前的按账号/设备分库：共享工作区里还没有任务时，把当前账号原有任务复制进来，避免数据凭空消失。
# 这里判断的是「有没有任务」而不是「文件在不在」——空库文件在首次访问时就会被创建出来。
if getattr(store, "backend", "local") == "local":
    try:
        _ws_empty = store.load() is None
    except (ValueError, OSError):
        _ws_empty = False
    if _ws_empty:
        _old_dir = ROOT / "runtime" / "tasks" / f"{_slug}_{_tag}"
        _candidates = sorted(_old_dir.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True) if _old_dir.exists() else []
        _flat = ROOT / "runtime" / "tasks" / f"{_slug}_{_tag}.db"
        if _flat.exists():
            _candidates.append(_flat)
        for _old_db in _candidates:
            try:
                if Store(_old_db).load() is None:
                    continue
                shutil.copy2(_old_db, task_db_path)
                break
            except (ValueError, OSError):
                continue

# 共享空间：显式发布才写入，只有本账号的其它设备可以载入；默认不参与同步
shared_store = build_store(ROOT / "runtime" / "shared" / f"{_slug}_{_tag}.db", f"{_slug}_{_tag}_shared")
if "task" not in st.session_state:
    try:
        st.session_state.task = store.load()
        if st.session_state.task:
            interrupted = False
            for log in st.session_state.task.ai_logs:
                if log.get("status") == "running" and log["id"] not in worker().jobs:
                    log.update(status="interrupted", error="工作台进程已重启，原请求未完成；未自动重试")
                    interrupted = True
            if interrupted:
                store.save(st.session_state.task)
    except (ValueError, OSError) as exc:
        st.error(f"当前任务无法恢复：{exc}")
        st.stop()
for key, default in {"staged": {}, "import_logs": [], "mapping_ai": {}, "seen_jobs": set()}.items():
    if key not in st.session_state:
        st.session_state[key] = default
task = st.session_state.task
record_index = {r.id: r for r in task.records} if task else {}


def persist():
    if st.session_state.task:
        store.save(st.session_state.task)


def render_suggestion(result):
    if "mappings" in result:
        st.dataframe([{"标准字段": FIELDS.get(item["field"], item["field"]), "建议原始列": item["column"],
                       "建议依据": item["reason"]} for item in result["mappings"]], hide_index=True, width="stretch")
    else:
        st.write(result.get("reason", "未提供解释"))
        st.caption("建议候选：" + (result.get("candidate_id") or "证据不足，未选择"))
        fact_labels = {"business_id": "业务编号", "object_id": "对象标识", "name": "名称", "date": "日期", "amount": "金额", "direction": "收支方向"}
        if result.get("verified_facts"):
            st.dataframe([{"程序核对字段": fact_labels.get(key.removesuffix("_exact"), key),
                           "是否完全一致": "缺少字段" if value is None else "是" if value else "否"}
                          for key, value in result["verified_facts"].items()], hide_index=True, width="stretch")
    for note in result.get("cleaning_notes", []):
        st.caption("待人工确认的建议：" + note)


STATUS_STYLE = {"已匹配": "#E6F4EC", "异常差异": "#FBE9E7", "未匹配": "#FFF4E0"}


def style_status(df):
    """按『自动分类』列给结果组表格整行着色（仅样式，不改数据）。"""
    def row_style(row):
        color = STATUS_STYLE.get(row.get("自动分类", ""), "")
        return ["background-color:%s" % color if color else "" for _ in range(len(row))]
    return df.style.apply(row_style, axis=1)


def metric_card(icon, label, value, bg, fg):
    return (f'<div class="mcard"><div class="micon" style="background:{bg};color:{fg}">{icon}</div>'
            f'<div><div class="mval">{value}</div><div class="mlab">{label}</div></div></div>')


def eyebrow_html(cloud):
    return "RECONCILIATION WORKBENCH / " + ("CLOUD DEPLOYMENT" if cloud else "LOCAL PROTOTYPE")


def hero_html(cloud, ai):
    chips = ("云端部署" if cloud else "本地运行", "规则 demo-1.0",
             f"AI 辅助：{ai['provider_label']}", "数据存 Supabase" if cloud else "数据仅存本机")
    meta = "".join(f"<span>{chip}</span>" for chip in chips)
    return (f'<div class="hero"><div class="hero-eyebrow">{eyebrow_html(cloud)}</div>'
            '<h1>三方账务核对平台</h1>'
            '<p>把重复核对交给规则，把判断依据留给财务人员。银行流水 · 学生收费 · 财务往来 三源对账，所有自动结果均须人工复核。</p>'
            f'<div class="hero-meta">{meta}</div></div>')


def group_label(group):
    label = "缺少业务编号" if group.label in group.record_ids else group.label
    sources = " / ".join(SOURCES[source] for source in SOURCES if any(record_index[rid].source == source for rid in group.record_ids))
    return f"{label} · {sources}"


def submit_ai(kind, payload, context):
    try:
        jid = worker().submit(kind, payload, task.id if task and kind == "candidate" else "import")
        st.session_state.current_job = jid
        st.session_state.job_context = context
        log = worker().jobs[jid].log()
        log["context"] = context
        if task and kind == "candidate":
            task.ai_logs.append(log)
            persist()
        else:
            st.session_state.import_logs.append(log)
        st.rerun()
    except AIError as exc:
        st.error(str(exc))


@st.fragment(run_every="1s")
def ai_progress():
    jid = st.session_state.get("current_job")
    if not jid:
        return
    job = worker().jobs.get(jid)
    if not job:
        st.warning("AI进程已重启，请重新提交建议请求。")
        return
    with st.container(border=True):
        if job.status == "running":
            st.info(f"{_ai['provider_label']}正在生成建议。规则结果保持不变。")
            if st.button("取消 AI 请求", key="cancel_ai"):
                worker().cancel(jid)
            return
        if jid not in st.session_state.seen_jobs:
            log = job.log()
            context = st.session_state.get("job_context", {})
            log["context"] = context
            if context.get("import_key") and job.status == "success":
                st.session_state.mapping_ai[context["import_key"]] = job.result
            current = st.session_state.task
            if current and current.id == job.task_id:
                existing = next((item for item in current.ai_logs if item["id"] == jid), None)
                if existing:
                    existing.update(log)
                else:
                    current.ai_logs.append(log)
                persist()
            else:
                existing = next((item for item in st.session_state.import_logs if item["id"] == jid), None)
                if existing:
                    existing.update(log)
                else:
                    st.session_state.import_logs.append(log)
            st.session_state.seen_jobs.add(jid)
        if job.status == "success":
            st.success(f"AI 建议已生成 · {job.elapsed:.1f} 秒 · 请核查依据后决定是否采纳")
            render_suggestion(job.result)
        else:
            st.warning(job.error)
        if st.button("更新页面并查看建议", key="refresh_ai"):
            st.session_state.pop("current_job", None)
            st.rerun()


with st.sidebar:
    _ai = ai_info()
    ai_ok = _ai["ok"]
    st.markdown(f"""<div class="sidebar-brand">
      <div class="sidebar-logo">核</div>
      <div class="sidebar-brand-t"><b>账务核对工作台</b><span>P14 / FINANCE OPS</span></div>
    </div>""", unsafe_allow_html=True)
    page = st.radio("工作区", _pages(), label_visibility="collapsed")
    st.markdown("**当前用户**")
    role_label = ROLE_LABELS.get(_role, "未分配")
    role_hint = {"admin": "全部权限", "导入": "仅导入与建立对账", "复核": "仅查看结果并提交复核"}.get(_role, "")
    st.caption(f"{current_user['username']} · {role_label}（{role_hint}）")
    if st.button("退出登录"):
        _clear_login()
        _clear_task_state()
        st.rerun()
    if current_user["role"] != "admin":
        with st.expander("账号设置"):
            st.caption("注销后，该账号及其任务数据将被**永久删除**，无法恢复。")
            del_pw = st.text_input("输入当前密码以确认注销", type="password", key="del_pw")
            del_sure = st.checkbox("我确认永久注销此账号", key="del_sure")
            if st.button("注销账户", type="primary", key="del_btn", disabled=not del_sure, use_container_width=True):
                try:
                    auth.delete_account(current_user["username"], del_pw)
                    try:
                        # 对账数据属于共享工作区（导入与复核共用），注销个人账号时不清空；
                        # 只清理改造前遗留在云端、属于本账号的旧分库副本。
                        if getattr(store, "backend", "local") == "supabase":
                            for _dev_key in _all_task_keys(_slug, _tag):
                                build_store(task_db_path, _dev_key).clear()
                    except (OSError, ValueError):
                        pass
                    _clear_login()
                    _clear_task_state()
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
    st.divider()
    st.markdown("**运行边界**")
    st.caption("演示规则 demo-1.0 · 未经财务确认")
    st.caption(f"共享对账工作区 · 设备标识 {_device}\n\n导入与复核账号共用同一份对账数据")
    _auth_backend = "Supabase 云端" if getattr(auth, "backend", "local") == "supabase" else "本地文件"
    _task_backend = "Supabase 云端" if getattr(store, "backend", "local") == "supabase" else "本机文件"
    st.caption(f"账户存储：{_auth_backend}\n\n任务存储：{_task_backend}")
    st.markdown(f"{_ai['provider_label']}：<span class='ai-dot {'on' if ai_ok else 'off'}'></span>{_ai['model']} {'可用' if ai_ok else '未就绪'}", unsafe_allow_html=True)
    if not ai_ok:
        st.caption(_ai["hint"])
    if task:
        st.caption(f"当前任务：{task.name}\n\n{len(task.records)} 条原始记录 / {len(task.groups)} 个结果组")

actor = current_user["username"]
# 只要账户或任务任一走了 Supabase，就说明这是线上部署，文案不该再写"仅存本机"
_cloud = (getattr(store, "backend", "local") == "supabase"
          or getattr(auth, "backend", "local") == "supabase")

if page == "对账总览":
    st.markdown(hero_html(_cloud, _ai), unsafe_allow_html=True)
else:
    st.markdown(f'<div class="eyebrow">{eyebrow_html(_cloud)}</div>', unsafe_allow_html=True)
    st.title(page)
    st.markdown('<div class="hero-note">把重复核对交给规则，把判断依据留给财务人员。所有自动结果均须人工复核，原型不用于正式财务结算。</div>', unsafe_allow_html=True)


def demo_controls():
    allowed = True
    if task:
        allowed = st.checkbox("我确认用合成演示替换当前任务（当前复核记录将被替换）", key="demo_replace")
    if st.button("加载合成演示并运行对账", type="primary", disabled=not allowed or not can_import or worker().busy):
        st.session_state.task = load_demo()
        persist()
        st.rerun()


if page == "对账总览":
    cols = st.columns(3)
    for col, num, title, description in zip(cols, ["01", "02", "03"],
        ["导入并确认字段", "规则核对与 AI 建议", "人工复核与导出"],
        ["多份 Excel 统一映射，保留原始行号。", "两组关系独立核对，所有差异可追溯。", "自动分类与人工结论分别记录。"]):
        col.markdown(f'<div class="step"><div class="step-no">{num}</div><b>{title}</b><p>{description}</p></div>', unsafe_allow_html=True)
    if task:
        counts = {status: sum(g.status == status for g in task.groups) for status in ("已匹配", "未匹配", "异常差异")}
        pending = sum(review_status(task, g.id) == "待复核" for g in task.groups)
        metrics = st.columns(4)
        cards = [
            ("✓", "已匹配 · 组", counts["已匹配"], ("#E6F4EC", "#2E7D5B")),
            ("⚠", "异常差异 · 组", counts["异常差异"], ("#FBE9E7", "#B5453C")),
            ("!", "未匹配 · 组", counts["未匹配"], ("#FFF4E0", "#B7791F")),
            ("◷", "待复核 · 组", pending, ("#EAF1F7", "#3A6B96")),
        ]
        for col, (icon, label, value, (bg, fg)) in zip(metrics, cards):
            col.markdown(metric_card(icon, label, value, bg, fg), unsafe_allow_html=True)
        st.caption(f"原始记录 {len(task.records)} 条；两组关系允许引用同一银行记录，每组关系内均检查无重复分配。")
        st.subheader("当前结果概览")
        st.dataframe(style_status(pd.DataFrame(group_rows(task)).drop(columns=["成员标识"])), hide_index=True, width="stretch")
        st.download_button("导出完整核对工作簿", workbook_bytes(task), "P14-对账结果.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        st.info("尚未建立任务。导入账号可加载独立合成样例体验完整流程，也可以进入“导入与字段确认”导入授权数据。")
        if not can_import:
            st.caption("当前是复核账号：只能查看结果并提交复核结论，不能导入或替换对账数据。")
    if can_import:
        with st.expander("合成演示数据", expanded=not bool(task)):
            st.caption("样例覆盖金额差异、缺少来源、批次汇总、重复编号、退款、跨日与模糊候选。全部为虚构数据。")
            demo_controls()

elif page == "导入与字段确认":
    st.info("在本机选择授权的脱敏/模拟文件。先确认每份文件的工作表、表头和字段，再建立新任务。")
    for source, label in SOURCES.items():
        with st.expander(label, expanded=True):
            uploads = st.file_uploader(f"选择{label}文件", type=["xlsx", "xls"], accept_multiple_files=True, key="upload_" + source)
            seen_files = set()
            for upload in uploads:
                content = upload.getvalue()
                digest = fingerprint(content)
                if digest in seen_files:
                    st.warning(f"重复文件未再次导入：{upload.name}")
                    continue
                seen_files.add(digest)
                key = f"{source}_{digest}"
                st.markdown(f"**{html.escape(upload.name)}**")
                try:
                    names = sheet_names(content, upload.name)
                    selected_sheets = st.multiselect("导入工作表", names, default=names[:1], key=key + "_sheets")
                    for selected_sheet in selected_sheets:
                        ikey = key + "_" + selected_sheet
                        st.caption("工作表：" + selected_sheet)
                        header = int(st.number_input("表头所在行", min_value=1, max_value=100, value=1, key=ikey + "_header"))
                        frame = read_sheet(content, upload.name, selected_sheet, header)
                        st.dataframe(frame.head(8).astype(str), hide_index=True, width="stretch")
                        defaults = suggest_mapping(frame.columns)
                        if st.button("请 AI 建议字段与清洗方式", key=ikey + "_ai",
                                     disabled=not ai_ok, help=None if ai_ok else _ai["hint"]):
                            submit_ai("mapping", {"standard_fields": FIELDS, "columns": list(frame.columns),
                                                  "sample_rows": frame.head(3).astype(str).to_dict("records")}, {"import_key": ikey})
                        suggestion = st.session_state.mapping_ai.get(ikey)
                        if suggestion:
                            with st.expander("查看字段与清洗建议"):
                                render_suggestion(suggestion)
                            if st.button("将 AI 建议填入映射（仍需确认）", key=ikey + "_apply_ai"):
                                for item in suggestion["mappings"]:
                                    if item["column"] in frame.columns:
                                        st.session_state[ikey + "_map_" + item["field"]] = item["column"]
                        columns = [""] + list(frame.columns)
                        mapping = {}
                        left, right = st.columns(2)
                        for idx, (field, field_label) in enumerate(FIELDS.items()):
                            with (left if idx % 2 == 0 else right):
                                widget_key = ikey + "_map_" + field
                                if widget_key in st.session_state and st.session_state[widget_key] not in columns:
                                    st.session_state[widget_key] = ""
                                mapping[field] = st.selectbox(field_label, columns,
                                    index=columns.index(defaults[field]) if defaults[field] in columns else 0,
                                    format_func=lambda value: value or "未映射", key=widget_key)
                        if st.button("确认映射并加入待对账数据", key=ikey + "_confirm"):
                            if not actor.strip():
                                st.error("请在左侧填写操作人")
                            else:
                                records = normalize(frame, source, upload.name, selected_sheet, header, mapping, digest)
                                st.session_state.staged[ikey] = {"records": records, "meta": {
                                    "来源": source, "文件": upload.name, "文件哈希": digest,
                                    "工作表": selected_sheet, "表头行": header, "映射": mapping,
                                    "确认人": actor, "确认时间": timestamp(), "AI建议": bool(suggestion)}}
                                st.success(f"已确认 {len(records)} 行；同文件同工作表再次确认会替换暂存，不重复添加。")
                                _touch_active()
                except (ValueError, OSError, KeyError) as exc:
                    st.error(f"文件未加入：{exc}")
                except Exception as exc:
                    st.error(f"Excel解析失败（{type(exc).__name__}），请检查文件格式、工作表和表头。")
    staged = st.session_state.staged
    st.subheader("已确认的导入清单")
    if staged:
        st.dataframe([{**{k: v for k, v in item["meta"].items() if k not in ("映射", "文件哈希")},
                       "记录数": len(item["records"])} for item in staged.values()], hide_index=True, width="stretch")
        remove = st.multiselect("移除暂存工作表", list(staged), format_func=lambda k: staged[k]["meta"]["文件"] + " / " + staged[k]["meta"]["工作表"])
        if st.button("移除选中的暂存项", disabled=not remove):
            for k in remove:
                staged.pop(k)
            st.rerun()
    name = st.text_input("新任务名称", value="本地核对任务")
    confirmed = st.checkbox("我已检查字段映射、默认币种与方向；确认建立新任务并替换当前任务。")
    if st.button("开始规则对账", type="primary", disabled=not (staged and confirmed) or worker().busy):
        try:
            entries = list(staged.values())
            st.session_state.task = create_task([r for item in entries for r in item["records"]], name,
                                                [item["meta"] for item in entries])
            st.session_state.task.ai_logs = list(st.session_state.import_logs)
            persist()
            st.session_state.staged = {}
            st.session_state.import_logs = []
            st.success("对账完成，已保存。复核账号登录后可在「结果与人工复核」查看结果并提交复核结论。")
            _touch_active()
        except ValueError as exc:
            st.error(str(exc))

elif page == "结果与人工复核":
    if not task:
        st.info("请先导入数据或加载合成演示。")
    else:
        a, b = st.columns(2)
        status = a.multiselect("自动分类", ["已匹配", "未匹配", "异常差异"], default=["已匹配", "未匹配", "异常差异"])
        human = b.multiselect("人工复核状态", ["待复核", "已确认", "已驳回"], default=["待复核", "已确认", "已驳回"])
        shown = [g for g in task.groups if g.status in status and review_status(task, g.id) in human]
        st.caption(f"显示 {len(shown)} 个结果组 / 总计 {len(task.groups)} 个结果组")
        st.dataframe(style_status(pd.DataFrame([r for r in group_rows(task) if r["结果组"] in {g.id for g in shown}])), hide_index=True, width="stretch")
        if shown:
            group_map = {g.id: g for g in shown}
            gid = st.selectbox("选择结果组查看依据", list(group_map), format_func=lambda k: group_label(group_map[k]) + " · " + group_map[k].status)
            group = group_map[gid]
            st.subheader(group_label(group))
            st.write("自动分类：**" + group.status + "**　人工复核：**" + review_status(task, gid) + "**")
            st.write("；".join(group.reasons))
            st.dataframe([r for r in record_rows(task) if r["记录标识"] in group.record_ids], hide_index=True, width="stretch")
            with st.expander("原始数据与两组核对关系"):
                for p in task.pairs:
                    if p.id in group.pair_ids:
                        st.write(f"**{p.relation}** · {p.status} · 差额 {money(p.delta_cents) or '未知'} 元")
                        st.caption("；".join(p.reasons))
                st.json([{ "记录标识": r.id, "原始内容": r.raw} for r in task.records if r.id in group.record_ids])
            with st.form("review_" + task.id + "_" + gid):
                st.markdown("**人工复核与详细备注**")
                action = st.radio("复核结论", ["确认", "驳回"], horizontal=True)
                note = st.text_area("详细备注 / 判断依据（支持多行；驳回须填写原因）", height=150,
                                    placeholder="例如：该组银行与收费金额精确一致、同日同币种，依据业务编号关联确认……")
                st.caption("确认表示已核查该分类；不会将异常差额清零，也不代表正式财务批准。填写的详细备注会写入导出的结果组「人工详细备注」列。")
                if st.form_submit_button("保存复核结论", type="primary"):
                    try:
                        record_review(task, gid, action, actor, note)
                        persist()
                        _touch_active()
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
            if not can_import:
                st.caption("复核账号只读：候选补配、建立关联属于修改对账数据，只能由导入账号处理；此处仅可提交复核结论。")
            orphan_pairs = [p for p in task.pairs if p.id in group.pair_ids and len(p.left_ids) == 1 and not p.right_ids] if can_import else []
            if orphan_pairs:
                st.subheader("人工候选关联")
                pmap = {p.id: p for p in orphan_pairs}
                pid = st.selectbox("选择需要补充的核对关系", list(pmap), format_func=lambda k: pmap[k].relation)
                pair = pmap[pid]
                bank_id = pair.left_ids[0]
                candidates = candidate_records(task, bank_id, pair.relation)
                record_map = {r.id: r for r in task.records}
                if candidates:
                    st.dataframe([{"记录标识": r.id, "启发式排序分": score, "业务编号": r.business_id,
                                   "对象": r.name, "对象标识": r.object_id, "金额(元)": money(r.amount_cents),
                                   "日期": r.date} for score, r in candidates], hide_index=True, width="stretch")
                    st.caption("排序分用于缩小范围，不是匹配概率；金额相同不会自动建立关联。")
                    st.caption("模型说明可能有误。程序核对结果单独列出字段是否一致；缺少字段不表示一致。")
                    minimal = lambda r: {"id": r.id, "business_id": r.business_id, "object_id": r.object_id,
                                         "name": r.name, "date": r.date, "amount": money(r.amount_cents), "direction": r.direction}
                    if st.button("请 AI 解释候选", key="candidate_ai_" + pid,
                                 disabled=not ai_ok, help=None if ai_ok else _ai["hint"]):
                        submit_ai("candidate", {"bank": minimal(record_map[bank_id]),
                                  "candidates": [minimal(r) for _, r in candidates]},
                                  {"bank_id": bank_id, "relation": pair.relation})
                    candidate_id = st.selectbox("人工选择候选记录", [r.id for _, r in candidates],
                        format_func=lambda rid: record_map[rid].business_id + " · " + record_map[rid].name + " · " + rid)
                    latest = next((log for log in reversed(task.ai_logs) if log.get("context", {}).get("bank_id") == bank_id
                                   and log.get("context", {}).get("relation") == pair.relation and log["status"] == "success"), None)
                    if latest:
                        render_suggestion(latest["suggestion"])
                    evidence = st.text_input("建立关联的人工依据", key="evidence_" + pid)
                    if st.button("确认建立关联并重算", key="accept_" + pid):
                        try:
                            accept_candidate(task, bank_id, candidate_id, pair.relation, actor, evidence)
                            if latest:
                                latest["adoption"] = "已采纳候选" if latest["suggestion"]["candidate_id"] == candidate_id else "人工选择其他候选"
                            persist()
                            _touch_active()
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))
                else:
                    st.info("当前没有未分配候选，保留未匹配结果。")
        st.download_button("导出含复核记录的完整工作簿", workbook_bytes(task), "P14-对账结果.xlsx")

elif page == "AI 辅助与记录":
    st.subheader("AI 服务状态")
    _page_ai = ai_info()
    if _page_ai["ok"]:
        st.success(_page_ai["hint"])
    else:
        st.warning(_page_ai["hint"])
    st.caption(f"后端：{_page_ai['provider_label']} · 模型：{_page_ai['model']} · 接口：{_page_ai['endpoint']}")
    if st.button("重新检测模型"):
        ai_info.clear()
        st.rerun()
    st.caption("AI只提出字段、清洗和候选建议。映射和关联必须由人接受，规则引擎负责金额与分类。")
    if task and task.ai_logs:
        st.dataframe([{k: v for k, v in log.items() if k not in ("suggestion", "context")} for log in task.ai_logs], hide_index=True, width="stretch")
        log_map = {log["id"]: log for log in task.ai_logs}
        lid = st.selectbox("查看 AI 记录", list(log_map))
        st.json(log_map[lid])
        decision = st.selectbox("人工判断", ["待人工判断", "已采纳字段建议", "部分采纳", "未采纳"])
        rationale = st.text_input("判断说明")
        if st.button("保存 AI 使用判断"):
            if not actor.strip():
                st.error("请填写操作人")
            else:
                log_map[lid]["adoption"] = decision
                task.reviews.append({"id": lid + "_" + timestamp(), "group_id": "", "action": "AI建议判断", "actor": actor,
                                     "note": rationale, "ai_log_id": lid, "decision": decision, "at": timestamp()})
                persist()
                _touch_active()
                st.success("已记录人工判断")
    else:
        st.info("还没有当前任务的 AI 使用记录。可在字段映射或候选关联处发起 AI 建议请求。")
    if task:
        with st.expander("人工复核操作记录"):
            st.json(task.reviews)

else:
    st.subheader("数据存放与共享")
    st.caption(f"导入与复核共用一个对账工作区（当前设备标识 {_device}）：导入账号建立的任务，复核账号登录后直接看到同一份结果与复核记录。")
    if not task:
        st.caption("当前没有任务；请由导入账号导入对账数据并运行规则对账。")
    if not can_import:
        st.info("复核账号只读：不能发布、载入或导入对账数据，以免覆盖导入账号建立的结果。下方可正常导出查看。")
    if can_import:
        c_share, c_load = st.columns(2)
        if c_share.button("发布到云端共享", use_container_width=True, disabled=task is None,
                          help="把当前任务复制到本账号的共享空间，供其它设备载入"):
            shared_store.save(task)
            st.success(f"已发布到共享空间（{timestamp()}）。其它设备可用「从云端共享载入」获取。")
        if c_load.button("从云端共享载入", use_container_width=True,
                         help="用共享空间的最新任务覆盖当前工作区的任务"):
            try:
                shared_task = shared_store.load()
            except (ValueError, OSError) as exc:
                shared_task = None
                st.error(f"共享空间无法读取：{exc}")
            if shared_task is None:
                st.info("共享空间还是空的：先在任意设备上点「发布到云端共享」。")
            else:
                store.save(shared_task)
                st.session_state.task = shared_task
                for key in ("staged", "import_logs", "mapping_ai", "seen_jobs", "current_job", "active_job"):
                    st.session_state.pop(key, None)
                st.success(f"已载入共享任务：{shared_task.name}")
                st.rerun()

    st.markdown("**手动迁移：对账包**")
    st.caption("导出的文件保存在你自己的电脑上；换电脑时用导入恢复，这条通道不经过服务器自动同步。")
    if task:
        st.download_button("导出对账包（保存到本机）",
                           json.dumps(task.to_dict(), ensure_ascii=False).encode("utf-8"),
                           file_name=f"P14-对账包-{task.name}.json", mime="application/json")
    if can_import:
        with st.form("bundle_import", clear_on_submit=True):
            up = st.file_uploader("导入对账包（.json）", type=["json"])
            if st.form_submit_button("导入到本机"):
                if up is None:
                    st.error("请先选择一个对账包文件")
                else:
                    try:
                        imported = Task.from_dict(json.loads(up.getvalue().decode("utf-8")))
                    except Exception as exc:
                        st.error(f"对账包无法解析：{exc}")
                    else:
                        store.save(imported)
                        st.session_state.task = imported
                        for key in ("staged", "import_logs", "mapping_ai", "seen_jobs", "current_job", "active_job"):
                            st.session_state.pop(key, None)
                        st.success(f"已导入：{imported.name}")
                        st.rerun()
    st.divider()

    st.subheader("交付材料")
    for title, filename in [("需求与验收边界", "PRD.md"), ("业务规则与异常分类", "BUSINESS_RULES.md"),
                            ("用户操作说明", "USER_GUIDE.md"), ("待财务确认清单", "BUSINESS_CONFIRMATION.md"),
                            ("演示与汇报材料", "DEMO.md"), ("测试与验证记录", "TEST_REPORT.md")]:
        path = ROOT / "docs" / filename
        if path.exists():
            with st.expander(title):
                st.markdown(path.read_text(encoding="utf-8"))
    st.warning("合成样例通过不等于财务业务验收通过。受限样例、导出文件和任务数据库应按项目清单管理，并在项目结束时清理。")

if page == "用户与权限":
    st.subheader("用户与权限管理")
    st.caption("「导入」账号只能导入表格并建立对账；「复核」账号只查看结果并提交复核结论，不能修改数据；"
               "管理员拥有全部权限。旧账号角色显示「未分配」时，需在这里指定后才能进入工作台。")
    users = auth.users()
    st.dataframe([{"用户名": u.get("username", ""), "角色": ROLE_LABELS.get(u.get("role"), "未分配"),
                   "状态": u.get("status", ""), "创建时间": u.get("created_at", ""),
                   "最近操作时间": u.get("last_active_at") or "—"} for u in users],
                 hide_index=True, width="stretch")
    active = [u for u in users if u["status"] == "active"]
    if active:
        st.markdown("**在职账号与角色**")
        for u in active:
            c1, c2, c3, c4 = st.columns([3, 2, 1, 1])
            c1.write(u["username"] + ("（管理员）" if u["username"] == "admin" else ""))
            if u["username"] == "admin":
                c2.caption("管理员 · 全部权限")
                c3.caption("—")
                c4.caption("—")
                continue
            current_role = u.get("role")
            picked = c2.selectbox("角色", list(USER_ROLES),
                                  index=list(USER_ROLES).index(current_role) if current_role in USER_ROLES else None,
                                  placeholder="未分配（请选择）", key="role_" + u["username"],
                                  label_visibility="collapsed")
            if c3.button("保存", key="save_role_" + u["username"], disabled=picked is None or picked == current_role):
                try:
                    auth.set_role(u["username"], picked)
                    st.success(f"已把 {u['username']} 设为「{picked}」。该账号需重新登录后生效。")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
            if c4.button("移除", key="arm_" + u["username"]):
                try:
                    auth.reject(u["username"])
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
            if current_role not in USER_ROLES:
                c1.caption("当前未分配角色：登录后会被拦在角色分配页，无法进入工作台。")
    st.markdown("**修改密码**")
    with st.form("chpwd_form"):
        old_p = st.text_input("原密码", type="password")
        new_p = st.text_input("新密码", type="password")
        new_p2 = st.text_input("确认新密码", type="password")
        if st.form_submit_button("修改密码", type="primary"):
            if new_p != new_p2:
                st.error("两次新密码不一致")
            else:
                try:
                    auth.change_password(current_user["username"], old_p, new_p)
                    st.success("密码已修改")
                except ValueError as exc:
                    st.error(str(exc))

ai_progress()
st.markdown('<div class="footer">P14 / 账务核对平台　·　本地演示原型　·　规则 demo-1.0　·　所有结果须人工复核</div>', unsafe_allow_html=True)
