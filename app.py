import streamlit as st
import streamlit.components.v1 as components
from groq import Groq, RateLimitError
from supabase import create_client
import json
import time
import datetime
import re
import os

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="CMRIT – Software Developer Essay Assessment",
    page_icon="🖥️",
    layout="centered",
)

# ── Styling ─────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

  html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

  .stApp { background: #ffffff; color: #1f2328; }

  .hero {
    background: linear-gradient(135deg, #f6f8fa 0%, #ffffff 60%);
    border: 1px solid #d0d7de;
    border-radius: 12px;
    padding: 2rem 2.4rem;
    margin-bottom: 1.8rem;
  }
  .hero h1 { font-size: 1.8rem; font-weight: 700; color: #0969da; margin: 0 0 .3rem; }
  .hero p  { color: #57606a; margin: 0; font-size: .95rem; }

  .card {
    background: #f6f8fa;
    border: 1px solid #d0d7de;
    border-radius: 10px;
    padding: 1.6rem 2rem;
    margin-bottom: 1.2rem;
  }

  .timer-box {
    background: #fff1e7;
    border: 1px solid #d4742c;
    border-radius: 8px;
    padding: .8rem 1.2rem;
    font-family: 'JetBrains Mono', monospace;
    font-size: 1.5rem;
    font-weight: 600;
    color: #bc4c00;
    text-align: center;
  }
  .timer-ok  { background: #e6f4ea; border-color: #1a7f37; color: #1a7f37; }
  .timer-warn{ background: #fff8e6; border-color: #9a6700; color: #9a6700; }

  .grade-badge {
    display: inline-block;
    padding: .25rem .75rem;
    border-radius: 20px;
    font-weight: 700;
    font-size: 1.1rem;
  }
  .grade-A { background:#dafbe1; color:#1a7f37; }
  .grade-B { background:#ddf4ff; color:#0969da; }
  .grade-C { background:#fff8c5; color:#9a6700; }
  .grade-D { background:#ffeee8; color:#bc4c00; }
  .grade-F { background:#ffebe9; color:#cf222e; }

  .stButton > button {
    background: #238636; border: 1px solid #2ea043;
    color: white; border-radius: 6px; font-weight: 600;
    padding: .5rem 1.5rem; transition: background .2s;
  }
  .stButton > button:hover { background: #2ea043; }

  .submitted-tag {
    background:#dafbe1; color:#1a7f37; border-radius:6px;
    padding:.4rem .9rem; font-size:.85rem; font-weight:600;
  }
  .word-counter { color:#57606a; font-size:.8rem; font-family:'JetBrains Mono',monospace; }
  .st-key-auto_submit_container { display: none; }
</style>
""", unsafe_allow_html=True)

# ── Constants ───────────────────────────────────────────────────────────────────
ADMIN_EMAIL   = os.environ.get("ADMIN_EMAIL") or st.secrets.get("ADMIN_EMAIL", "")
ADMIN_USN     = (os.environ.get("ADMIN_USN") or st.secrets.get("ADMIN_USN", "")).upper()
MAX_MINUTES   = 20
MAX_SECONDS   = MAX_MINUTES * 60
ESSAY_TOPICS  = [
    "Artificial Intelligence: Workforce Replacement or Opportunity Creation?",
    "Remote Work vs. Office Collaboration: The Productivity Debate",
    "The Necessity of Continuous Learning for Software Engineers",
    "Social Media: A Tool for Connection or Professional Distraction?",
    "Synthetic Media and the Death of Truth: Can Democracy Survive an Internet Where Anything Can Be Faked?",
    "The 'Hook' Economy: Who Is to Blame When Our Apps Become Addictive?",
]

# ── Supabase client ─────────────────────────────────────────────────────────────
@st.cache_resource
def get_supabase():
    url = os.environ.get("SUPABASE_URL") or st.secrets.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY") or st.secrets.get("SUPABASE_KEY")
    return create_client(url, key)

# ── Storage helpers ─────────────────────────────────────────────────────────────
def load_submissions() -> list:
    resp = get_supabase().table("submissions").select("usn, data").execute()
    return [row["data"] for row in resp.data]

def save_submission(usn: str, data: dict):
    get_supabase().table("submissions").insert({"usn": usn.upper(), "data": data}).execute()

def already_submitted(usn: str) -> bool:
    resp = get_supabase().table("submissions").select("usn").eq("usn", usn.upper()).execute()
    return len(resp.data) > 0

def load_config() -> dict:
    resp = get_supabase().table("app_config").select("value").eq("key", "settings").execute()
    return resp.data[0]["value"] if resp.data else {}

def save_config(cfg: dict):
    get_supabase().table("app_config").upsert({"key": "settings", "value": cfg}).execute()

def clear_all_submissions():
    get_supabase().table("submissions").delete().neq("usn", "").execute()

def paste_enabled() -> bool:
    return load_config().get("paste_enabled", False)

# ── AI grading via Groq ─────────────────────────────────────────────────────────
def grade_essay(name: str, topic: str, essay: str) -> dict:
    api_key = os.environ.get("GROQ_API_KEY") or st.secrets.get("GROQ_API_KEY")
    client = Groq(api_key=api_key)
    words = re.findall(r"\S+", essay)
    word_count = len(words)
    truncated_essay = " ".join(words[:200])

    prompt = f"""You are an expert evaluator assessing a 100-200 word essay written by an undergraduate student applying for a Software Developer position. This essay was written in a timed assessment with approximately 20 minutes available for planning and writing.When grading:
    - Evaluate the essay relative to what can reasonably be produced within a 20-minute time limit since online 20 minutes its difficult to produce a fully polished essay, so focus on the quality of ideas and expression rather than perfection.
    - Focus on understanding of the topic, logical reasoning, clarity of ideas, organization, and communication skills.
    - Do not heavily penalize students for the absence of citations, statistics, references, or extensive supporting evidence.
    - Reward originality, relevant examples, coherent arguments, and clear expression.
    - Be objective, consistent, and moderately strict.
 Avoid grade inflation, but recognize that this is a timed writing exercise rather than a research essay.

Student name : {name}
Essay topic  : {topic}
Word count   : {word_count}
Essay text (truncated to first 200 words):
\"\"\"
{truncated_essay}
\"\"\"

CRITICAL TOPIC-RELEVANCE CHECK — apply this BEFORE scoring against the rubric below:
Determine whether the essay actually engages with the assigned topic ("{topic}"). If the essay is substantially about a different subject and does not meaningfully address the assigned topic, it is OFF-TOPIC. For an off-topic essay, regardless of how well-written, organized, or grammatically correct it is:
- content_score must be 0-3
- critical_thinking_score must be 0-5
- evidence_score must be 0-1
- organization_score and language_score may still reflect writing quality, but total_score must not exceed 15
- grade must be "F" and grade_label must be "Fail"
- overall_feedback must clearly state that the essay did not address the assigned topic
Do not let good writing mechanics on an unrelated subject compensate for missing topic relevance.

1. Content & Understanding (30 marks)
   - Demonstrates knowledge of the topic
   - Addresses the question effectively
   - Explains concepts correctly

2. Critical Thinking & Analysis (25 marks)
   - Demonstrates reasoning and judgment
   - Discusses implications, trade-offs, or benefits
   - Supports claims with logical arguments

3. Organization & Structure (20 marks)
   - Clear introduction
   - Logical flow of ideas
   - Effective conclusion

4. Relevance & Supporting Examples (5 marks)
   - Uses relevant examples where appropriate
   - Connects ideas to practical situations
   - Evidence is not required but should strengthen arguments if present

5. Language & Presentation (20 marks)
   - Grammar and spelling
   - Clarity and conciseness
   - Professional communication


Let the tone of feedback  be positive. Respond ONLY with a valid JSON object in this exact format (no markdown, no preamble):
{{
  "content_score": <0-30>,
  "critical_thinking_score": <0-25>,
  "organization_score": <0-20>,
  "evidence_score": <0-5>,
  "language_score": <0-20>,
  "total_score": <0-100>,
  "grade": "<A/B/C/D/F>",
  "grade_label": "<Excellent/Good/Average/Below Average/Fail>",
  "strengths": "<2-3 sentence only summary>",
  "improvements": "<2-3 sentence only summary>",
  "overall_feedback": "<3-4 sentence only detailed feedback>"
}}

Grade mapping: A=90-100, B=75-89, C=60-74, D=45-59, F=below 45"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=800,
        temperature=0.2,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"```json|```", "", raw).strip()
    return json.loads(raw)

def submit_essay(info: dict, essay: str, words: int):
    with st.spinner("Grading your essay with AI… this takes a few seconds."):
        try:
            result = grade_essay(info["name"], info["topic"], essay)
            result["essay"]        = essay
            result["word_count"]   = words
            result["submitted_at"] = datetime.datetime.now().isoformat()
            result["name"]         = info["name"]
            result["usn"]          = info["usn"]
            result["topic"]        = info["topic"]
            if not info.get("is_admin"):
                save_submission(info["usn"], result)
            st.session_state.result    = result
            st.session_state.submitted = True
            st.session_state.page      = "result"
            st.rerun()
        except RateLimitError:
            st.error(
                "⚠️ The daily AI grading quota has been used up for today. "
                "Please copy your essay somewhere safe and try submitting again tomorrow once the quota renews."
            )
        except Exception as e:
            st.error(f"Grading error: {e}")

# ── Timer helpers ───────────────────────────────────────────────────────────────
def start_timer():
    st.session_state["timer_start"] = time.time()

def seconds_remaining() -> int:
    if "timer_start" not in st.session_state:
        return MAX_SECONDS
    elapsed = int(time.time() - st.session_state["timer_start"])
    return max(0, MAX_SECONDS - elapsed)

def fmt_time(secs: int) -> str:
    m, s = divmod(secs, 60)
    return f"{m:02d}:{s:02d}"

# ── Pure helpers (rules also applied inline in the UI; extracted for testability) ──
def count_words(text: str) -> int:
    return len(re.findall(r"\S+", text))

def is_valid_usn(usn: str) -> bool:
    return usn.strip().upper().startswith("1CR")

def word_count_color(words: int) -> str:
    if 150 <= words <= 200:
        return "#1a7f37"
    if 130 <= words < 150 or 200 < words <= 220:
        return "#9a6700"
    return "#bc4c00"

# ── Session defaults ────────────────────────────────────────────────────────────
for key, val in {
    "page": "home",
    "student_info": None,
    "result": None,
    "submitted": False,
    "auto_submit_done": False,
}.items():
    if key not in st.session_state:
        st.session_state[key] = val

# ═══════════════════════════════════════════════════════════════════════════════
#  PAGE: HOME
# ═══════════════════════════════════════════════════════════════════════════════
if st.session_state.page == "home":
    st.markdown("""
    <div class="hero">
      <h1>🖥️ CMRIT – English Essay Assessment</h1>
      <p>Department of Artificial Intelligence & Machine Learning &amp; Engineering · Essay Evaluation Portal</p>
    </div>
    """, unsafe_allow_html=True)

    mode = st.radio("Select mode", ["📝 Take the Essay Test", "📊 Admin Report"], horizontal=True, label_visibility="collapsed")

    if mode == "📝 Take the Essay Test":
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("Student Details")

        name  = st.text_input("Full Name *")
        usn   = st.text_input("USN *")
        topic = st.selectbox("Choose Essay Topic *", ESSAY_TOPICS)

        st.markdown("""
        **Rules:**
        - You have **20 minutes** from the moment you start the test.
        - Essay must be **100–200 words**.
        - Once submitted, **no edits** are allowed.
        """)
        st.markdown("</div>", unsafe_allow_html=True)

        if st.button("🚀 Start Test", use_container_width=True):
            is_admin_session = usn.strip().upper() == ADMIN_USN
            if not all([name.strip(), usn.strip(), topic]):
                st.error("Please fill in all required fields.")
            elif not is_valid_usn(usn):
                st.error(f"Invalid USN: **{usn.upper()}**")
            else:
                st.session_state.student_info = {
                    "name": name.strip(), "usn": usn.strip().upper(),
                    "topic": topic,
                    "is_admin": is_admin_session,
                }
                st.session_state.result           = None
                st.session_state.submitted        = False
                st.session_state.auto_submit_done = False
                start_timer()
                st.session_state.page = "exam"
                st.rerun()

    else:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("Admin Access")
        admin_email = st.text_input("Admin email")
        admin_usn   = st.text_input("Admin USN")
        if st.button("🔐 Access Report", use_container_width=True):
            if admin_email.strip().lower() == ADMIN_EMAIL.lower() and admin_usn.strip().upper() == ADMIN_USN:
                st.session_state.page = "report"
                st.rerun()
            else:
                st.error("Access denied. Invalid admin email or USN.")
        st.markdown("</div>", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  PAGE: EXAM
# ═══════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "exam":
    info = st.session_state.student_info
    secs = seconds_remaining()

    if secs > 600:
        tcls = "timer-ok"
    elif secs > 180:
        tcls = "timer-warn"
    else:
        tcls = ""

    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown(f"""
        <div class="hero" style="padding:1rem 1.5rem; margin-bottom:1rem;">
          <h1 style="font-size:1.2rem;">📝 {info['name']} &nbsp;·&nbsp; {info['usn']}</h1>
          <p>Topic: <strong style="color:#1f2328;">{info['topic']}</strong></p>
        </div>""", unsafe_allow_html=True)
    with col2:
        st.markdown(f'<div class="timer-box {tcls}" id="timer-display">{fmt_time(secs)}</div>', unsafe_allow_html=True)

    if not st.session_state.submitted:
        components.html(f"""
        <script>
        (function() {{
          const doc = window.parent.document;
          const el = doc.getElementById('timer-display');
          if (!el) return;
          if (doc.__essayTimerInterval) {{
            clearInterval(doc.__essayTimerInterval);
          }}
          let remaining = {secs};
          function fmt(s) {{
            const m = Math.floor(s / 60);
            const sec = s % 60;
            return String(m).padStart(2, '0') + ':' + String(sec).padStart(2, '0');
          }}
          function applyClass(s) {{
            el.classList.remove('timer-ok', 'timer-warn');
            if (s > 600) el.classList.add('timer-ok');
            else if (s > 180) el.classList.add('timer-warn');
          }}
          el.textContent = fmt(remaining);
          applyClass(remaining);
          doc.__essayTimerInterval = setInterval(function() {{
            remaining -= 1;
            if (remaining <= 0) {{
              clearInterval(doc.__essayTimerInterval);
              el.textContent = '00:00';
              const textarea = doc.querySelector('textarea');
              if (textarea) {{
                textarea.blur();
              }}
              setTimeout(function() {{
                const btn = doc.querySelector('.st-key-auto_submit_container button');
                if (btn) btn.click();
              }}, 400);
              return;
            }}
            el.textContent = fmt(remaining);
            applyClass(remaining);
          }}, 1000);
        }})();
        </script>
        """, height=0)

    if secs == 0:
        st.error("⏰ Time is up! Your essay is being submitted for evaluation…")

    if not st.session_state.submitted:
        essay = st.text_area(
            "Write your essay here (100–200 words):",
            height=500,
            placeholder="Begin writing your essay…",
            key="essay_text",
            disabled=(secs == 0),
        )

        words = count_words(essay) if essay.strip() else 0
        wcolor = word_count_color(words)
        st.markdown(f'<p class="word-counter" id="word-counter-display" style="color:{wcolor};">Word count: {words} / 100–200</p>', unsafe_allow_html=True)

        components.html("""
        <script>
        (function() {
          const doc = window.parent.document;
          const textarea = doc.querySelector('textarea');
          const counter = doc.getElementById('word-counter-display');
          if (!textarea || !counter) return;
          const update = () => {
            const words = textarea.value.trim() ? textarea.value.trim().split(/\\s+/).filter(Boolean).length : 0;
            counter.textContent = 'Word count: ' + words + ' / 100–200';
            let color = '#bc4c00';
            if (words >= 150 && words <= 200) color = '#1a7f37';
            else if ((words >= 130 && words < 150) || (words > 200 && words <= 220)) color = '#9a6700';
            counter.style.color = color;
          };
          if (textarea.__wordCounterHandler) {
            textarea.removeEventListener('input', textarea.__wordCounterHandler);
          }
          textarea.__wordCounterHandler = update;
          textarea.addEventListener('input', update);
        })();
        </script>
        """, height=0)

        if not (info.get("is_admin") or paste_enabled()):
            components.html("""
            <script>
            (function() {
              const doc = window.parent.document;
              if (doc.__essayPasteBlocked) return;
              doc.__essayPasteBlocked = true;
              const block = (e) => {
                if (e.target && e.target.tagName === 'TEXTAREA') e.preventDefault();
              };
              doc.addEventListener('paste', block, true);
            })();
            </script>
            """, height=0)

        with st.container(key="auto_submit_container"):
            auto_submit_clicked = st.button("auto-submit-on-timeout", key="auto_submit_btn")

        submit_col, _ = st.columns([1, 3])
        with submit_col:
            manual_submit_clicked = st.button("✅ Submit Essay", use_container_width=True, disabled=(secs == 0))

        if auto_submit_clicked:
            submit_essay(info, essay, words)
        elif manual_submit_clicked:
            if words < 50:
                st.error("Essay is too short. Please write at least 50 words.")
            else:
                submit_essay(info, essay, words)
        elif secs == 0 and not st.session_state.auto_submit_done:
            st.session_state.auto_submit_done = True
            submit_essay(info, essay, words)
    else:
        st.info("Essay submitted. Redirecting…")
        time.sleep(2)
        st.session_state.page = "result"
        st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
#  PAGE: RESULT
# ═══════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "result":
    r = st.session_state.result
    if r is None:
        info = st.session_state.student_info
        if info:
            subs = load_submissions()
            matches = [s for s in subs if s.get("usn") == info["usn"].upper()]
            r = max(matches, key=lambda s: s.get("submitted_at", ""), default=None)
            st.session_state.result = r

    if r is None:
        st.error("No result found. Please restart.")
        st.stop()

    grade     = r.get("grade", "N/A")
    grade_cls = f"grade-{grade}" if grade in "ABCDF" else "grade-F"

    st.markdown(f"""
    <div class="hero">
      <h1>🎉 Submission Confirmed</h1>
      <p>{r['name']} &nbsp;·&nbsp; {r['usn']} &nbsp;·&nbsp; {r.get('submitted_at','')[:19].replace('T',' ')}</p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Your Submitted Essay")
    st.text_area(
        "Submitted essay (read-only)",
        value=r.get("essay", ""),
        height=300,
        disabled=True,
        label_visibility="collapsed",
    )
    st.markdown("</div>", unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Score", f"{r.get('total_score',0)} / 100")
    col2.metric("Word Count",  f"{r.get('word_count',0)} words")
    col3.markdown(f"**Grade**<br><span class='grade-badge {grade_cls}'>{grade} – {r.get('grade_label','')}</span>", unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Score Breakdown")
    scores = [
        ("Content & Understanding",     r.get("content_score", 0),          30),
        ("Critical Thinking & Analysis", r.get("critical_thinking_score", 0), 25),
        ("Organization & Structure",    r.get("organization_score", 0),     20),
        ("Relevance & Supporting Examples", r.get("evidence_score", 0),       5),
        ("Language & Presentation",     r.get("language_score", 0),         20),
    ]
    for label, score, max_pts in scores:
        pct = score / max_pts
        bar_color = "#1a7f37" if pct >= .8 else ("#9a6700" if pct >= .6 else "#bc4c00")
        st.markdown(f"""
        <div style="margin-bottom:.7rem;">
          <div style="display:flex;justify-content:space-between;font-size:.85rem;color:#57606a;">
            <span>{label}</span><span style="color:#1f2328;font-weight:600;">{score}/{max_pts}</span>
          </div>
          <div style="background:#d0d7de;border-radius:4px;height:8px;margin-top:.3rem;">
            <div style="background:{bar_color};width:{pct*100:.0f}%;height:8px;border-radius:4px;"></div>
          </div>
        </div>""", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Feedback")
    st.markdown(f"**Strengths:** {r.get('strengths','')}")
    st.markdown(f"**Areas for improvement:** {r.get('improvements','')}")
    st.markdown(f"**Overall:** {r.get('overall_feedback','')}")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<span class="submitted-tag">✅ Submission locked – no further edits allowed</span>', unsafe_allow_html=True)

    if st.button("🏠 Home"):
        st.session_state.page = "home"
        st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
#  PAGE: REPORT (admin only)
# ═══════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "report":
    subs = load_submissions()

    st.markdown("""
    <div class="hero">
      <h1>📊 Admin Report – All Submissions</h1>
      <p>CMRIT Software Developer Essay Assessment · Confidential</p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Settings")
    cfg = load_config()
    paste_on = st.toggle("Allow paste in the essay window for students", value=cfg.get("paste_enabled", False))
    st.caption("Off by default. The admin test USN (1CRADMIN) can always paste regardless of this setting.")
    if paste_on != cfg.get("paste_enabled", False):
        cfg["paste_enabled"] = paste_on
        save_config(cfg)
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

    if not subs:
        st.info("No submissions yet.")
    else:
        total = len(subs)
        avg   = sum(v.get("total_score", 0) for v in subs) / total
        grade_counts = {}
        for v in subs:
            g = v.get("grade", "F")
            grade_counts[g] = grade_counts.get(g, 0) + 1

        m1, m2, m3 = st.columns(3)
        m1.metric("Total Submissions", total)
        m2.metric("Class Average",     f"{avg:.1f} / 100")
        m3.metric("Top Grade (A)",     grade_counts.get("A", 0))

        st.markdown("---")

        search       = st.text_input("🔍 Search by name or USN", "")
        grade_filter = st.multiselect("Filter by grade", ["A","B","C","D","F"], default=["A","B","C","D","F"])

        st.markdown("""
        <div style="display:grid;grid-template-columns:2fr 1.5fr 2fr 1fr 1fr;
             gap:.5rem;padding:.5rem 1rem;background:#f6f8fa;border-radius:6px;
             font-size:.78rem;font-weight:600;color:#57606a;margin-bottom:.4rem;">
          <span>NAME</span><span>USN</span><span>TOPIC</span>
          <span>SCORE</span><span>GRADE</span>
        </div>""", unsafe_allow_html=True)

        for v in sorted(subs, key=lambda x: x.get("total_score", 0), reverse=True):
            usn = v.get("usn", "")
            g = v.get("grade", "F")
            if g not in grade_filter:
                continue
            q = search.lower()
            if q and q not in v.get("name","").lower() and q not in usn.lower():
                continue
            grade_cls   = f"grade-{g}"
            topic_short = v.get("topic","")[:30] + ("…" if len(v.get("topic","")) > 30 else "")
            st.markdown(f"""
            <div style="display:grid;grid-template-columns:2fr 1.5fr 2fr 1fr 1fr;
                 gap:.5rem;padding:.6rem 1rem;background:#ffffff;border:1px solid #d0d7de;
                 border-radius:6px;margin-bottom:.3rem;font-size:.82rem;align-items:center;">
              <span style="color:#1f2328;font-weight:500;">{v.get('name','')}</span>
              <span style="font-family:'JetBrains Mono',monospace;color:#57606a;">{usn}</span>
              <span style="color:#57606a;font-size:.75rem;">{topic_short}</span>
              <span style="color:#1f2328;font-weight:600;">{v.get('total_score',0)}</span>
              <span class="grade-badge {grade_cls}" style="font-size:.75rem;">{g}</span>
            </div>""", unsafe_allow_html=True)

        st.markdown("---")
        import csv, io
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Name","USN","Topic","Total Score","Grade","Grade Label",
                          "Content & Understanding","Critical Thinking & Analysis","Organization & Structure",
                          "Relevance & Supporting Examples","Language & Presentation",
                          "Actual Words","Submitted At","Strengths","Improvements","Feedback"])
        for v in subs:
            writer.writerow([
                v.get("name"), v.get("usn"), v.get("topic"),
                v.get("total_score"), v.get("grade"), v.get("grade_label"),
                v.get("content_score"), v.get("critical_thinking_score"), v.get("organization_score"),
                v.get("evidence_score"), v.get("language_score"), v.get("word_count"),
                v.get("submitted_at"), v.get("strengths"), v.get("improvements"), v.get("overall_feedback"),
            ])
        st.download_button("⬇️ Download Full Report (CSV)", buf.getvalue(),
                           file_name="essay_report.csv", mime="text/csv")

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("⚠️ Danger Zone")
    st.caption("Permanently delete all student submissions from the database. This cannot be undone.")
    confirm_clear = st.checkbox("I understand this will permanently delete all submission records.")
    if st.button("🗑️ Clear All Submissions", disabled=not confirm_clear):
        clear_all_submissions()
        st.success("All submissions have been deleted.")
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

    if st.button("← Back to Home"):
        st.session_state.page = "home"
        st.rerun()
