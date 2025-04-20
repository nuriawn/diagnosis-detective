import streamlit as st, json, openai, time

st.set_page_config(page_title="Diagnosis Detective", layout="wide")

# ---------------------- API KEY ----------------------
openai.api_key = st.secrets["OPENAI_KEY"]

# ------------------ PROMPT TEMPLATES -----------------
# ASCII‑only to avoid encoding errors

CASE_PROMPT = """
You are a board‑prep item writer. Create ONE adult internal‑medicine case and
RETURN IT AS raw json with this schema:
{
  "stem": "<concise patient H&P>",
  "hidden_data": {
    "gold_dx": "<single best final diagnosis>",
    "gold_tx": "<best initial management>",
    "question_bank": [
      {"q": "<diagnostic step>", "a": "<objective result>"},
      ...
    ],
    "CASE_ID": "<copy seed value>"
  }
}
Rules for question_bank:
- At least 15 items.
- About 30% history/physical and 70% objective tests.
- The first 5 entries must be history/physical.
- Every answer is purely factual. If normal or negative, state a normal value
  (e.g., "D‑dimer 0.2 ug/mL – Normal") or simply "Normal".
- NEVER output phrases like "not provided", "not performed", "N/A".
- No interpretation or management advice.
Always echo the CASE_ID from the provided seed.
Output ONLY the json object.
"""

QUESTION_PICKER = """
You are a teaching attending. Input payload contains:
  • case (json)
  • questions_already_asked (list)
  • current_turn (int starting at 0)
RETURN json exactly: {"next_q": ["q1", "q2", "q3"]}
Guidelines:
- Suggest 3 NEW diagnostic steps not yet asked.
- If current_turn < 2, use ONLY history/physical questions.
- Otherwise maintain a running mix of about 70% objective tests and 30% history.
- Do NOT include questions about treatment or diagnosis.
"""

ANSWER_PROMPT = """
You are the patient's electronic record. Provide the objective result for the
chosen diagnostic step AS IF the test was performed. If normal, state that.
Respond with json: {"answer": "<objective result>"}
"""

DX_TX_CHOICES = """
Using the case json, build TWO shuffled lists (length 3) for diagnosis and
initial treatment. Each list must contain EXACTLY one correct answer.
Return json: {"dx_options": [...], "tx_options": [...]}.
"""

EXPLANATION_PROMPT = """
You are a clinician‑educator. Given the case json, the player's choices, and
correct answers, RETURN json:
{
  "dx_explanation": "<why correct / incorrect>",
  "tx_explanation": "<why correct / incorrect>"
}
Each explanation <= 120 words.
"""

# ----------------- HELPER FUNCTION ------------------

def chat(system_prompt: str, payload: dict) -> dict:
    """Call the OpenAI chat endpoint and return parsed JSON."""
    resp = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload)}
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content)

# -------------- SESSION HELPERS --------------------

def generate_new_case():
    seed = {"seed": time.time()}
    st.session_state.case = chat(CASE_PROMPT, seed)
    st.session_state.turn = 0
    st.session_state.revealed = {}
    st.session_state.final = False
    st.session_state.pop("final_opts", None)

if "case" not in st.session_state:
    generate_new_case()

# -------------- CONSTANTS --------------------------
max_turns = 10

# ------------------- UI HEADER ---------------------
st.title("🩺 Diagnosis Detective")
if st.button("🔄 Start a new case"):
    generate_new_case()
    st.rerun()

case = st.session_state.case
turn = st.session_state.turn

st.markdown("#### Patient vignette")
st.write(case["stem"])

# --------- DISPLAY REVEALED INFORMATION ------------
if st.session_state.revealed:
    st.divider()
    st.markdown("#### Information gathered so far")
    for q, a in st.session_state.revealed.items():
        st.markdown(f"**{q}**")
        st.write(a)

st.divider()

# ---------------- QUESTION PHASE -------------------
if turn < max_turns and not st.session_state.final:
    q_key = f"qset_{turn}"
    if q_key not in st.session_state:
        q_dict = chat(
            QUESTION_PICKER,
            {
                "case": case,
                "questions_already_asked": list(st.session_state.revealed),
                "current_turn": turn,
            },
        )
        st.session_state[q_key] = q_dict["next_q"]

    st.subheader("Choose your next diagnostic step")
    choice = st.radio(
        label="Diagnostic options",
        options=st.session_state[q_key],
        index=None,
        label_visibility="collapsed",
    )

    if choice:
        ans = chat(ANSWER_PROMPT, {"case": case, "ask": choice})
        st.session_state.revealed[choice] = ans["answer"]
        st.session_state.turn += 1
        st.rerun()

    st.progress(turn / max_turns)
    if len(st.session_state.revealed) >= 3 or turn >= max_turns:
        st.button("I’m ready to diagnose", on_click=lambda: st.session_state.update(final=True))

# ----------------- FINAL PHASE ---------------------
if turn >= max_turns or st.session_state.final:
    if "final_opts" not in st.session_state:
        st.session_state.final_opts = chat(DX_TX_CHOICES, case)

    opts = st.session_state.final_opts
    dx = st.radio("Pick the diagnosis", opts["dx_options"], index=None)
    tx = st.radio("Pick the initial treatment", opts["tx_options"], index=None)

    if dx and tx:
        gold = case["hidden_data"]
        score = (
            (50 if dx == gold["gold_dx"] else 0)
            + (30 if tx == gold["gold_tx"] else 0)
            + (max(0, max_turns - turn) * 10)
        )
        st.metric("Your score", score)

        explanations = chat(
            EXPLANATION_PROMPT,
            {
                "case": case,
                "player_dx": dx,
                "player_tx": tx,
                "correct_dx": gold["gold_dx"],
                "correct_tx": gold["gold_tx"],
            },
        )
        st.info(
            f"### Diagnosis rationale\n{explanations['dx_explanation']}\n\n"
            f"### Treatment rationale\n{explanations['tx_explanation']}"
        )
