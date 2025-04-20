import streamlit as st, json, openai

st.set_page_config(page_title="Diagnosis Detective", layout="wide")

# OpenAI key comes from Streamlit → Secrets
openai.api_key = st.secrets["OPENAI_KEY"]

# ───────────────────────────────────── PROMPT TEMPLATES ─────────────────────────────────────
CASE_PROMPT = """
Act as a board‑prep item writer. Create ONE adult internal‑medicine case.
Return JSON with:
  "stem": <concise patient history & physical>,
  "hidden_data": {
    "gold_dx": <single gold‑standard final diagnosis>,
    "gold_tx": <best initial management>,
    "question_bank": [
      {"q": "...", "a": "..."}, ...
    ]
  }
Rules:
- Provide at least 15 Q/A pairs. Each **q** MUST be a diagnostic inquiry or test order (history detail, physical exam, lab, imaging, etc.).
- EXCLUDE any question about differential reasoning, likely cause, prognosis, or treatment.
- Output ONLY the JSON object.
"""

QUESTION_PICKER = """
You are a teaching attending. Given:
  • full case JSON
  • questions_already_asked
Return THREE next‑best diagnostic questions/exams that have NOT been asked yet.
Respond with {"next_q": ["q1", "q2", "q3"]} only.
"""

ANSWER_PROMPT = """
Provide the truthful answer to the chosen diagnostic question for this patient.
Return only: {"answer": "..."}
"""

DX_TX_CHOICES = """
Given the full case JSON, create shuffled multiple‑choice lists for diagnosis and treatment.
Return exactly: {"dx_options": [...], "tx_options": [...]} with ONE correct answer in each list.
"""

# ───────────────────────────────────── HELPER ───────────────────────────────────────────────

def chat(system_prompt: str, payload: dict) -> str:
    """Call the OpenAI chat endpoint and force JSON output."""
    resp = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload)}
        ],
        temperature=0.2,
        response_format={"type": "json_object"}
    )
    return resp.choices[0].message.content

# ───────────────────────────────────── SESSION INIT ─────────────────────────────────────────
if "case" not in st.session_state:
    st.session_state.case = json.loads(chat(CASE_PROMPT, {}))
    st.session_state.turn = 0
    st.session_state.revealed = {}  # {question: answer}
    st.session_state.final = False

case = st.session_state.case
turn = st.session_state.turn
max_turns = 10

# ───────────────────────────────────── HEADER & RESET BTN ───────────────────────────────────
st.title("🩺 Diagnosis Detective")

if st.button("🔄 Start a new case"):
    for k in ("case", "turn", "revealed", "final", "final_opts"):
        st.session_state.pop(k, None)
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
    if key not in st.session_state:
        q_raw = chat(QUESTION_PICKER, {"case": case, "questions_already_asked": list(st.session_state.revealed)})
        st.session_state[key] = json.loads(q_raw)["next_q"]

    st.subheader("Choose your next diagnostic step")
    choice = st.radio("Diagnostic options", st.session_state[key], index=None, label_visibility="collapsed")

    if choice:
        ans_raw = chat(ANSWER_PROMPT, {"case": case, "ask": choice})
        ans_json = json.loads(ans_raw)
        st.session_state.revealed[choice] = ans_json["answer"]
        st.session_state.turn += 1
        st.rerun()

    st.progress(turn / max_turns)

    if len(st.session_state.revealed) >= 3 or turn >= max_turns:
        st.button("I’m ready to diagnose", on_click=lambda: st.session_state.update(final=True))

# ───────────────────────────────────── FINAL PHASE ──────────────────────────────────────────
if turn >= max_turns or st.session_state.final:
    if "final_opts" not in st.session_state:
        st.session_state.final_opts = json.loads(chat(DX_TX_CHOICES, case))

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
