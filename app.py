from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st


ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "progress.db"
PLAN_PATH = DATA_DIR / "workout_plan.json"
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

def exercise(
    name: str,
    sets: int,
    reps: str,
    alternatives: list[str],
    notes: str = "Use controlled technique and finish with about 3 repetitions in reserve.",
) -> dict:
    return {
        "name": name,
        "sets": sets,
        "reps": reps,
        "alternatives": alternatives,
        "notes": notes,
        "source": "PDF",
    }


STARTER_PLAN = {
    "Monday": [
        exercise("Machine chest press", 2, "8–12", ["Dumbbell bench press", "Smith-machine bench press"]),
        exercise("Lat pulldown", 2, "8–12", ["Assisted pull-up", "Neutral-grip lat pulldown"]),
        exercise(
            "Seated cable row", 2, "8–12",
            ["Chest-supported machine row", "One-arm cable row"],
            "Keep the torso stable and pull under control.",
        ),
        exercise(
            "Machine shoulder press (neutral grip)", 2, "8–12",
            ["Dumbbell shoulder press (neutral grip)", "Landmine press"],
            "Neutral grip is the default. Keep elbows slightly forward and your back and "
            "head on the pad. Do not lower excessively deep or continue through pinching.",
        ),
        exercise("Cable triceps pushdown", 2, "10–15", ["Machine triceps extension", "Resistance-band pushdown"]),
        exercise("Machine or dumbbell curl", 2, "10–15", ["Cable curl", "Hammer curl"]),
    ],
    "Tuesday": [
        exercise(
            "Leg press", 2, "10–15", ["Box squat", "Supported goblet squat"],
            "Use a comfortable depth. Do not force the knees toward the chest if the lower back rounds.",
        ),
        exercise("Seated leg curl", 2, "10–15", ["Lying leg curl", "Standing machine leg curl"]),
        exercise("Leg extension", 2, "10–15", ["Supported low step-up", "Spanish squat"]),
        exercise("Machine hip thrust or glute bridge", 2, "10–15", ["Cable pull-through", "Bodyweight glute bridge"]),
        exercise("Seated calf raise", 2, "12–20", ["Standing calf raise", "Calf press on leg press"]),
        exercise("Pallof press", 2, "10–12 per side", ["Dead bug", "Machine crunch"]),
    ],
    "Wednesday": [
        exercise("Incline machine chest press", 2, "8–12", ["Incline dumbbell press", "Incline Smith-machine press"]),
        exercise(
            "Pec deck fly", 2, "10–15", ["Cable chest fly", "Dumbbell chest fly"],
            "Keep your back and head on the pad and a slight elbow bend. Move slowly; "
            "do not let the arms travel excessively behind the body.",
        ),
        exercise(
            "Machine shoulder press (neutral grip)", 2, "8–12",
            ["Dumbbell shoulder press (neutral grip)", "Landmine press"],
            "Keep elbows slightly forward, back and head on the pad, and stop before the shoulders roll forward.",
        ),
        exercise("Cable lateral raise", 2, "12–15", ["Machine lateral raise", "Dumbbell lateral raise"]),
        exercise("Cable triceps pushdown", 2, "10–15", ["Machine triceps extension", "Resistance-band pushdown"]),
        exercise("Overhead cable triceps extension", 2, "10–15", ["Single-arm cable extension", "Dumbbell overhead extension"]),
    ],
    "Thursday": [
        exercise("Neutral-grip lat pulldown", 2, "8–12", ["Assisted neutral-grip pull-up", "Regular lat pulldown"]),
        exercise(
            "Chest-supported machine row", 2, "8–12",
            ["Chest-supported dumbbell row", "Seated cable row"],
            "Chest support is preferred initially because it reduces demand on the lower back.",
        ),
        exercise("One-arm cable row", 2, "10–12 per side", ["One-arm machine row", "Chest-supported dumbbell row"]),
        exercise("Reverse pec deck", 2, "12–15", ["Cable rear-delt fly", "Face pull"]),
        exercise("Cable or machine curl", 2, "10–15", ["Dumbbell curl", "Preacher curl"]),
        exercise("Hammer curl", 2, "10–15", ["Rope cable hammer curl", "Machine curl"]),
    ],
    "Friday": [
        exercise(
            "Leg press", 2, "10–15", ["Box squat", "Supported goblet squat"],
            "Use a comfortable depth and keep the lower back from rounding.",
        ),
        exercise("Seated or lying leg curl", 2, "10–15", ["Standing machine leg curl", "Stability-ball leg curl"]),
        exercise(
            "Supported split squat or low step-up", 2, "8–10 per leg",
            ["Leg extension", "Supported reverse lunge"],
            "Hold a fixed support. Use leg extensions if knee discomfort, poor balance, "
            "or excessive fatigue makes the movement difficult.",
        ),
        exercise("Machine hip thrust", 2, "10–15", ["Glute bridge", "Cable pull-through"]),
        exercise("Seated calf raise", 2, "12–20", ["Standing calf raise", "Calf press on leg press"]),
        exercise("Machine crunch or dead bug", 2, "10–15", ["Pallof press", "Cable crunch"]),
    ],
}


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS workout_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            performed_on TEXT NOT NULL,
            day_name TEXT NOT NULL,
            planned_exercise TEXT NOT NULL,
            performed_exercise TEXT NOT NULL,
            sets INTEGER NOT NULL,
            reps TEXT NOT NULL,
            weight REAL,
            rir INTEGER,
            pain INTEGER,
            notes TEXT,
            set_number INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        )
        """
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(workout_log)")}
    if "set_number" not in columns:
        connection.execute("ALTER TABLE workout_log ADD COLUMN set_number INTEGER DEFAULT 1")
    connection.commit()
    return connection


def load_plan() -> dict[str, list[dict]]:
    DATA_DIR.mkdir(exist_ok=True)
    if not PLAN_PATH.exists():
        PLAN_PATH.write_text(json.dumps(STARTER_PLAN, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        saved = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        saved = STARTER_PLAN
    return {day: saved.get(day, []) for day in DAYS}


def save_plan(plan: dict[str, list[dict]]) -> None:
    PLAN_PATH.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")


def read_log(connection: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT * FROM workout_log ORDER BY performed_on DESC, id DESC", connection
    )


def exercise_label(item: dict) -> str:
    return f"{item['name']} · {item['sets']} × {item['reps']}"


st.set_page_config(page_title="My Training Path", page_icon="🏋️", layout="wide")
st.markdown(
    """
    <style>
      .block-container {max-width: 1120px; padding-top: 2rem;}
      [data-testid="stMetric"] {
        background: linear-gradient(135deg, #16231d, #21382d);
        border: 1px solid #365846; border-radius: 16px; padding: 14px;
      }
      div[data-testid="stExpander"] {border-radius: 14px; border-color: #3a5145;}
      .eyebrow {letter-spacing:.12em; text-transform:uppercase; color:#80d4a6;
                font-size:.78rem; font-weight:700;}
      .muted {color:#9eaaa4;}
    </style>
    """,
    unsafe_allow_html=True,
)

plan = load_plan()
db = connect()

st.markdown('<p class="eyebrow">Personal training companion</p>', unsafe_allow_html=True)
st.title("My Training Path")
st.caption("Know what to do today, swap an exercise when needed, and keep a useful record of your progress.")

today_name = datetime.now().strftime("%A")
default_day = DAYS.index(today_name) if today_name in DAYS else 0

tab_today, tab_plan, tab_progress = st.tabs(["Today", "My plan", "Progress"])

with tab_today:
    selected_day = st.segmented_control(
        "Training day", DAYS, default=DAYS[default_day], selection_mode="single"
    )
    exercises = plan.get(selected_day, [])

    with st.expander("How hard should I train?"):
        st.markdown(
            """
            - Finish each set with about **3 repetitions still possible**; do not train
              to failure during the first two months.
            - Rest **90–120 seconds** after compound movements and **60–90 seconds**
              after curls, triceps, calves, and abdominal work.
            - During the first two weeks, one working set per exercise is acceptable
              when soreness or fatigue is high.
            - When you reach the top of the rep range on both sets with good form,
              increase the weight by the smallest available amount.
            - Add **10–20 minutes of low-impact cardio** after weights on 3–4 days:
              recumbent or stationary bike, elliptical if comfortable, or flat
              treadmill walking.
            """
        )

    if not exercises:
        st.info(f"No exercises are set for {selected_day}. Add them in **My plan**.")
    else:
        st.subheader(f"{selected_day}'s workout")
        st.caption(f"{len(exercises)} exercises · Log each movement after you finish it.")

        for index, item in enumerate(exercises):
            with st.container(border=True):
                left, right = st.columns([3, 1])
                left.markdown(f"#### {index + 1}. {item['name']}")
                right.markdown(f"### {item['sets']} × {item['reps']}")
                if item.get("source") == "PDF":
                    st.caption("From your ChatGPT conversation PDF")
                st.write(item.get("notes", ""))

                alternatives = item.get("alternatives", [])
                choices = [item["name"], *alternatives]
                with st.expander("Alternatives & workout log"):
                    performed = st.selectbox(
                        "Exercise performed",
                        choices,
                        key=f"performed_{selected_day}_{index}",
                        help="Choose the planned movement or an alternative.",
                    )
                    with st.form(f"log_{selected_day}_{index}", clear_on_submit=True):
                        log_date = st.date_input(
                            "Date", date.today(), key=f"date_{selected_day}_{index}"
                        )
                        st.markdown("**Sets performed**")
                        set_values = []
                        for set_number in range(1, int(item["sets"]) + 1):
                            set_col, reps_col, weight_col = st.columns([1, 2, 2])
                            set_col.markdown(f"Set **{set_number}**")
                            set_reps = reps_col.number_input(
                                f"Set {set_number} reps",
                                min_value=0,
                                max_value=100,
                                value=0,
                                key=f"reps_{selected_day}_{index}_{set_number}",
                            )
                            set_weight = weight_col.number_input(
                                f"Set {set_number} weight (kg)",
                                min_value=0.0,
                                max_value=1000.0,
                                value=0.0,
                                step=0.5,
                                key=f"weight_{selected_day}_{index}_{set_number}",
                            )
                            set_values.append((set_number, set_reps, set_weight))

                        c1, c2 = st.columns(2)
                        rir = c1.select_slider(
                            "Reps in reserve", options=list(range(0, 6)), value=2,
                            key=f"rir_{selected_day}_{index}",
                        )
                        pain = c2.select_slider(
                            "Pain / discomfort", options=list(range(0, 11)), value=0,
                            key=f"pain_{selected_day}_{index}",
                        )
                        log_notes = st.text_area(
                            "Session notes", placeholder="Form, energy, machine settings…",
                            key=f"notes_{selected_day}_{index}",
                        )
                        submitted = st.form_submit_button("Save to progress", type="primary")
                        if submitted:
                            completed = [values for values in set_values if values[1] > 0]
                            if not completed:
                                st.error("Enter the repetitions for at least one set.")
                            else:
                                logged_at = datetime.now().isoformat(timespec="microseconds")
                                db.executemany(
                                    """
                                    INSERT INTO workout_log (
                                        performed_on, day_name, planned_exercise,
                                        performed_exercise, sets, reps, weight, rir,
                                        pain, notes, set_number, created_at
                                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    """,
                                    [
                                        (
                                            log_date.isoformat(), selected_day, item["name"],
                                            performed, 1, str(set_reps), set_weight, rir, pain,
                                            log_notes.strip(), set_number, logged_at,
                                        )
                                        for set_number, set_reps, set_weight in completed
                                    ],
                                )
                                db.commit()
                                st.success(f"{len(completed)} sets saved.")

with tab_plan:
    st.subheader("Build your Monday–Friday plan")
    st.caption(
        "The starter schedule follows the full routine in your updated PDF. "
        "You can still add, edit, or remove any exercise."
    )
    edit_day = st.selectbox("Day to edit", DAYS)

    for index, item in enumerate(plan[edit_day]):
        with st.expander(exercise_label(item), expanded=False):
            with st.form(f"edit_{edit_day}_{index}"):
                name = st.text_input("Exercise", item["name"])
                c1, c2 = st.columns(2)
                sets = c1.number_input("Sets", 1, 20, int(item["sets"]))
                reps = c2.text_input("Rep target", str(item["reps"]))
                alternatives = st.text_area(
                    "Alternatives (one per line)", "\n".join(item.get("alternatives", []))
                )
                notes = st.text_area("Form cues / notes", item.get("notes", ""))
                save_col, delete_col = st.columns(2)
                save = save_col.form_submit_button("Save changes", type="primary")
                delete = delete_col.form_submit_button("Remove exercise")
                if save:
                    plan[edit_day][index] = {
                        **item,
                        "name": name.strip(),
                        "sets": sets,
                        "reps": reps.strip(),
                        "alternatives": [x.strip() for x in alternatives.splitlines() if x.strip()],
                        "notes": notes.strip(),
                    }
                    save_plan(plan)
                    st.rerun()
                if delete:
                    plan[edit_day].pop(index)
                    save_plan(plan)
                    st.rerun()

    with st.expander("＋ Add an exercise", expanded=not plan[edit_day]):
        with st.form(f"add_{edit_day}", clear_on_submit=True):
            new_name = st.text_input("Exercise name")
            c1, c2 = st.columns(2)
            new_sets = c1.number_input("Sets", 1, 20, 3)
            new_reps = c2.text_input("Rep target", "8–12")
            new_alternatives = st.text_area("Alternatives (one per line)")
            new_notes = st.text_area("Form cues / notes")
            if st.form_submit_button("Add to plan", type="primary"):
                if new_name.strip():
                    plan[edit_day].append(
                        {
                            "name": new_name.strip(),
                            "sets": new_sets,
                            "reps": new_reps.strip(),
                            "alternatives": [
                                x.strip() for x in new_alternatives.splitlines() if x.strip()
                            ],
                            "notes": new_notes.strip(),
                            "source": "Custom",
                        }
                    )
                    save_plan(plan)
                    st.rerun()
                else:
                    st.error("Enter an exercise name.")

with tab_progress:
    log = read_log(db)
    if log.empty:
        st.info("Your progress will appear here after you log your first exercise.")
    else:
        log["performed_on"] = pd.to_datetime(log["performed_on"])
        completed_days = log.groupby("performed_on").size().rename("sets")
        c1, c2, c3 = st.columns(3)
        c1.metric("Training days", int(log["performed_on"].nunique()))
        c2.metric("Exercises logged", int(log["created_at"].nunique()))
        c3.metric("Sets completed", len(log))

        st.subheader("Training activity")
        st.bar_chart(completed_days, y="sets", x_label="Date", y_label="Completed sets")

        exercise_filter = st.selectbox(
            "Exercise history", ["All exercises", *sorted(log["performed_exercise"].unique())]
        )
        shown = log if exercise_filter == "All exercises" else log[
            log["performed_exercise"] == exercise_filter
        ]
        display = shown[
            [
                "performed_on", "performed_exercise", "set_number", "reps",
                "weight", "rir", "pain", "notes",
            ]
        ].rename(
            columns={
                "performed_on": "Date", "performed_exercise": "Exercise", "set_number": "Set",
                "reps": "Reps", "weight": "Weight (kg)", "rir": "RIR", "pain": "Pain",
                "notes": "Notes",
            }
        )
        st.dataframe(display, use_container_width=True, hide_index=True)
        st.download_button(
            "Download progress as CSV",
            log.to_csv(index=False).encode("utf-8"),
            "workout_progress.csv",
            "text/csv",
        )

        with st.expander("Delete a mistaken entry"):
            entry = st.selectbox(
                "Entry",
                shown["id"].tolist(),
                format_func=lambda row_id: (
                    f"#{row_id} · "
                    f"{shown.loc[shown['id'] == row_id, 'performed_on'].iloc[0].date()} · "
                    f"{shown.loc[shown['id'] == row_id, 'performed_exercise'].iloc[0]} · "
                    f"set {shown.loc[shown['id'] == row_id, 'set_number'].iloc[0]}"
                ),
            )
            if st.button("Delete selected entry"):
                db.execute("DELETE FROM workout_log WHERE id = ?", (int(entry),))
                db.commit()
                st.rerun()

st.divider()
st.caption(
    "Training guidance is educational, not medical advice. Stop if you feel sharp pain, "
    "and ask a qualified professional if an exercise causes persistent discomfort."
)
db.close()
