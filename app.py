import streamlit as st, json, openai, time

st.set_page_config(page_title="Diagnosis Detective", layout="wide")

# ----------------------- API KEY -----------------------
openai.api_key = st.secrets["OPENAI_KEY"]

# ------------------- PROMPT TEMPLATES -------------------
# Every prompt includes the word "json" so we can use response_format="json_object"

CASE_PROMPT = """
You are a board‑prep item writer. Create ONE adult internal‑medicine case and
RETURN IT AS raw **json** with this schema:
{
  "stem": "<concise patient H&P>",
  "hidden_data": {
    "gold_dx": "<single best final diagnosis>",
    "gold_tx": "<best initial management>",
    "question_bank": [
      {"q": "<diagnostic step>", "a": "<objective result>"}, ...
    ]
  }
}
Rules for question_bank:
- ≥ 15 items.
- At least 6 must be objective studies (labs, imaging, ECG, scopes, etc.).
- The rest may be focused history or physical‑exam maneuvers.
- **Every answer must be purely factual** — write it exactly as it would appear
  in a chart or report (e.g., "WBC 15 K/µL, neutrophil‑predominant" or
  "Chest X‑ray: hyperinflated lungs, no focal infiltrate").
- Absolutely **do NOT provide interpretation, likelihood statements, or clues
  about the correct diagnosis** in any answer.
- No items about treatment, management, prognosis, or differential reasoning.
Add a unique CASE_ID field that matches the supplied seed so each request
produces a fresh vignette.
Output the json object only.
"""
You are a board‑prep item writer. Create ONE adult internal‑medicine case and
RETURN IT AS raw **json** with this schema:
{
  "stem": "<concise patient H&P>",
  "hidden_data": {
    "gold_dx": "<single best final diagnosis>",
    "gold_tx": "<best initial management>",
    "question_bank": [
      {"q": "<diagnostic step>", "a": "<truthful answer/result>"}, ...
    ]
  }
}
Rules for question_bank:
- ≥ 15 items.
- ‑‑ AT LEAST 6 must be objective studies (labs, imaging, ECG, endoscopy, etc.).
- Remaining items can be history or focused physical‑exam maneuvers.
- NO items about treatment, management, or differential reasoning.
- Answers for tests should look like realistic reports (e.g., "WBC 15 K, neutrophil‑predominant").
Add a unique CASE_ID field somewhere in the object that matches the supplied seed so every new request yields a brand‑new vignette.
Output the json object only.
"""

QUESTION_PICKER = """
You are a teaching attending. Given the case **json** and the list
questions_already_asked, RETURN **json**:
{"next_q": ["q1", "q2", "q3"]}
Guidelines:
- Provide 3 BRAND‑NEW diagnostic steps not yet asked.
- Try to MIX modalities: include labs or imaging if none asked recently.
- DO NOT include questions about treatment or final diagnosis.
"""

ANSWER_PROMPT = """
You are the patient's electronic record. Return the objective result for the
user's chosen diagnostic step. **Do NOT add interpretation, likelihood, or
clinical commentary.** Respond with **json**:
{"answer": "<objective finding or report>"}
"""
You are the patient's record. Answer the chosen diagnostic step for this case.
Reply with **json**: {"answer": "..."}
"""

DX_TX_CHOICES = """
Using the provided case **json**, build two shuffled multiple‑choice arrays
(each of length 3) and return as **json**:
{"dx_options": ["...", "...", "..."], "tx_options": ["...", "...", "..."]}
Include exactly ONE correct item in each list.
"""

EXPLANATION_PROMPT = """
You are a clinician‑educator. Given the full case **json**, the player's chosen
and the correct diagnosis / treatment, RETURN **json**:
{
  "dx_explanation": "<why the correct diagnosis is correct and the chosen is/was right or wrong>",
  "tx_explanation": "<why the correct initial management is correct and the chosen is/was right or wrong>"
}
Keep explanations to ≤ 120 words each.
"""

# ------------------- HELPER FUNCTION --------------------

def chat(system_prompt: str, payload: dict) -> dict:
    """Wrapper forcing JSON output and returning a dict."""
    r = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload)}
        ],
        temperature=0.3,  # slightly higher for more variety
        response_format={"type": "json_object"}
    )
    return json.loads(r.choices[0].message.content)

# -------------------- NEW‑CASE MAKER --------------------

def generate_new_case():
    """Generate a brand‑new case with a time‑based seed to ensure uniqueness."""
    seed = {"seed": time.time()}
    st.session_state.case = chat(CASE_PROMPT, seed)
    st.session_state.turn = 0
    st.session_state.revealed = {}
    st.session_state.final = False
    st.session_state.pop("final_opts", None)

# ------------------- SESSION INITIALISE -----------------
if "case" not in st.session_state:
    generate_new_case()

case = st.session_state.case
turn = st.session_state.turn
max_turns = 10

# ------------------- HEADER & RESET ---------------------
st.title("🩺 Diagnosis Detective")
if st.button("🔄 Start a new case"):
    generate_new_case()
    st.rerun()

st.markdown("#### Patient vignette")
st.write(case["stem"])

# ------------ DISPLAY INFO GATHERED SO FAR --------------
if st.session_state.revealed:
    st.divider(); st.markdown("#### Information gathered so far")
    for q, a in st.session_state.revealed.items():
        st.markdown(f"**{q}**")
        st.write(a)

st.divider()

# ------------------ QUESTION PHASE ----------------------
if turn < max_turns and not st.session_state.final:
    key = f"qset_{turn}"
    if key not in st.session_state:
        q_dict = chat(QUESTION_PICKER, {"case": case, "questions_already_asked": list(st.session_state.revealed)})
        st.session_state[key] = q_dict["next_q"]

    st.subheader("Choose your next diagnostic step")
    choice = st.radio("Diagnostic options", st.session_state[key], index=None, label_visibility="collapsed")

    if choice:
        ans = chat(ANSWER_PROMPT, {"case": case, "ask": choice})
        st.session_state.revealed[choice] = ans["answer"]
        st.session_state.turn += 1
        st.rerun()

    st.progress(turn / max_turns)
    if len(st.session_state.revealed) >= 3 or turn >= max_turns:
        st.button("I’m ready to diagnose", on_click=lambda: st.session_state.update(final=True))

# ------------------ FINAL PHASE -------------------------
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

        expl = chat(EXPLANATION_PROMPT, {
            "case": case,
            "player_dx": dx, "player_tx": tx,
            "correct_dx": gold["gold_dx"], "correct_tx": gold["gold_tx"]
        })
        st.info(f"### Diagnosis rationale\n{expl['dx_explanation']}\n\n### Treatment rationale\n{expl['tx_explanation']}")
