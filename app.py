import streamlit as st
import random
import time
import re
import smtplib
import json
import importlib
import threading
from datetime import datetime
from pathlib import Path
import streamlit.components.v1 as components
from email.message import EmailMessage
from streamlit.errors import StreamlitSecretNotFoundError
from filelock import FileLock

try:
    from streamlit_autorefresh import st_autorefresh
except ModuleNotFoundError:
    def st_autorefresh(interval=0, key=None):
        return 1

st.set_page_config(page_title="Spinner Wheel", page_icon="🎰")

st.title("🎰 Spinner Wheel")
st.markdown("""
Add options and specify how many times each one can be selected. 
Once an option's limit is reached, it will no longer be available.
""")

STORE_PATH = Path(__file__).parent / "data" / "shared_state.json"
LOCK_PATH = str(STORE_PATH) + ".lock"
STATE_OP_LOCK = threading.Lock()


def default_shared_state():
    return {
        "options": [],
        "assignments": [],
        "next_submission_seq": 1,
        "spin_id": 0,
        "updated_at": time.time()
    }


def normalize_state(state):
    if not isinstance(state, dict):
        state = default_shared_state()

    if "options" not in state or not isinstance(state["options"], list):
        state["options"] = []
    if "assignments" not in state or not isinstance(state["assignments"], list):
        state["assignments"] = []
    if "next_submission_seq" not in state or not isinstance(state["next_submission_seq"], int):
        state["next_submission_seq"] = 1
    if state["next_submission_seq"] < 1:
        state["next_submission_seq"] = 1
    if "spin_id" not in state or not isinstance(state["spin_id"], int):
        state["spin_id"] = 0
    if "updated_at" not in state:
        state["updated_at"] = time.time()

    normalized_assignments = []
    fallback_assigned_ms = int(float(state.get("updated_at", time.time())) * 1000)
    for item in state["assignments"]:
        if not isinstance(item, dict):
            continue
        spin_id = item.get("spin_id")
        option_name = str(item.get("option_name", "")).strip()
        if not isinstance(spin_id, int) or not option_name:
            continue

        assigned_at_raw = item.get("assigned_at_ms")
        if isinstance(assigned_at_raw, (int, float)):
            assigned_at_ms = int(assigned_at_raw)
        else:
            assigned_at_ms = fallback_assigned_ms

        completed_raw = item.get("completed_at_ms")
        if isinstance(completed_raw, (int, float)):
            completed_at_ms = int(completed_raw)
        else:
            completed_at_ms = None

        normalized_assignments.append({
            "spin_id": spin_id,
            "option_name": option_name,
            "assigned_at_ms": assigned_at_ms,
            "team_name": str(item.get("team_name", "")).strip(),
            "completed_at_ms": completed_at_ms,
            "submission_seq": int(item.get("submission_seq")) if isinstance(item.get("submission_seq"), int) and int(item.get("submission_seq")) > 0 else None
        })

    state["assignments"] = normalized_assignments

    return state


