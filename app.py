import streamlit as st, json, openai, time

st.set_page_config(page_title="Diagnosis Detective", layout="wide")

# ----------------------- API KEY -----------------------
openai.api_key = st.secrets["OPENAI_KEY"]

# ------------------- PROMPT TEMPLATES ------------------
# Use plain ASCII hyphens to avoid Unicode syntax errors.

CASE_PROMPT = """
You are a board-prep item writer. Create ONE adult internal-medicine case and
RETURN IT AS raw json with this schema:
{
  "stem": "<concise patient H&P>",
  "hidden_data": {
    "gold_dx": "<single best final diagnosis>",
    "gold_tx": "<best initial management>",
    "question_bank": [
      {"q": "<diagnostic step>", "a": "<objective result>"}, ...
    ],
    "CASE_ID": "<copy seed value>"
  }
}
Rules for question_bank:
- At least 15 items.
- About 30 % should be focused **history / physical‑exam** inquiries and 70 % **objective tests** (labs, imaging, ECG, scopes, etc.).
- The **first 5** items in the list must be history/physical so early turns favour clinical questioning.
- Every answer must be purely factual, exactly as it would appear in a chart or report.
  *If the finding is normal/negative, explicitly state "Normal" or a typical reference‑range value (e.g., "D‑dimer: 0.2 µg/mL – within normal limits").*
  *Never say "not performed", "N/A", or provide hints about relevance.*
- Do NOT provide interpretation, likelihood statements, or diagnostic clues in any answer.
- No items about treatment, management, prognosis, or differential reasoning.
Always include a unique CASE_ID that matches the supplied seed so each request
produces a fresh vignette. a unique CASE_ID that matches the supplied seed so each request
produces a fresh vignette.
Output the json object only.
"""

QUESTION_PICKER = """
You are a teaching attending. Given the case json and the list
questions_already_asked, RETURN json:
{"next_q": ["q1", "q2", "q3"]}
Guidelines:
- Provide 3 brand‑new diagnostic steps not yet asked.
- **If < 2 turns have elapsed**, favour history/physical questions.
- After that, aim for roughly 70 % objective tests and 30 % history/physical across the remaining turns.
- Do NOT include questions about treatment or final diagnosis.
"""

ANSWER_PROMPT = """
You are the patient's electronic record. Return the objective result for the
user's chosen diagnostic step *as if the test WERE performed*. If the result is
normal/negative, state that plainly. Do NOT add interpretation or commentary.
Respond with json: {"answer": "<objective finding or normal result>"}
"""
You are the patient's electronic record. Return the objective result for the
user's chosen diagnostic step. Do NOT add interpretation, likelihood, or
clinical commentary. Respond with json:
{"answer": "<objective finding or report>"}
"""

DX_TX_CHOICES = """
Using the provided case json, build two arrays (length 3) for diagnosis and
initial treatment. Each list must contain EXACTLY one correct answer plus two
plausible distractors. **Shuffle the order randomly** so the correct answer is
not predictably in the first position, then return as json:
{"dx_options": ["...", "...", "..."], "tx_options": ["...", "...", "..."]}
"""
"""

EXPLANATION_PROMPT = """
You are a clinician‑educator. Given the full case json, the player's chosen and
correct diagnosis/treatment, RETURN json:
{
  "dx_explanation": "<why the correct diagnosis is correct and the chosen is/was right or wrong>",
  "tx_explanation": "<why the correct initial management is correct and the chosen is/was right or wrong>"
}
Keep explanations to 120 words or fewer each.
"""

# ------------------- HELPER FUNCTION -------------------

def chat(system_prompt: str, payload: dict) -> dict:
    """Call OpenAI, force JSON response, and return as dict."""
    resp = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload)}
        ],
        temperature=0.3,
        response_format={"type": "json_object"}
    )
    return json.loads(resp.choices[0].message.content)

# -------------------- NEW CASE MAKER -------------------

def generate_new_case():
    seed = {"seed": time.time()}
    st.session_state.case = chat(CASE_PROMPT, seed)
    st.session_state.turn = 0
    st.session_state.revealed = {}
    st.session_state.final = False
    st.session_state.pop("final_opts", None)

# ----------------- SESSION INITIALISE -----------------
if "case" not in st.session_state:
    generate_new_case()

case = st.session_state.case
turn = st.session_state.turn
max_turns = 10

# ------------------- HEADER & RESET -------------------
st.title("🩺 Diagnosis Detective")
if st.button("🔄 Start a new case"):
    generate_new_case()
    st.rerun()

st.markdown("#### Patient vignette")
st.write(case["stem"])

# ------------- DISPLAY INFO GATHERED SO FAR -----------
if st.session_state.revealed:
    st.divider()
    st.markdown("#### Information gathered so far")
    for q, a in st.session_state.revealed.items():
        st.markdown(f"**{q}**")
        st.write(a)

st.divider()

# ------------------ QUESTION PHASE --------------------
if turn < max_turns and not st.session_state.final:
    q_key = f"qset_{turn}"
    if q_key not in st.session_state:
        q_dict = chat(
            QUESTION_PICKER,
            {"case": case, "questions_already_asked": list(st.session_state.revealed)}
        )
        st.session_state[q_key] = q_dict["next_q"]

    st.subheader("Choose your next diagnostic step")
    choice = st.radio("Diagnostic options", st.session_state[q_key], index=None, label_visibility="collapsed")

    if choice:
        ans = chat(ANSWER_PROMPT, {"case": case, "ask": choice})
        st.session_state.revealed[choice] = ans["answer"]
        st.session_state.turn += 1
        st.rerun()

    st.progress(turn / max_turns)
    if len(st.session_state.revealed) >= 3 or turn >= max_turns:
        st.button("I’m ready to diagnose", on_click=lambda: st.session_state.update(final=True))

# ------------------ FINAL PHASE -----------------------
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

        explanations = chat(
            EXPLANATION_PROMPT,
            {
                "case": case,
                "player_dx": dx,
                "player_tx": tx,
                "correct_dx": gold["gold_dx"],
                "correct_tx": gold["gold_tx"]
            }
        )
        st.info(
            f"### Diagnosis rationale\n{explanations['dx_explanation']}\n\n"
            f"### Treatment rationale\n{explanations['tx_explanation']}"
        )
