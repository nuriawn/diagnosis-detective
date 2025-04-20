import streamlit as st, json, openai, time

st.set_page_config(page_title="Diagnosis Detective", layout="wide")

# ---------------------- API KEY ----------------------
openai.api_key = st.secrets.get("OPENAI_KEY", "")

# ------------------ PROMPT TEMPLATES -----------------
# NOTE: Plain ASCII only – no fancy bullets or non‑breaking hyphens

CASE_PROMPT = """
You are a board‑prep item writer. Create ONE adult case and return it as raw
JSON (schema below). Repeated calls must cycle through *different* disease
categories. The payload includes an array called prev_diagnoses with diagnoses
used earlier in the session – do NOT pick any diagnosis already in that list.

Target distribution (approx.):
- 25% Cardiovascular / Respiratory (AMI, COPD, asthma, PE, etc.)
- 20% Infectious diseases (CAP, meningitis, sepsis, plus at least one tropical
  illness such as malaria, dengue, typhoid, schistosomiasis, or Chagas)
- 15% Endocrine / Metabolic (DKA, thyroid storm, adrenal crisis)
- 10% Oncology / Hematology (acute leukemia, colon cancer, lung cancer,
  lymphoma, paraneoplastic syndromes)
- 10% Neurologic / Psychiatric (stroke, meningitis, panic attack, etc.)
- 10% Gastro‑Hepato (GI bleed, pancreatitis, viral hepatitis)
- 10% Renal / Rheum / Misc. (AKI, lupus flare, sickle crisis, etc.)

Return JSON exactly:
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

Other rules:
- At least 15 diagnostic steps (~30% history/physical, 70% objective tests).
- Answers are purely factual; give normal values for negative results; never
  write "not provided", "not performed", or similar.
- Do NOT add interpretation or management hints.
- Echo CASE_ID from payload.
Output ONLY the JSON object – no markdown.
"""

QUESTION_PICKER = """
You are a teaching attending. Payload contains:
  - case (the JSON case)
  - questions_already_asked (list)
  - current_turn (int starting at 0)
Return JSON exactly: {"next_q": ["q1", "q2", "q3"]}
Guidelines:
- Suggest 3 NEW diagnostic steps not yet asked.
- Each trio must include at least TWO objective tests (lab, imaging, POC study, etc.).
- Maintain an overall 70% objective tests / 30% history‑physical mix throughout the game.
- Do NOT include treatment or diagnosis questions.
"""

ANSWER_PROMPT = """
You are the patient's electronic record. Provide the objective result for the
chosen diagnostic step *as if the test was performed*. If normal, state that.
Respond with JSON: {"answer": "<objective result>"}
"""

DX_TX_CHOICES = """
Using the case JSON, build TWO shuffled lists (length 3) – one for diagnosis,
one for initial treatment. Each list must contain EXACTLY one correct answer.
Return JSON: {"dx_options": [...], "tx_options": [...]}.
"""

EXPLANATION_PROMPT = """
You are a clinician‑educator. Given the case JSON, the player's picks, and the
correct answers, return JSON:
{
  "dx_explanation": "<brief rationale>",
  "tx_explanation": "<brief rationale>"
}
Each explanation <= 120 words.
"""

# ----------------- HELPER FUNCTION -----------------

def chat(system_prompt: str, payload: dict) -> dict:
    """Call OpenAI chat endpoint and parse JSON response."""
    response = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload)}
        ],
        temperature=0.3,
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)

# -------------- SESSION HELPERS -------------------

def generate_new_case():
    prev_dx = st.session_state.get("prev_diagnoses", [])
    seed_payload = {"seed": time.time(), "prev_diagnoses": prev_dx}
    new_case = chat(CASE_PROMPT, seed_payload)
    # store
    st.session_state.case = new_case
    prev_dx.append(new_case["hidden_data"]["gold_dx"])
    st.session_state.prev_diagnoses = prev_dx[-10:]  # keep last 10 distinct diagnoses
    st.session_state.turn = 0
    st.session_state.revealed = {}
    st.session_state.final = False
    st.session_state.pop("final_opts", None)

if "case" not in st.session_state:
    generate_new_case()

MAX_TURNS = 10

# ------------------- UI HEADER --------------------
st.title("🩺 Diagnosis Detective")
if st.button("🔄 Start a new case"):
    generate_new_case()
    st.rerun()

case = st.session_state.case
turn = st.session_state.turn

st.markdown("#### Patient vignette")
st.write(case["stem"])

# -------- DISPLAY REVEALED INFORMATION ------------
if st.session_state.revealed:
    st.divider()
    st.markdown("#### Information gathered so far")
    for q, a in st.session_state.revealed.items():
        st.markdown(f"**{q}**")
        st.write(a)

st.divider()

# ---------------- QUESTION PHASE ------------------
if turn < MAX_TURNS and not st.session_state.final:
    q_key = f"qset_{turn}"
    if q_key not in st.session_state:
        picker_payload = {
            "case": case,
            "questions_already_asked": list(st.session_state.revealed),
            "current_turn": turn,
        }
        q_dict = chat(QUESTION_PICKER, picker_payload)
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

    st.progress(turn / MAX_TURNS)
    if len(st.session_state.revealed) >= 3 or turn >= MAX_TURNS:
        st.button("I’m ready to diagnose", on_click=lambda: st.session_state.update(final=True))

# ----------------- FINAL PHASE --------------------
if turn >= MAX_TURNS or st.session_state.final:
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
            + (max(0, MAX_TURNS - turn) * 10)
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
