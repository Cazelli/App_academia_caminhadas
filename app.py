from __future__ import annotations

import json
import re
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
MUSCLE_GROUPS = [
    "Chest", "Back", "Shoulders", "Biceps", "Triceps", "Quadriceps",
    "Hamstrings", "Glutes", "Calves", "Core",
]


def infer_muscle_groups(name: str) -> list[str]:
    text = name.lower()
    rules = [
        (("chest press", "pec deck", "chest fly", "bench press"), ["Chest", "Shoulders", "Triceps"]),
        (("lat pulldown", "pull-up"), ["Back", "Biceps"]),
        (("row",), ["Back", "Biceps"]),
        (("shoulder press",), ["Shoulders", "Triceps"]),
        (("lateral raise",), ["Shoulders"]),
        (("reverse pec", "rear-delt", "face pull"), ["Shoulders", "Back"]),
        (("triceps",), ["Triceps"]),
        (("curl",), ["Biceps"]),
        (("leg press", "split squat", "step-up", "leg extension", "goblet squat"), ["Quadriceps", "Glutes"]),
        (("leg curl",), ["Hamstrings"]),
        (("hip thrust", "glute bridge", "pull-through", "hip abduction"), ["Glutes"]),
        (("calf",), ["Calves"]),
        (("pallof", "crunch", "dead bug"), ["Core"]),
    ]
    groups: list[str] = []
    for keywords, matched_groups in rules:
        if any(keyword in text for keyword in keywords):
            groups.extend(group for group in matched_groups if group not in groups)
    return groups

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
        "muscle_groups": infer_muscle_groups(name),
    }


