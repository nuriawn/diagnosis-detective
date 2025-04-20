import streamlit as st, json, openai

st.set_page_config(page_title="Diagnosis Detective", layout="wide")

# OpenAI key comes from Streamlit → Secrets
openai.api_key = st.secrets["OPENAI_KEY"]

# ───────────────────────────────────── PROMPT TEMPLATES ─────────────────────────────────────
# (All prompts intentionally include the lowercase word "json" so the
#  response_format={"type": "json_object"} requirement is satisfied.)

CASE_PROMPT = """
You are a board‑prep item writer. Create ONE adult internal‑medicine case and
return it as a **json** object with this structure:
{
  "stem": "<concise patient history & physical>",
  "hidden_data": {
    "gold_dx": "<gold‑standard final diagnosis>",
    "gold_tx": "<best initial management>",
    "question_bank": [
       {"q": "<diagnostic question>", "a": "<truthful answer>"},
       ... (≥ 15 items) ...
    ]
  }
}
Rules:
- Every question in question_bank MUST be a diagnostic inquiry or test order
  (history detail, physical‑exam manoeuvre, lab, imaging, etc.).
- EXCLUDE any question about management, treatment, or differential reasoning.
- Do not wrap the object in markdown; output the raw json only.
"""

QUESTION_PICKER = """
You are a teaching attending. Given a case stored as a **json** object and a
list of questions_already_asked, reply with another json object:
{"next_q": ["q1", "q2", "q3"]}
where each q is a NEW diagnostic question or test that has not been asked yet.
Do not propose items about treatment or diagnosis.
"""

ANSWER_PROMPT = """
You are the patient's record. Answer the user's chosen diagnostic question for
this case. Reply with exactly this **json** shape: {"answer": "..."}
No additional keys.
"""

DX_TX_CHOICES = """
Create two shuffled multiple‑choice lists (three options each) for diagnosis
and treatment, based on the provided case **json**. Respond with a json object:
{"dx_options": ["...", "...", "..."], "tx_options": ["...", "...", "..."]}
Include exactly ONE correct entry in each list.
"""

# ───────────────────────────────────── HELPER ───────────────────────────────────────────────

def chat(system_prompt: str, payload: dict) -> dict:
    """Call OpenAI chat with forced‑JSON output and return the parsed object."""
    resp = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload)}
        ],
        temperature=0.2,
        response_format={"type": "json_object"}
    )
    return json.loads(resp.choices[0].message.content)

# ───────────────────────────────────── SESSION INIT ─────────────────────────────────────────
if "case" not in st.session_state:
    st.session_state.case = chat(CASE_PROMPT, {})
    st.session_state.turn = 0
    st.session_state.revealed = {}  # {question: answer}
    st.session_state.final = False

case = st.session_state.case
turn = st.session_state.turn
max_turns = 10

# ───────────────────────────────────── HEADER & RESET BTN ───────────────────────────────────
st.title("🩺 Diagnosis Detective")

if st.button("🔄 Start a new case"):
    st.session_state.clear()
    st.rerun()

st.markdown("#### Patient vignette")
st.write(case["stem"])

# Display gathered info so far
if st.session_state.revealed:
    st.divider()
    st.markdown("#### Information gathered so far")
    for q, a in st.session_state.revealed.items():
        st.markdown(f"**{q}**")
        st.write(a)

st.divider()

# ───────────────────────────────────── QUESTION PHASE ───────────────────────────────────────
if turn < max_turns and not st.session_state.final:
    key = f"qset_{turn}"

    # Fetch or cache next trio of diagnostic questions
    if key not in st.session_state:
        q_data = chat(
            QUESTION_PICKER,
            {"case": case, "questions_already_asked": list(st.session_state.revealed)}
        )
        st.session_state[key] = q_data["next_q"]

    st.subheader("Choose your next diagnostic step")
    choice = st.radio(
        label="Diagnostic options", options=st.session_state[key], index=None,
        label_visibility="collapsed"
    )

    if choice:
        answer_obj = chat(ANSWER_PROMPT, {"case": case, "ask": choice})
        st.session_state.revealed[choice] = answer_obj["answer"]
        st.session_state.turn += 1
        st.rerun()

    st.progress(turn / max_turns)

    if len(st.session_state.revealed) >= 3 or turn >= max_turns:
        st.button("I’m ready to diagnose", on_click=lambda: st.session_state.update(final=True))

# ───────────────────────────────────── FINAL PHASE ──────────────────────────────────────────
if turn >= max_turns or st.session_state.final:
    if "final_opts" not in st.session_state:
        st.session_state.final_opts = chat(DX_TX_CHOICES, case)

    opts = st.session_state.final_opts
    dx = st.radio("Pick the diagnosis", opts["dx_options"], index=None)
    tx = st.radio("Pick the initial treatment", opts["tx_options"], index=None)

    if dx and tx:
        gold = case["hidden_data"]
        score = (
            (50 if dx == gold["gold_dx"] else 0) +
            (30 if tx == gold["gold_tx"] else 0) +
            (max(0, max_turns - turn) * 10)
        )
        st.metric("Your score", score)
        st.info(f"Correct Dx: **{gold['gold_dx']}**\n\nCorrect Tx: **{gold['gold_tx']}**")
