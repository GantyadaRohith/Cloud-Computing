import streamlit as st
import random
import time
import re
import smtplib
import json
import streamlit.components.v1 as components
from email.message import EmailMessage
from streamlit.errors import StreamlitSecretNotFoundError
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Spinner Wheel", page_icon="🎰")

st.title("🎰 Spinner Wheel")
st.markdown("""
Add options and specify how many times each one can be selected. 
Once an option's limit is reached, it will no longer be available.
""")

# Initialize session state for options if it doesn't exist
if 'options' not in st.session_state:
    # Structure: [{'name': 'Option A', 'limit': 3, 'remaining': 3}]
    st.session_state.options = []

if 'last_result' not in st.session_state:
    st.session_state.last_result = None

if 'spin_id' not in st.session_state:
    st.session_state.spin_id = 0

if 'last_sent_signature' not in st.session_state:
    st.session_state.last_sent_signature = None

if 'last_spin_wheel' not in st.session_state:
    st.session_state.last_spin_wheel = None

if 'pending_wheel_animation' not in st.session_state:
    st.session_state.pending_wheel_animation = False

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
    if get_smtp_config() is None:
        st.warning("SMTP not configured. Add credentials in .streamlit/secrets.toml")

    with st.form("add_option_form", clear_on_submit=True):
        new_option_name = st.text_input("Option Name")
        new_option_desc = st.text_area("Description (optional)")
        new_option_limit = st.number_input("Usage Limit", min_value=1, value=1, step=1)
        submitted = st.form_submit_button("Add Option")
        
        if submitted and new_option_name:
            # Check for duplicates (optional, but good practice)
            if any(opt['name'] == new_option_name for opt in st.session_state.options):
                st.error(f"'{new_option_name}' already exists!")
            else:
                st.session_state.options.append({
                    'name': new_option_name,
                    'description': new_option_desc,
                    'limit': new_option_limit,
                    'remaining': new_option_limit
                })
                st.success(f"Added '{new_option_name}'")

    st.divider()
    if st.button("Reset All", type="primary"):
        st.session_state.options = []
        st.session_state.last_result = None
        st.session_state.last_spin_wheel = None
        st.session_state.pending_wheel_animation = False
        st.rerun()

# --- Main Area: Display Options and Spin ---

wheel_col, options_col = st.columns([2.2, 1])

with wheel_col:
    st.subheader("Spinner")
    
    # Calculate available pool
    pool = []
    for index, opt in enumerate(st.session_state.options):
        # We add the index to the pool as many times as it has remaining?
        # OR just once if it has > 0 and we want equal probability per unique item?
        # Usually "wheel" implies prob weighted by size, but "usage limit" might just mean availability.
        # Let's assume: Each available item has an equal chance of being picked, regardless of how many "uses" it has left.
        # If the user wants weighted probability (more uses left = higher chance), we can change this logic.
        
        # User request: "add each option on which it lands and how many times that option can be used"
        # Simplest interpretation: It is in the bag if count > 0.
        if opt['remaining'] > 0:
            pool.append(index)
    
    can_spin = len(pool) > 0

    active_labels_now = [st.session_state.options[index]['name'] for index in pool]
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
        refresh_count = st_autorefresh(
            interval=4300,
            key=f"spin-finish-{wheel_state['spin_id']}"
        )
        if refresh_count < 1:
            st.stop()
        st.session_state.pending_wheel_animation = False
        st.rerun()
    else:
        render_wheel(
            labels=active_labels_now,
            animate=False,
            spin_key=st.session_state.spin_id
        )
    
    spin_btn = st.button("SPIN!", disabled=not can_spin, use_container_width=True, type="primary")

with options_col:
    with st.expander("Current Options", expanded=False):
        if not st.session_state.options:
            st.info("No options added yet. Use the sidebar to add some!")
        else:
            active_options = [opt for opt in st.session_state.options if opt['remaining'] > 0]
            finished_options = [opt for opt in st.session_state.options if opt['remaining'] == 0]

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
        time.sleep(1)
        winner_index = random.choice(pool)
        winner = st.session_state.options[winner_index]
        labels_for_spin = [st.session_state.options[index]['name'] for index in pool]

        st.session_state.spin_id += 1
        st.session_state.last_spin_wheel = {
            'labels': labels_for_spin,
            'winner_name': winner['name'],
            'spin_id': st.session_state.spin_id
        }
        st.session_state.pending_wheel_animation = True
        st.session_state.options[winner_index]['remaining'] -= 1
        st.session_state.last_result = {
            'name': winner['name'],
            'description': winner.get('description', ''),
            'spin_id': st.session_state.spin_id
        }
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