STARTER_PLAN = {
    "Monday": [
        exercise("Machine chest press", 4, "8–12", ["Dumbbell bench press", "Smith-machine bench press"]),
        exercise("Neutral-grip lat pulldown", 4, "8–12", ["Assisted pull-up", "Regular lat pulldown"]),
        exercise(
            "Chest-supported row", 3, "8–12",
            ["Chest-supported dumbbell row", "Seated cable row"],
            "Keep the chest supported and pull under control.",
        ),
        exercise(
            "Machine shoulder press", 3, "8–12",
            ["Dumbbell shoulder press (neutral grip)", "Landmine press"],
            "Neutral grip is the default. Keep elbows slightly forward and your back and "
            "head on the pad. Do not lower excessively deep or continue through pinching.",
        ),
        exercise("Cable triceps pushdown", 3, "10–15", ["Machine triceps extension", "Resistance-band pushdown"]),
        exercise("Machine or cable curl", 3, "10–15", ["Dumbbell curl", "Hammer curl"]),
    ],
    "Tuesday": [
        exercise(
            "Leg press", 3, "10–15", ["Box squat", "Supported goblet squat"],
            "Use a comfortable depth. Do not force the knees toward the chest if the lower back rounds.",
        ),
        exercise("Seated leg curl", 3, "10–15", ["Lying leg curl", "Standing machine leg curl"]),
        exercise("Leg extension", 3, "12–15", ["Supported low step-up", "Spanish squat"]),
        exercise("Machine hip thrust", 3, "10–15", ["Glute bridge", "Cable pull-through"]),
        exercise("Seated calf raise", 3, "12–20", ["Standing calf raise", "Calf press on leg press"]),
        exercise("Pallof press", 3, "10–15 per side", ["Dead bug", "Machine crunch"]),
    ],
    "Wednesday": [
        exercise("Incline machine chest press", 4, "8–12", ["Incline dumbbell press", "Incline Smith-machine press"]),
        exercise(
            "Pec deck", 3, "10–15", ["Cable chest fly", "Dumbbell chest fly"],
            "Keep your back and head on the pad and a slight elbow bend. Move slowly; "
            "do not let the arms travel excessively behind the body.",
        ),
        exercise(
            "Machine shoulder press", 3, "8–12",
            ["Dumbbell shoulder press (neutral grip)", "Landmine press"],
            "Keep elbows slightly forward, back and head on the pad, and stop before the shoulders roll forward.",
        ),
        exercise("Cable or machine lateral raise", 4, "12–20", ["Dumbbell lateral raise", "Single-arm cable lateral raise"]),
        exercise("Cable triceps pushdown", 3, "10–15", ["Machine triceps extension", "Resistance-band pushdown"]),
        exercise("Overhead cable triceps extension", 3, "10–15", ["Single-arm cable extension", "Dumbbell overhead extension"]),
    ],
    "Thursday": [
        exercise("Neutral-grip lat pulldown", 4, "8–12", ["Assisted neutral-grip pull-up", "Regular lat pulldown"]),
        exercise(
            "Chest-supported machine row", 4, "8–12",
            ["Chest-supported dumbbell row", "Seated cable row"],
            "Chest support is preferred initially because it reduces demand on the lower back.",
        ),
        exercise("One-arm cable row", 3, "10–15 per side", ["One-arm machine row", "Chest-supported dumbbell row"]),
        exercise("Reverse pec deck", 4, "12–20", ["Cable rear-delt fly", "Face pull"]),
        exercise("Cable or machine curl", 3, "10–15", ["Dumbbell curl", "Preacher curl"]),
        exercise("Hammer curl", 3, "10–15", ["Rope cable hammer curl", "Machine curl"]),
    ],
    "Friday": [
        exercise(
            "Seated or lying leg curl", 4, "8–12",
            ["Standing machine leg curl", "Stability-ball leg curl"],
        ),
        exercise(
            "Leg press, feet slightly higher", 3, "10–15",
            ["Box squat", "Supported goblet squat"],
            "Use a comfortable depth and keep the lower back from rounding.",
        ),
        exercise(
            "Supported split squat or low step-up", 3, "8–12 per leg",
            ["Leg extension", "Supported reverse lunge"],
            "Hold a fixed support and use controlled technique.",
        ),
        exercise("Machine hip thrust", 4, "8–12", ["Glute bridge", "Cable pull-through"]),
        exercise("Seated calf raise", 3, "12–20", ["Standing calf raise", "Calf press on leg press"]),
        exercise("Machine crunch or dead bug", 3, "10–15", ["Pallof press", "Cable crunch"]),
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
    normalized = {day: saved.get(day, []) for day in DAYS}
    changed = False
    for exercises in normalized.values():
        for item in exercises:
            if not item.get("muscle_groups"):
                item["muscle_groups"] = infer_muscle_groups(item.get("name", ""))
                changed = True
    if changed:
        save_plan(normalized)
    return normalized


def save_plan(plan: dict[str, list[dict]]) -> None:
    PLAN_PATH.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")


def read_log(connection: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT * FROM workout_log ORDER BY performed_on DESC, id DESC", connection
    )


def exercise_label(item: dict) -> str:
    return f"{item['name']} · {item['sets']} × {item['reps']}"


def target_rep_range(target: str) -> tuple[int | None, int | None]:
    values = [int(value) for value in re.findall(r"\d+", str(target))]
    return (values[0], values[1]) if len(values) >= 2 else (None, None)


def session_summary(log: pd.DataFrame) -> pd.DataFrame:
    working = log.copy()
    working["reps_num"] = pd.to_numeric(working["reps"], errors="coerce").fillna(0)
    working["weight"] = pd.to_numeric(working["weight"], errors="coerce").fillna(0)
    working["volume_load"] = working["reps_num"] * working["weight"]
    working["estimated_1rm"] = working["weight"] * (1 + working["reps_num"] / 30)
    return (
        working.groupby(
            ["created_at", "performed_on", "day_name", "planned_exercise", "performed_exercise"],
            as_index=False,
        )
        .agg(
            sets=("id", "count"),
            total_reps=("reps_num", "sum"),
            minimum_reps=("reps_num", "min"),
            best_reps=("reps_num", "max"),
            best_weight=("weight", "max"),
            volume_load=("volume_load", "sum"),
            estimated_1rm=("estimated_1rm", "max"),
            average_rir=("rir", "mean"),
            average_pain=("pain", "mean"),
        )
        .sort_values(["performed_on", "created_at"])
    )


def apply_date_to_day(day: str, exercise_count: int) -> None:
    selected_date = st.session_state[f"workout_date_{day}"]
    for exercise_index in range(exercise_count):
        st.session_state[f"date_{day}_{exercise_index}"] = selected_date


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

    workout_date = st.date_input(
        "Date for all exercises",
        value=date.today(),
        key=f"workout_date_{selected_day}",
        on_change=apply_date_to_day,
        args=(selected_day, len(exercises)),
        help="Changing this date updates every exercise below. You can still override an individual date.",
    )
    st.caption("This date is applied to all exercises; individual dates remain editable.")

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
                    set_count = st.selectbox(
                        "Number of sets",
                        options=list(range(1, 11)),
                        index=min(max(int(item["sets"]), 1), 10) - 1,
                        key=f"set_count_{selected_day}_{index}",
                        help="Choose how many sets you performed, then enter each set below.",
                    )
                    with st.form(f"log_{selected_day}_{index}", clear_on_submit=True):
                        exercise_date_key = f"date_{selected_day}_{index}"
                        if exercise_date_key not in st.session_state:
                            st.session_state[exercise_date_key] = workout_date
                        log_date = st.date_input(
                            "Date",
                            key=exercise_date_key,
                            help="Change this only when this exercise was performed on a different date.",
                        )
                        st.markdown("**Sets performed**")
                        set_values = []
                        for set_number in range(1, set_count + 1):
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
                muscle_groups = st.multiselect(
                    "Muscle groups",
                    MUSCLE_GROUPS,
                    default=item.get("muscle_groups", []),
                    help="Each completed set counts toward every selected muscle group.",
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
                        "muscle_groups": muscle_groups,
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
            new_muscle_groups = st.multiselect("Muscle groups", MUSCLE_GROUPS)
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
                            "muscle_groups": new_muscle_groups,
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
        sessions = session_summary(log)
        completed_days = log.groupby("performed_on").size().rename("Completed sets")
        c1, c2, c3 = st.columns(3)
        c1.metric("Training days", int(log["performed_on"].nunique()))
        c2.metric("Exercises logged", int(log["created_at"].nunique()))
        c3.metric("Sets completed", len(log))

        overview_tab, exercise_tab, muscles_tab, recovery_tab, history_tab = st.tabs(
            ["Overview", "Exercise progress", "Muscle groups", "Effort & pain", "History"]
        )

        with overview_tab:
            st.subheader("Training activity")
            st.bar_chart(completed_days, x_label="Date", y_label="Completed sets")

            sessions_by_week = (
                sessions.assign(week=sessions["performed_on"].dt.to_period("W-MON").dt.start_time)
                .groupby("week")["performed_on"]
                .nunique()
                .rename("Completed workouts")
            )
            first_week = sessions_by_week.index.min()
            current_week = pd.Timestamp.today().to_period("W-MON").start_time
            week_index = pd.date_range(first_week, current_week, freq="W-TUE")
            if len(week_index) == 0:
                week_index = pd.DatetimeIndex([first_week])
            adherence = sessions_by_week.reindex(week_index, fill_value=0).to_frame()
            adherence["Planned workouts"] = 5
            if current_week in adherence.index:
                elapsed_weekdays = min(pd.Timestamp.today().weekday() + 1, 5)
                adherence.loc[current_week, "Planned workouts"] = elapsed_weekdays
            adherence["Adherence %"] = (
                adherence["Completed workouts"] / adherence["Planned workouts"].clip(lower=1) * 100
            ).clip(upper=100)

            st.subheader("Weekly adherence")
            st.bar_chart(
                adherence[["Completed workouts", "Planned workouts"]],
                x_label="Week", y_label="Workouts",
            )
            recent = adherence.tail(4)
            st.metric(
                "Four-week adherence",
                f"{recent['Completed workouts'].sum() / recent['Planned workouts'].sum():.0%}",
            )

            st.subheader("Personal records")
            records = (
                sessions.groupby("performed_exercise", as_index=False)
                .agg(
                    Sessions=("created_at", "nunique"),
                    **{
                        "Best weight (kg)": ("best_weight", "max"),
                        "Best reps": ("best_reps", "max"),
                        "Estimated 1RM (kg)": ("estimated_1rm", "max"),
                    },
                )
                .rename(columns={"performed_exercise": "Exercise"})
            )
            records["Estimated 1RM (kg)"] = records["Estimated 1RM (kg)"].round(1)
            st.dataframe(records, width="stretch", hide_index=True)

        with exercise_tab:
            selected_exercise = st.selectbox(
                "Exercise",
                sorted(sessions["performed_exercise"].unique()),
                key="progress_exercise",
            )
            exercise_sessions = sessions[
                sessions["performed_exercise"] == selected_exercise
            ].sort_values(["performed_on", "created_at"])
            latest = exercise_sessions.iloc[-1]
            previous = exercise_sessions.iloc[-2] if len(exercise_sessions) > 1 else None

            planned_item = next(
                (
                    item
                    for day_exercises in plan.values()
                    for item in day_exercises
                    if item["name"] == latest["planned_exercise"]
                    or selected_exercise in item.get("alternatives", [])
                ),
                None,
            )
            lower_target, upper_target = target_rep_range(
                planned_item["reps"] if planned_item else ""
            )
            latest_sets = log[log["created_at"] == latest["created_at"]].copy()
            latest_sets["reps_num"] = pd.to_numeric(latest_sets["reps"], errors="coerce")

            if latest["average_pain"] >= 4:
                signal, message = "🔴 Review before progressing", (
                    "Pain/discomfort was elevated. Do not increase the load; review the "
                    "movement, setup, and recovery first."
                )
            elif (
                previous is not None
                and latest["estimated_1rm"] < previous["estimated_1rm"] * 0.95
            ):
                signal, message = "🔴 Performance dropped", (
                    "Estimated performance fell by more than 5% from the previous session. "
                    "Keep or reduce the load and check fatigue and recovery."
                )
            elif (
                upper_target is not None
                and latest_sets["reps_num"].min() >= upper_target
                and 1 <= latest["average_rir"] <= 4
                and latest["average_pain"] <= 2
            ):
                signal, message = "🟢 Ready to progress", (
                    "Every logged set reached the top of the target range with controlled "
                    "effort and low discomfort. Consider the smallest available load increase."
                )
            else:
                signal, message = "🟡 Build repetitions", (
                    "Keep the current load and work toward the top of the rep range on every set."
                )
            st.subheader(signal)
            st.write(message)

            d1, d2, d3, d4 = st.columns(4)
            d1.metric(
                "Best weight",
                f"{latest['best_weight']:.1f} kg",
                None if previous is None else f"{latest['best_weight'] - previous['best_weight']:+.1f}",
            )
            d2.metric(
                "Estimated 1RM",
                f"{latest['estimated_1rm']:.1f} kg",
                None if previous is None else f"{latest['estimated_1rm'] - previous['estimated_1rm']:+.1f}",
            )
            d3.metric(
                "Total reps",
                int(latest["total_reps"]),
                None if previous is None else f"{latest['total_reps'] - previous['total_reps']:+.0f}",
            )
            d4.metric("Average RIR", f"{latest['average_rir']:.1f}")

            trend = exercise_sessions.set_index("performed_on")[
                ["best_weight", "estimated_1rm"]
            ].rename(
                columns={"best_weight": "Best weight", "estimated_1rm": "Estimated 1RM"}
            )
            st.subheader("Strength trend")
            st.line_chart(trend, x_label="Date", y_label="Kilograms")
            st.caption(
                "Estimated 1RM uses the Epley formula and is a trend estimate—not a "
                "recommendation to attempt a maximum lift."
            )

            st.subheader("Recent set-by-set performance")
            comparison_rows = []
            recent_session_ids = exercise_sessions.tail(5)["created_at"].tolist()
            for session_id in reversed(recent_session_ids):
                set_rows = log[log["created_at"] == session_id].sort_values("set_number")
                row = {
                    "Date": set_rows["performed_on"].iloc[0].date(),
                    "RIR": set_rows["rir"].mean(),
                    "Pain": set_rows["pain"].mean(),
                }
                for _, set_row in set_rows.iterrows():
                    row[f"Set {int(set_row['set_number'])}"] = (
                        f"{float(set_row['weight']):g} kg × {set_row['reps']}"
                    )
                comparison_rows.append(row)
            st.dataframe(pd.DataFrame(comparison_rows), width="stretch", hide_index=True)

        with muscles_tab:
            plan_groups = {
                item["name"]: item.get("muscle_groups", infer_muscle_groups(item["name"]))
                for day_exercises in plan.values()
                for item in day_exercises
            }
            muscle_rows = []
            for _, set_row in log.iterrows():
                groups = plan_groups.get(
                    set_row["planned_exercise"],
                    infer_muscle_groups(set_row["planned_exercise"]),
                )
                for group in groups:
                    muscle_rows.append(
                        {
                            "Week": set_row["performed_on"].to_period("W-MON").start_time,
                            "Muscle group": group,
                            "Completed sets": 1,
                        }
                    )
            if muscle_rows:
                muscle_data = pd.DataFrame(muscle_rows)
                muscle_weekly = (
                    muscle_data.groupby(["Week", "Muscle group"])["Completed sets"]
                    .sum()
                    .unstack(fill_value=0)
                )
                st.subheader("Weekly sets by muscle group")
                st.bar_chart(muscle_weekly, x_label="Week", y_label="Completed sets")
                st.caption(
                    "A compound set counts toward every assigned muscle group. Edit "
                    "assignments in My plan if you prefer primary-muscle-only counting."
                )
                st.dataframe(
                    muscle_weekly.sort_index(ascending=False),
                    width="stretch",
                )
            else:
                st.info("Assign muscle groups in My plan to populate this chart.")

        with recovery_tab:
            weekly_recovery = (
                log.assign(week=log["performed_on"].dt.to_period("W-MON").dt.start_time)
                .groupby("week")[["rir", "pain"]]
                .mean()
                .rename(columns={"rir": "Average RIR", "pain": "Average pain"})
            )
            st.subheader("Weekly effort and discomfort")
            st.line_chart(weekly_recovery, x_label="Week", y_label="Rating")
            recent_pain = log.sort_values("performed_on").tail(20)
            pain_flags = recent_pain[recent_pain["pain"] >= 4]
            zero_rir = recent_pain[recent_pain["rir"] == 0]
            if not pain_flags.empty:
                st.warning(
                    f"{len(pain_flags)} of your last {len(recent_pain)} sets recorded "
                    "pain/discomfort of 4 or higher. Review those exercises before progressing."
                )
            if not zero_rir.empty:
                st.warning(
                    f"{len(zero_rir)} of your last {len(recent_pain)} sets reached 0 RIR. "
                    "Your plan currently targets roughly 2–3 RIR."
                )
            if pain_flags.empty and zero_rir.empty:
                st.success("No elevated pain or unexpected 0-RIR sets in your recent history.")

        with history_tab:
            exercise_filter = st.selectbox(
                "Exercise history",
                ["All exercises", *sorted(log["performed_exercise"].unique())],
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
                    "performed_on": "Date", "performed_exercise": "Exercise",
                    "set_number": "Set", "reps": "Reps", "weight": "Weight (kg)",
                    "rir": "RIR", "pain": "Pain", "notes": "Notes",
                }
            )
            st.dataframe(display, width="stretch", hide_index=True)
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
