import streamlit as st, json, openai

st.set_page_config(page_title="Diagnosis Detective", layout="wide")

# Use the API key you stored in Streamlit secrets
openai.api_key = st.secrets["OPENAI_KEY"]

# ───────────────────────────────────── PROMPT TEMPLATES ──────────────────────────────────────
CASE_PROMPT = """
Act as a board‑prep item writer. Create ONE adult internal‑medicine case.
Return JSON with:
  "stem": <concise patient history & physical>,
  "hidden_data": {
    "gold_dx": <single gold‑standard final diagnosis>,
    "gold_tx": <best initial management>,
    "question_bank": [
      {"q": "...", "a": "..."},
      ...
    ]
  }
Rules:
- Provide at least 15 Q/A pairs. Each **q** MUST be a diagnostic inquiry or test order (history detail, physical‑exam maneuver, lab, imaging, etc.).
- EXCLUDE any questions about differential reasoning, likely cause, prognosis, or treatment decisions.
- Make sure every answer is consistent with the case and reveals new, helpful information.
- Output **only** the JSON object, without markdown or commentary.
"""

QUESTION_PICKER = """
You are a teaching attending. Given:
  • full case JSON
  • questions_already_asked
Return THREE next‑best diagnostic questions/exams that have NOT been asked yet.
Guidelines:
- Each question must gather **new** data (history, physical, lab, imaging).
- Do NOT propose questions about management, treatment, or diagnosis.
- Respond with: {"next_q": ["q1", "q2", "q3"]}
"""

ANSWER_PROMPT = """
You are the patient's record. Give the truthful answer to the chosen question for this case.
Then return the updated case JSON with this Q/A added (e.g., into a `revealed` dict).
Respond with **only**:
{"answer": "...", "updated_case": {...}}
"""

DX_TX_CHOICES = """
Given the full case JSON, create shuffled multiple‑choice lists for diagnosis and treatment.
Return exactly this structure:
{"dx_options": ["...", "...", "..."], "tx_options": ["...", "...", "..."]}
Include **one** correct answer in each list.
"""

# ────────────────────────────────────── HELPER FUNCTION ──────────────────────────────────────

def chat(system_prompt: str, user_payload: dict) -> str:
    """Utility wrapper around the v1+ OpenAI client that forces JSON output."""
    response = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload)}
        ],
        temperature=0.2,
        # Guarantees syntactically valid JSON in the reply
        response_format={"type": "json_object"}
    )
    return response.choices[0].message.content

# ────────────────────────────────────── SESSION STATE SETUP ───────────────────────────────────
if "case" not in st.session_state:
    raw_case = chat(CASE_PROMPT, {})
    st.session_state.case = json.loads(raw_case)
    st.session_state.turn = 0
    st.session_state.revealed = {}   # {question: answer}
    st.session_state.final = False

case = st.session_state.case
turn = st.session_state.turn
max_turns = 10   # up to 10 diagnostic steps

# ─────────────────────────────────────────── UI HEADER ─────────────────────────────────────────
st.title("🩺 Diagnosis Detective")

st.markdown("#### Patient vignette")
st.write(case["stem"])
st.divider()

# ─────────────────────────────────────── QUESTION PHASE ───────────────────────────────────────
if turn < max_turns and not st.session_state.final:
    key = f"qset_{turn}"

    # Fetch or cache the next trio of diagnostic questions
    if key not in st.session_state:
        qset_raw = chat(
            QUESTION_PICKER,
            {"case": case, "questions_already_asked": list(st.session_state.revealed)}
        )
        st.session_state[key] = json.loads(qset_raw)["next_q"]

    st.subheader("Choose your next question / exam")
    choice = st.radio(
        label="Diagnostic options",
        options=st.session_state[key],
        index=None,
        label_visibility="collapsed"
    )

    if choice:
        # Get the answer & updated case
        ans_raw = chat(ANSWER_PROMPT, {"case": case, "ask": choice})
        ans_json = json.loads(ans_raw)

        st.success(ans_json["answer"])

        # Update session state
        st.session_state.case = ans_json["updated_case"]
        st.session_state.revealed[choice] = ans_json["answer"]
        st.session_state.turn += 1
        st.rerun()

    # Progress bar
    st.progress(turn / max_turns)

    # Show diagnose button after ≥3 answers or when turn cap hit
    if len(st.session_state.revealed) >= 3 or turn >= max_turns:
        st.button(
            "I’m ready to diagnose",
            on_click=lambda: st.session_state.update(final=True)
        )

# ─────────────────────────────────────── FINAL PHASE ──────────────────────────────────────────
if turn >= max_turns or st.session_state.final:
    if "final_opts" not in st.session_state:
        opts_raw = chat(DX_TX_CHOICES, st.session_state.case)
        st.session_state.final_opts = json.loads(opts_raw)

    opts = st.session_state.final_opts

    dx = st.radio("Pick the diagnosis", opts["dx_options"], index=None)
    tx = st.radio("Pick the initial treatment", opts["tx_options"], index=None)

    if dx and tx:
        gold_dx = case["hidden_data"]["gold_dx"]
        gold_tx = case["hidden_data"]["gold_tx"]

        score = (
            (50 if dx == gold_dx else 0) +
            (30 if tx == gold_tx else 0) +
            (max(0, max_turns - turn) * 10)
        )

        st.metric("Your score", score)
        st.info(f"Correct Dx: **{gold_dx}**\n\nCorrect Tx: **{gold_tx}**")
