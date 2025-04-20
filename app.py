# -------------- app.py --------------
import streamlit as st, openai, json

st.set_page_config(page_title="Diagnosis Detective", layout="wide")
openai.api_key = st.secrets["OPENAI_KEY"]

# ---------- PROMPT TEMPLATES ----------
CASE_PROMPT = """
Act as a board-prep item writer. Create ONE adult internal-medicine
case. Return JSON with:
 "stem": <concise history & physical>,
 "hidden_data": {
   "gold_dx": <best final diagnosis>,
   "gold_tx": <best initial management>,
   "question_bank": [
     {"q": "...", "a": "..."},
     ...
   ]
 }
Rules:
- Provide at least 12 Q/A pairs (labs, imaging, history probes, etc.).
- Answers must be truthful and match the case.
"""
QUESTION_PICKER = """
You are a teaching attending. Given:
 ● full case JSON
 ● questions_already_asked
Return THREE next-best questions for the learner now:
{"next_q": ["...", "...", "..."]}
"""
ANSWER_PROMPT = """
Respond truthfully to the chosen question for this patient.
Return JSON:
{"answer": "...", "updated_case": {...}}
"""
DX_TX_CHOICES = """
Given full case JSON, create:
 {"dx_options": ["...", "...", "..."],
  "tx_options": ["...", "...", "..."]}
Include the correct answer once in each list and shuffle order.
"""

# ---------- HELPER ----------
def chat(system_prompt, user_payload):
    msg = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload)}
    ]
    return openai.ChatCompletion.create(
        model="gpt-4o-mini", messages=msg, temperature=0.2
    ).choices[0].message.content

# ---------- SESSION SET‑UP ----------
if "case" not in st.session_state:
    raw = chat(CASE_PROMPT, {})
    st.session_state.case = json.loads(raw)
    st.session_state.turn = 0
    st.session_state.revealed = {}

case = st.session_state.case
turn = st.session_state.turn
max_turns = 6

st.title("🩺 Diagnosis Detective")

# ---------- QUESTION PHASE ----------
if turn < max_turns and "final" not in st.session_state:
    # pick / cache question set
    key = f"qset_{turn}"
    if key not in st.session_state:
        q_raw = chat(
            QUESTION_PICKER,
            {"case": case, "already": list(st.session_state.revealed)}
        )
        st.session_state[key] = json.loads(q_raw)["next_q"]

    st.subheader("Choose your next question")
    choice = st.radio("", st.session_state[key], index=None)

    if choice:
        ans_raw = chat(ANSWER_PROMPT, {"case": case, "ask": choice})
        ans_json = json.loads(ans_raw)
        st.success(ans_json["answer"])
        st.session_state.case = ans_json["updated_case"]
        st.session_state.revealed[choice] = ans_json["answer"]
        st.session_state.turn += 1
        st.experimental_rerun()

    st.progress(turn / max_turns)
    st.button("I’m ready to diagnose", on_click=lambda: st.session_state.update(final=True))

# ---------- FINAL CHOICES ----------
if turn >= max_turns or st.session_state.get("final"):
    if "final_opts" not in st.session_state:
        opts_raw = chat(DX_TX_CHOICES, st.session_state.case)
        st.session_state.final_opts = json.loads(opts_raw)

    opts = st.session_state.final_opts
    dx = st.radio("Pick the diagnosis", opts["dx_options"], index=None)
    tx = st.radio("Pick the initial treatment", opts["tx_options"], index=None)

    if dx and tx:
        gold = st.session_state.case["hidden_data"]
        score = (
            (50 if dx == gold["gold_dx"] else 0)
            + (30 if tx == gold["gold_tx"] else 0)
            + (max(0, max_turns - turn) * 10)
        )
        st.metric("Your score", score)
        st.info(f"Correct Dx: **{gold['gold_dx']}**\n\nCorrect Tx: **{gold['gold_tx']}**")