def current_time_ms():
    return int(time.time_ns() // 1_000_000)


def format_timestamp_ms(value):
    if not isinstance(value, (int, float)):
        return "-"
    return datetime.fromtimestamp(float(value) / 1000).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def format_duration_ms(duration_ms):
    if not isinstance(duration_ms, (int, float)):
        return "-"
    return f"{int(duration_ms)} ms"


def get_sync_config():
    try:
        sync = st.secrets["sync"]
    except (StreamlitSecretNotFoundError, KeyError, TypeError):
        return None

    provider = str(sync.get("provider", "")).strip().lower()
    if provider != "supabase":
        return None

    url = str(sync.get("supabase_url", "")).strip()
    key = str(sync.get("supabase_key", "")).strip()
    app_id = str(sync.get("app_id", "limited-use-spinner")).strip() or "limited-use-spinner"

    if not url or not key:
        return None

    return {
        "provider": "supabase",
        "supabase_url": url,
        "supabase_key": key,
        "app_id": app_id
    }


@st.cache_resource
def get_supabase_client(url, key):
    supabase_module = importlib.import_module("supabase")
    return supabase_module.create_client(url, key)


def run_with_retries(operation, attempts=3, delay_seconds=0.35):
    last_error = None
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as error:
            last_error = error
            if attempt < attempts - 1:
                time.sleep(delay_seconds)
    raise last_error


def ensure_store_exists():
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(LOCK_PATH, timeout=5):
        if not STORE_PATH.exists():
            STORE_PATH.write_text(json.dumps(default_shared_state(), indent=2), encoding="utf-8")


def load_local_shared_state():
    ensure_store_exists()
    with FileLock(LOCK_PATH, timeout=5):
        try:
            state = json.loads(STORE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            state = default_shared_state()
        return normalize_state(state)


def save_local_shared_state(state):
    state = normalize_state(state)
    state["updated_at"] = time.time()
    payload = json.dumps(state, indent=2)
    with FileLock(LOCK_PATH, timeout=5):
        STORE_PATH.write_text(payload, encoding="utf-8")


def load_supabase_state(sync_config):
    client = get_supabase_client(sync_config["supabase_url"], sync_config["supabase_key"])
    app_id = sync_config["app_id"]

    response = run_with_retries(lambda: client.table("spinner_state").select("state").eq("id", app_id).limit(1).execute())
    if response.data:
        return normalize_state(response.data[0].get("state"))

    state = default_shared_state()
    run_with_retries(lambda: client.table("spinner_state").upsert({
        "id": app_id,
        "state": state
    }).execute())
    return state


def save_supabase_state(sync_config, state):
    client = get_supabase_client(sync_config["supabase_url"], sync_config["supabase_key"])
    app_id = sync_config["app_id"]
    state = normalize_state(state)
    state["updated_at"] = time.time()
    run_with_retries(lambda: client.table("spinner_state").upsert({
        "id": app_id,
        "state": state
    }).execute())


def spin_supabase_once(sync_config):
    client = get_supabase_client(sync_config["supabase_url"], sync_config["supabase_key"])
    app_id = sync_config["app_id"]

    response = run_with_retries(lambda: client.rpc("spin_once", {"p_id": app_id}).execute())
    payload = response.data

    if payload is None:
        raise ValueError("Empty response from spin_once RPC")

    if isinstance(payload, list):
        payload = payload[0] if payload else None

    if not isinstance(payload, dict):
        raise ValueError("Unexpected spin_once RPC response format")

    if payload.get("error"):
        raise ValueError(str(payload["error"]))

    winner_name = payload.get("winner_name")
    if not winner_name:
        return None

    labels_for_spin = payload.get("labels_for_spin", [])
    if not labels_for_spin:
        labels_for_spin = [winner_name]

    return {
        "winner_name": winner_name,
        "winner_description": payload.get("winner_description", ""),
        "labels_for_spin": labels_for_spin,
        "spin_id": int(payload.get("spin_id", 0))
    }


def submit_supabase_completion_once(sync_config, spin_id, team_name):
    client = get_supabase_client(sync_config["supabase_url"], sync_config["supabase_key"])

    response = run_with_retries(lambda: client.rpc("submit_completion_once", {
        "p_id": sync_config["app_id"],
        "p_spin_id": int(spin_id),
        "p_team_name": str(team_name)
    }).execute())
    payload = response.data

    if payload is None:
        raise ValueError("Empty response from submit_completion_once RPC")

    if isinstance(payload, list):
        payload = payload[0] if payload else None

    if not isinstance(payload, dict):
        raise ValueError("Unexpected submit_completion_once RPC response format")

    if payload.get("error"):
        return False, str(payload["error"])
    if payload.get("ok") is True:
        return True, str(payload.get("message") or "Completion submitted successfully.")
    return False, str(payload.get("message") or "Completion failed.")


def is_missing_spin_rpc_error(error):
    message = str(error)
    return "PGRST202" in message or "Could not find the function public.spin_once" in message


def is_missing_submit_rpc_error(error):
    message = str(error)
    return "PGRST202" in message or "Could not find the function public.submit_completion_once" in message


def load_shared_state():
    sync_config = get_sync_config()
    if sync_config is None or st.session_state.force_local_sync:
        st.session_state.sync_backend = "local"
        return load_local_shared_state()

    try:
        state = load_supabase_state(sync_config)
        st.session_state.sync_backend = "supabase"
        st.session_state.force_local_sync = False
        return state
    except Exception as error:
        st.session_state.sync_backend = "local"
        st.session_state.sync_warning = f"Cloud read unavailable ({error}). Showing local snapshot for now."
        return load_local_shared_state()


def save_shared_state(state):
    sync_config = get_sync_config()
    if sync_config is None or st.session_state.force_local_sync:
        st.session_state.sync_backend = "local"
        return save_local_shared_state(state)

    try:
        result = save_supabase_state(sync_config, state)
        st.session_state.sync_backend = "supabase"
        st.session_state.force_local_sync = False
        return result
    except Exception as error:
        st.session_state.sync_backend = "supabase"
        st.session_state.sync_warning = f"Cloud save failed ({error}). Change was not saved to cloud."
        raise RuntimeError("Cloud save failed") from error


def add_option_shared(name, description, limit):
    with STATE_OP_LOCK:
        try:
            clean_name = name.strip()
            if not clean_name:
                return False, "Option name is required."

            state = load_shared_state()
            options = state.get("options", [])
            if any(str(opt.get("name", "")).strip().lower() == clean_name.lower() for opt in options):
                return False, f"'{clean_name}' already exists!"

            options.append({
                "name": clean_name,
                "description": description,
                "limit": int(limit),
                "remaining": int(limit)
            })
            state["options"] = options
            save_shared_state(state)
            return True, f"Added '{clean_name}'"
        except Exception as error:
            return False, f"Failed to add option: {error}"


def reset_shared_state():
    with STATE_OP_LOCK:
        save_shared_state(default_shared_state())


def spin_shared_once():
    sync_config = get_sync_config()
    if sync_config is not None and not st.session_state.force_local_sync and st.session_state.spin_rpc_enabled:
        try:
            spin_result = spin_supabase_once(sync_config)
            st.session_state.sync_backend = "supabase"
            st.session_state.force_local_sync = False
            if spin_result is not None:
                try:
                    record_spin_assignment(spin_result["spin_id"], spin_result["winner_name"])
                except Exception as error:
                    st.session_state.sync_warning = f"Spin recorded, but assignment log failed ({error})."
            return spin_result
        except Exception as error:
            if is_missing_spin_rpc_error(error):
                st.session_state.spin_rpc_enabled = False
                st.session_state.sync_warning = "Atomic cloud RPC not installed. Using standard cloud mode."
            else:
                st.session_state.sync_warning = "Cloud spin RPC unavailable. Using standard cloud mode."

    with STATE_OP_LOCK:
        state = load_shared_state()
        options = state.get("options", [])
        pool = [index for index, option in enumerate(options) if option.get("remaining", 0) > 0]

        if not pool:
            return None

        winner_index = random.choice(pool)
        winner = options[winner_index]
        labels_for_spin = [options[index]["name"] for index in pool]

        winner["remaining"] = int(winner.get("remaining", 0)) - 1
        state["spin_id"] = int(state.get("spin_id", 0)) + 1

        spin_assignment = {
            "spin_id": state["spin_id"],
            "option_name": winner["name"],
            "assigned_at_ms": current_time_ms(),
            "team_name": "",
            "completed_at_ms": None,
            "submission_seq": None
        }
        assignments = state.get("assignments", [])
        if not any(item.get("spin_id") == spin_assignment["spin_id"] for item in assignments if isinstance(item, dict)):
            assignments.append(spin_assignment)
        state["assignments"] = assignments

        save_shared_state(state)

        return {
            "winner_name": winner["name"],
            "winner_description": winner.get("description", ""),
            "labels_for_spin": labels_for_spin,
            "spin_id": state["spin_id"]
        }


def record_spin_assignment(spin_id, option_name):
    with STATE_OP_LOCK:
        state = load_shared_state()
        assignments = state.get("assignments", [])
        if any(item.get("spin_id") == int(spin_id) for item in assignments if isinstance(item, dict)):
            return

        assignments.append({
            "spin_id": int(spin_id),
            "option_name": str(option_name),
            "assigned_at_ms": current_time_ms(),
            "team_name": "",
            "completed_at_ms": None,
            "submission_seq": None
        })
        state["assignments"] = assignments
        try:
            save_shared_state(state)
        except Exception as error:
            st.session_state.sync_warning = f"Assignment log save failed ({error})."


def submit_completion(spin_id, team_name):
    sync_config = get_sync_config()
    if sync_config is not None and not st.session_state.force_local_sync and st.session_state.submit_rpc_enabled:
        try:
            ok, message = submit_supabase_completion_once(sync_config, spin_id, team_name)
            st.session_state.sync_backend = "supabase"
            st.session_state.force_local_sync = False
            return ok, message
        except Exception as error:
            if is_missing_submit_rpc_error(error):
                st.session_state.submit_rpc_enabled = False
                st.session_state.sync_warning = "Atomic submit RPC not installed. Using standard submit mode."
            else:
                st.session_state.sync_warning = "Cloud submit RPC unavailable. Using standard submit mode."

    with STATE_OP_LOCK:
        try:
            state = load_shared_state()
            assignments = state.get("assignments", [])
            next_submission_seq = int(state.get("next_submission_seq", 1))
            if next_submission_seq < 1:
                next_submission_seq = 1
            for item in assignments:
                if isinstance(item, dict) and item.get("spin_id") == int(spin_id):
                    if item.get("completed_at_ms"):
                        return False, "This task was already submitted."
                    item["team_name"] = team_name.strip()
                    item["completed_at_ms"] = current_time_ms()
                    item["submission_seq"] = next_submission_seq
                    state["next_submission_seq"] = next_submission_seq + 1
                    state["assignments"] = assignments
                    save_shared_state(state)
                    return True, "Completion submitted successfully."

            return False, "Task assignment not found."
        except Exception as error:
            return False, f"Submit failed: {error}"

# Initialize session state for options if it doesn't exist
if 'last_result' not in st.session_state:
    st.session_state.last_result = None

if 'last_sent_signature' not in st.session_state:
    st.session_state.last_sent_signature = None

if 'last_spin_wheel' not in st.session_state:
    st.session_state.last_spin_wheel = None

if 'pending_wheel_animation' not in st.session_state:
    st.session_state.pending_wheel_animation = False

if 'pending_spin_started_at_ms' not in st.session_state:
    st.session_state.pending_spin_started_at_ms = None

if 'sync_backend' not in st.session_state:
    st.session_state.sync_backend = "local"

if 'sync_warning' not in st.session_state:
    st.session_state.sync_warning = None

if 'force_local_sync' not in st.session_state:
    st.session_state.force_local_sync = False

if 'spin_rpc_enabled' not in st.session_state:
    st.session_state.spin_rpc_enabled = True

if 'submit_rpc_enabled' not in st.session_state:
    st.session_state.submit_rpc_enabled = True

shared_state = load_shared_state()
shared_options = shared_state["options"]

if not st.session_state.pending_wheel_animation:
    st_autorefresh(interval=3000, key="sync-refresh")

def get_smtp_config():
    try:
        secrets = st.secrets
        smtp = secrets["smtp"]
        required_keys = ["host", "port", "username", "password", "from_email"]
        if any(not smtp.get(key) for key in required_keys):
            return None

        return {
            "host": smtp["host"],
            "port": int(smtp["port"]),
            "username": smtp["username"],
            "password": smtp["password"],
            "from_email": smtp["from_email"],
            "use_tls": bool(smtp.get("use_tls", True))
        }
    except (StreamlitSecretNotFoundError, KeyError, TypeError, ValueError):
        return None


def send_email(recipient, subject, body):
    smtp_config = get_smtp_config()
    if smtp_config is None:
        raise ValueError("SMTP is not configured. Add smtp settings in .streamlit/secrets.toml")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = smtp_config["from_email"]
    message["To"] = recipient
    message.set_content(body)

    with smtplib.SMTP(smtp_config["host"], smtp_config["port"], timeout=15) as server:
        if smtp_config["use_tls"]:
            server.starttls()
        server.login(smtp_config["username"], smtp_config["password"])
        server.send_message(message)

    return True


def is_valid_email(value):
    pattern = r"^[^\s@]+@[^\s@]+\.[^\s@]+$"
    return re.match(pattern, value) is not None


def render_wheel(labels, winner_name=None, animate=False, spin_key=0):
        if not labels:
                st.info("Add options to see the wheel.")
                return

        winner_index = labels.index(winner_name) if winner_name in labels else 0
        labels_json = json.dumps(labels)
        animate_js = "true" if animate else "false"
        wheel_id = f"wheel-{spin_key}-{len(labels)}"

        wheel_html = f"""
        <div style="display:flex; flex-direction:column; align-items:center; gap:8px;">
            <div style="position:relative; width:340px; height:340px;">
                <div style="position:absolute; top:-2px; left:50%; transform:translateX(-50%); width:0; height:0;
                                        border-left:14px solid transparent; border-right:14px solid transparent;
                                        border-top:26px solid #111827; z-index:10;"></div>
                <canvas id="{wheel_id}" width="340" height="340"></canvas>
            </div>
            <div style="font-size:13px; color:#6B7280;">{('Spinning...' if animate else 'Ready to spin')}</div>
        </div>

        <script>
            (function() {{
                const labels = {labels_json};
                const winnerIndex = {winner_index};
                const animate = {animate_js};
                const canvas = document.getElementById("{wheel_id}");
                const ctx = canvas.getContext("2d");
                const colors = [
                    "#60A5FA", "#34D399", "#FBBF24", "#F472B6", "#A78BFA",
                    "#F87171", "#22D3EE", "#4ADE80", "#FB923C", "#94A3B8"
                ];

                function drawWheel(rotationDeg) {{
                    const cx = canvas.width / 2;
                    const cy = canvas.height / 2;
                    const radius = 155;
                    const segment = (Math.PI * 2) / labels.length;

                    ctx.clearRect(0, 0, canvas.width, canvas.height);
                    ctx.save();
                    ctx.translate(cx, cy);
                    ctx.rotate((rotationDeg * Math.PI) / 180);

                    for (let i = 0; i < labels.length; i++) {{
                        const start = i * segment;
                        const end = start + segment;

                        ctx.beginPath();
                        ctx.moveTo(0, 0);
                        ctx.arc(0, 0, radius, start, end);
                        ctx.closePath();
                        ctx.fillStyle = colors[i % colors.length];
                        ctx.fill();
                        ctx.lineWidth = 2;
                        ctx.strokeStyle = "#ffffff";
                        ctx.stroke();

                        ctx.save();
                        ctx.rotate(start + segment / 2);
                        ctx.textAlign = "right";
                        ctx.fillStyle = "#111827";
                        ctx.font = "bold 13px sans-serif";
                        const label = String(labels[i]).slice(0, 16);
                        ctx.fillText(label, radius - 12, 4);
                        ctx.restore();
                    }}

                    ctx.beginPath();
                    ctx.arc(0, 0, 30, 0, Math.PI * 2);
                    ctx.fillStyle = "#111827";
                    ctx.fill();
                    ctx.fillStyle = "#ffffff";
                    ctx.font = "bold 12px sans-serif";
                    ctx.textAlign = "center";
                    ctx.fillText("SPIN", 0, 4);

                    ctx.restore();
                }}

                drawWheel(0);

                if (animate && labels.length > 0) {{
                    const segmentDeg = 360 / labels.length;
                    const winnerCenterDeg = (winnerIndex + 0.5) * segmentDeg;
                    const baseOffset = ((270 - winnerCenterDeg) % 360 + 360) % 360;
                    const target = 2160 + baseOffset;
                    const duration = 4200;
                    let start = null;

                    function easeOutCubic(x) {{
                        return 1 - Math.pow(1 - x, 3);
                    }}

                    function animateSpin(ts) {{
                        if (!start) start = ts;
                        const progress = Math.min((ts - start) / duration, 1);
                        const eased = easeOutCubic(progress);
                        drawWheel(target * eased);
                        if (progress < 1) {{
                            requestAnimationFrame(animateSpin);
                        }} else {{
                            drawWheel(target);
                        }}
                    }}

                    requestAnimationFrame(animateSpin);
                }}
            }})();
        </script>
        """

        components.html(wheel_html, height=390)

# --- Sidebar: Add New Options ---
with st.sidebar:
    st.header("Add New Option")
    sync_backend_label = "Cloud (Supabase)" if st.session_state.sync_backend == "supabase" else "Local file"
    updated_at_value = shared_state.get("updated_at")
    if isinstance(updated_at_value, (int, float)):
        updated_at_text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(updated_at_value))
    else:
        updated_at_text = "Unknown"

    st.caption(f"Sync: {sync_backend_label}")
    st.caption(f"Last update: {updated_at_text}")
    if st.session_state.sync_backend == "supabase":
        st.success("Cloud sync active")
    else:
        st.info("Local sync active")

    with st.expander("Diagnostics", expanded=False):
        sync_config = get_sync_config()
        active_count = sum(1 for opt in shared_options if opt.get("remaining", 0) > 0)
        total_count = len(shared_options)

        st.caption(f"Backend: {st.session_state.sync_backend}")
        st.caption(f"Force local: {st.session_state.force_local_sync}")
        st.caption(f"RPC enabled: {st.session_state.spin_rpc_enabled}")
        st.caption(f"Submit RPC enabled: {st.session_state.submit_rpc_enabled}")
        st.caption(f"Options: {active_count} active / {total_count} total")
        st.caption(f"Spin ID: {shared_state.get('spin_id', 0)}")

        test_cloud_btn = st.button(
            "Test cloud connection",
            disabled=sync_config is None,
            key="test_cloud_connection_btn"
        )

        if sync_config is None:
            st.caption("Cloud config not set in secrets.")
        elif test_cloud_btn:
            try:
                _ = load_supabase_state(sync_config)
                st.success("Cloud connection OK")
            except Exception as error:
                st.error(f"Cloud check failed: {error}")

    if get_smtp_config() is None:
        st.warning("SMTP not configured. Add credentials in .streamlit/secrets.toml")

    with st.form("add_option_form", clear_on_submit=True):
        new_option_name = st.text_input("Option Name")
        new_option_desc = st.text_area("Description (optional)")
        new_option_limit = st.number_input("Usage Limit", min_value=1, value=1, step=1)
        submitted = st.form_submit_button("Add Option")
        
        if submitted and new_option_name:
            ok, message = add_option_shared(new_option_name, new_option_desc, new_option_limit)
            if ok:
                st.success(message)
                st.rerun()
            else:
                st.error(message)

    st.divider()
    if st.button("Reset All", type="primary"):
        reset_shared_state()
        st.session_state.last_result = None
        st.session_state.last_spin_wheel = None
        st.session_state.pending_wheel_animation = False
        st.rerun()

# --- Main Area: Display Options and Spin ---

wheel_col, options_col = st.columns([2.2, 1])

with wheel_col:
    st.subheader("Spinner")
    backend_label = "Cloud (Supabase)" if st.session_state.sync_backend == "supabase" else "Local file"
    st.caption(f"Auto-sync enabled via {backend_label} (refreshes every 3 seconds).")
    if st.session_state.sync_warning:
        st.warning(st.session_state.sync_warning)
        st.session_state.sync_warning = None
    
    pool = []
    for index, opt in enumerate(shared_options):
        if opt['remaining'] > 0:
            pool.append(index)
    
    can_spin = len(pool) > 0

    active_labels_now = [shared_options[index]['name'] for index in pool]
    is_animating_run = st.session_state.pending_wheel_animation and st.session_state.last_spin_wheel is not None

    if is_animating_run:
        wheel_state = st.session_state.last_spin_wheel
        render_wheel(
            labels=wheel_state['labels'],
            winner_name=wheel_state['winner_name'],
            animate=True,
            spin_key=wheel_state['spin_id']
        )
        st.caption("Spinning... result will appear once the wheel lands.")
        elapsed_ms = None
        if isinstance(st.session_state.pending_spin_started_at_ms, int):
            elapsed_ms = current_time_ms() - st.session_state.pending_spin_started_at_ms

        refresh_count = st_autorefresh(
            interval=4300,
            key=f"spin-finish-{wheel_state['spin_id']}"
        )
        if refresh_count < 1 and (elapsed_ms is None or elapsed_ms < 4300):
            st.stop()
        st.session_state.pending_wheel_animation = False
        st.session_state.pending_spin_started_at_ms = None
        st.rerun()
    else:
        render_wheel(
            labels=active_labels_now,
            animate=False,
            spin_key=shared_state.get("spin_id", 0)
        )
    
    spin_btn = st.button("SPIN!", disabled=not can_spin, use_container_width=True, type="primary")

with options_col:
    with st.expander("Current Options", expanded=False):
        if not shared_options:
            st.info("No options added yet. Use the sidebar to add some!")
        else:
            active_options = [opt for opt in shared_options if opt['remaining'] > 0]
            finished_options = [opt for opt in shared_options if opt['remaining'] == 0]

            if active_options:
                st.caption("Active")
                for opt in active_options:
                    st.progress(opt['remaining'] / opt['limit'], text=f"{opt['name']}: {opt['remaining']} / {opt['limit']} left")

            if finished_options:
                st.caption("Depleted")
                for opt in finished_options:
                    st.text(f"❌ {opt['name']} (0 left)")

if spin_btn:
    with st.spinner("Spinning..."):
        try:
            spin_result = spin_shared_once()
        except Exception as error:
            st.error(f"Spin failed: {error}")
            st.stop()

        if spin_result is None:
            st.warning("No options available to spin.")
            st.rerun()

        st.session_state.last_spin_wheel = {
            'labels': spin_result['labels_for_spin'],
            'winner_name': spin_result['winner_name'],
            'spin_id': spin_result['spin_id']
        }
        st.session_state.pending_wheel_animation = True
        st.session_state.last_result = {
            'name': spin_result['winner_name'],
            'description': spin_result['winner_description'],
            'spin_id': spin_result['spin_id']
        }
        st.session_state.pending_spin_started_at_ms = current_time_ms()
        st.session_state['result_email_input'] = ""
        st.rerun()

if st.session_state.last_result and not is_animating_run:
    result = st.session_state.last_result
    st.success(f"Result: **{result['name']}**")
    if result.get('description'):
        st.info(f"**Description:** {result['description']}")

    st.markdown("### 📧 Send Result Automatically")
    recipient_email = st.text_input(
        "Enter recipient email",
        key="result_email_input",
        placeholder="name@example.com"
    ).strip()

    if recipient_email:
        if not is_valid_email(recipient_email):
            st.warning("Please enter a valid email address.")
        else:
            signature = f"{result['spin_id']}|{recipient_email.lower()}"
            if st.session_state.last_sent_signature != signature:
                subject = f"Spin Result: {result['name']}"
                body = (
                    f"You spun the wheel and got:\n\n"
                    f"Option: {result['name']}\n"
                    f"Description: {result.get('description', '')}\n"
                )

                with st.spinner("Sending email..."):
                    try:
                        send_email(recipient_email, subject, body)
                        st.session_state.last_sent_signature = signature
                        st.success(f"Email sent to {recipient_email}!")
                    except Exception as error:
                        st.error(f"Failed to send email: {error}")
            else:
                st.caption("Email already sent for this spin result and address.")

st.markdown("### 🏁 Completion & Leaderboard")
submit_col, leaderboard_col = st.columns([1, 1.4])

assignments_all = shared_state.get("assignments", [])
pending_assignments = [item for item in assignments_all if isinstance(item, dict) and not item.get("completed_at_ms")]
completed_assignments = [item for item in assignments_all if isinstance(item, dict) and item.get("completed_at_ms")]

with submit_col:
    st.markdown("#### Submit Completed Task")
    if not pending_assignments:
        st.info("No pending assigned tasks right now.")
    else:
        assignment_labels = {}
        for item in sorted(pending_assignments, key=lambda row: int(row.get("spin_id", 0))):
            spin_id = int(item.get("spin_id", 0))
            label = f"#{spin_id} • {item.get('option_name', 'Task')} • {format_timestamp_ms(item.get('assigned_at_ms'))}"
            assignment_labels[label] = spin_id

        with st.form("submit_completion_form", clear_on_submit=True):
            selected_label = st.selectbox("Assigned task", list(assignment_labels.keys()))
            team_name_input = st.text_input("Team name")
            completion_submit = st.form_submit_button("Submit")

            if completion_submit:
                team_name = team_name_input.strip()
                if not team_name:
                    st.error("Please enter your team name.")
                else:
                    ok, message = submit_completion(assignment_labels[selected_label], team_name)
                    if ok:
                        st.success(message)
                        st.rerun()
                    else:
                        st.error(message)

with leaderboard_col:
    st.markdown("#### Leaderboard")
    if not completed_assignments:
        st.info("No completed submissions yet.")
    else:
        leaderboard_rows = []
        for item in completed_assignments:
            assigned_at_ms = int(item.get("assigned_at_ms", 0))
            completed_at_ms = int(item.get("completed_at_ms", 0))
            duration_ms = max(completed_at_ms - assigned_at_ms, 0)
            leaderboard_rows.append({
                "Team": item.get("team_name") or "-",
                "Task": item.get("option_name") or "-",
                "Spin #": int(item.get("spin_id", 0)),
                "Assigned at": format_timestamp_ms(assigned_at_ms),
                "Completed at": format_timestamp_ms(completed_at_ms),
                "Time": format_duration_ms(duration_ms),
                "_duration_sort": duration_ms,
                "_completed_sort": completed_at_ms,
                "_submission_seq_sort": int(item.get("submission_seq", 0)) if isinstance(item.get("submission_seq"), int) else 0
            })

        leaderboard_rows.sort(key=lambda row: (row["_duration_sort"], row["_completed_sort"], row["_submission_seq_sort"]))
        for index, row in enumerate(leaderboard_rows, start=1):
            row["Rank"] = index

        display_rows = []
        for row in leaderboard_rows:
            display_rows.append({
                "Rank": row["Rank"],
                "Team": row["Team"],
                "Task": row["Task"],
                "Spin #": row["Spin #"],
                "Assigned at": row["Assigned at"],
                "Completed at": row["Completed at"],
                "Time": row["Time"]
            })

        st.dataframe(display_rows, use_container_width=True, hide_index=True)
