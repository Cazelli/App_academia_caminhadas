from __future__ import annotations

import base64
import html
import json
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st


ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
EXERCISE_IMAGE_DIR = ROOT / "assets" / "exercises"
DB_PATH = DATA_DIR / "progress.db"
HISTORY_PATH = DATA_DIR / "workout_progress.csv"
BODY_HISTORY_PATH = DATA_DIR / "body_progress.csv"
CARDIO_HISTORY_PATH = DATA_DIR / "cardio_progress.csv"
PLAN_PATH = DATA_DIR / "workout_plan.json"
DAYS = ["Monday", "Tuesday", "Wednesday", "Friday", "Saturday"]
BRASILIA_TZ = ZoneInfo("America/Sao_Paulo")
MUSCLE_GROUPS = [
    "Chest", "Back", "Shoulders", "Biceps", "Triceps", "Quadriceps",
    "Hamstrings", "Glutes", "Calves", "Core",
]
EXERCISE_IMAGES = {
    "Machine chest press": "machine-bench-press.jpg",
    "Neutral-grip lat pulldown": "neutral-lat-pulldown.jpg",
    "Chest-supported row": "chest-supported-row.jpg",
    "Machine shoulder press": "machine-shoulder-press.jpg",
    "Cable triceps pushdown": "triceps-pushdown.jpg",
    "Machine or cable curl": "machine-curl.jpg",
    "Leg press": "leg-press.jpg",
    "Seated leg curl": "seated-leg-curl.jpg",
    "Leg extension": "leg-extension.jpg",
    "Machine hip thrust": "hip-thrust.jpg",
    "Seated calf raise": "seated-calf-raise.jpg",
    "Pallof press": "pallof-press.jpg",
    "Incline machine chest press": "incline-machine-press.jpg",
    "Pec deck": "pec-deck.jpg",
    "Cable or machine lateral raise": "lateral-raise.jpg",
    "Overhead cable triceps extension": "overhead-triceps.jpg",
    "Chest-supported machine row": "machine-row.jpg",
    "One-arm cable row": "one-arm-cable-row.jpg",
    "Reverse pec deck": "reverse-pec-deck.jpg",
    "Cable or machine curl": "machine-curl.jpg",
    "Hammer curl": "hammer-curl.jpg",
    "Seated or lying leg curl": "seated-leg-curl.jpg",
    "Leg press, feet slightly higher": "leg-press.jpg",
    "Supported split squat or low step-up": "split-squat.jpg",
    "Machine crunch or dead bug": "ab-crunch.jpg",
}


def brasilia_now() -> datetime:
    return datetime.now(BRASILIA_TZ)


def brasilia_today() -> date:
    return brasilia_now().date()


def brasilia_timestamp() -> pd.Timestamp:
    return pd.Timestamp(brasilia_now().replace(tzinfo=None))


def github_history_config() -> dict[str, str] | None:
    try:
        token = str(st.secrets.get("GITHUB_TOKEN", "")).strip()
        repository = str(
            st.secrets.get("GITHUB_HISTORY_REPO", "Cazelli/App_academia_caminhadas")
        ).strip()
        branch = str(st.secrets.get("GITHUB_HISTORY_BRANCH", "main")).strip()
    except FileNotFoundError:
        return None
    if not token or not repository:
        return None
    return {
        "token": token,
        "repository": repository,
        "branch": branch,
        "path": "data/workout_progress.csv",
    }


def github_history_request(
    config: dict[str, str],
    method: str = "GET",
    payload: dict | None = None,
    path: str | None = None,
) -> dict | None:
    encoded_path = urllib.parse.quote(path or config["path"])
    url = f"https://api.github.com/repos/{config['repository']}/contents/{encoded_path}"
    if method == "GET":
        url += f"?ref={urllib.parse.quote(config['branch'])}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {config['token']}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "my-training-path",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if method == "GET" and error.code == 404:
            return None
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub returned HTTP {error.code}: {detail}") from error


def restore_history_from_github(config: dict[str, str] | None) -> bool:
    if config is None:
        return False
    remote_file = github_history_request(config)
    if remote_file is None:
        return False
    history_bytes = base64.b64decode(remote_file["content"])
    if not history_bytes.lstrip().startswith((b"id,", b"Date,")):
        raise RuntimeError("The GitHub history file is not a recognized workout CSV.")
    DATA_DIR.mkdir(exist_ok=True)
    HISTORY_PATH.write_bytes(history_bytes)
    return True


def export_history_csv(connection: sqlite3.Connection) -> None:
    read_log(connection).to_csv(HISTORY_PATH, index=False)


def import_history_csv(connection: sqlite3.Connection) -> int:
    history = pd.read_csv(HISTORY_PATH)
    display_columns = {
        "Date": "performed_on",
        "Exercise": "performed_exercise",
        "Set": "set_number",
        "Reps": "reps",
        "Weight (kg)": "weight",
        "RIR": "rir",
        "Pain": "pain",
        "Notes": "notes",
    }
    if "Date" in history.columns:
        history = history.rename(columns=display_columns)
        history["performed_on"] = history["performed_on"].astype(str).str[:10]
        history["planned_exercise"] = history["performed_exercise"]
        history["day_name"] = pd.to_datetime(history["performed_on"]).dt.day_name()
        history["sets"] = 1
        session_keys = (
            history["performed_on"].astype(str)
            + "|"
            + history["performed_exercise"].astype(str)
        )
        session_numbers = pd.factorize(session_keys, sort=False)[0]
        history["created_at"] = [
            f"{performed_on}T12:00:{session_number:02d}.000000-03:00"
            for performed_on, session_number in zip(
                history["performed_on"], session_numbers
            )
        ]

    required = [
        "performed_on", "day_name", "planned_exercise", "performed_exercise",
        "sets", "reps", "weight", "rir", "pain", "notes", "set_number",
        "created_at",
    ]
    missing = [column for column in required if column not in history.columns]
    if missing:
        raise RuntimeError(f"History CSV is missing columns: {', '.join(missing)}")
    history["notes"] = history["notes"].fillna("")
    connection.execute("DELETE FROM workout_log")
    connection.executemany(
        """
        INSERT INTO workout_log (
            performed_on, day_name, planned_exercise, performed_exercise,
            sets, reps, weight, rir, pain, notes, set_number, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        history[required].itertuples(index=False, name=None),
    )
    connection.commit()
    export_history_csv(connection)
    return len(history)


def save_history_to_github(
    config: dict[str, str] | None, connection: sqlite3.Connection
) -> bool:
    export_history_csv(connection)
    if config is None:
        return False
    remote_file = github_history_request(config)
    payload = {
        "message": f"Update workout history ({brasilia_now():%Y-%m-%d %H:%M BRT})",
        "content": base64.b64encode(HISTORY_PATH.read_bytes()).decode("ascii"),
        "branch": config["branch"],
    }
    if remote_file is not None:
        payload["sha"] = remote_file["sha"]
    github_history_request(config, method="PUT", payload=payload)
    return True


def infer_muscle_groups(name: str) -> list[str]:
    text = name.lower()
    if "leg curl" in text:
        return ["Hamstrings"]
    if "reverse pec" in text or "rear-delt" in text or "face pull" in text:
        return ["Shoulders", "Back"]
    rules = [
        (("chest press", "bench press"), ["Chest", "Shoulders", "Triceps"]),
        (("pec deck", "chest fly"), ["Chest"]),
        (("lat pulldown", "pull-up"), ["Back", "Biceps"]),
        (("row",), ["Back", "Biceps"]),
        (("shoulder press",), ["Shoulders", "Triceps"]),
        (("lateral raise",), ["Shoulders"]),
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
    "Friday": [
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
    "Saturday": [
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
    "Monday": [
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
    "Tuesday": [
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
    "Wednesday": [
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
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS body_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            measured_on TEXT NOT NULL UNIQUE,
            weight REAL NOT NULL,
            waist REAL,
            hips REAL,
            chest REAL,
            thigh REAL,
            upper_arm REAL,
            neck REAL,
            notes TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS cardio_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            performed_on TEXT NOT NULL,
            activity TEXT NOT NULL,
            duration_minutes INTEGER NOT NULL,
            duration_seconds REAL,
            distance_km REAL,
            average_heart_rate INTEGER,
            effort INTEGER,
            notes TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cardio_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(cardio_log)")
    }
    if "duration_seconds" not in cardio_columns:
        connection.execute("ALTER TABLE cardio_log ADD COLUMN duration_seconds REAL")
    connection.execute(
        """
        UPDATE cardio_log
        SET duration_seconds = duration_minutes * 60.0
        WHERE duration_seconds IS NULL
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS app_migrations (
            migration_id TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    migration_id = "correct_2026_07_28_to_brasilia_2026_07_27"
    already_applied = connection.execute(
        "SELECT 1 FROM app_migrations WHERE migration_id = ?", (migration_id,)
    ).fetchone()
    if not already_applied:
        connection.execute(
            "UPDATE workout_log SET performed_on = ? WHERE performed_on = ?",
            ("2026-07-27", "2026-07-28"),
        )
        connection.execute(
            "INSERT INTO app_migrations (migration_id, applied_at) VALUES (?, ?)",
            (migration_id, brasilia_now().isoformat(timespec="microseconds")),
        )
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


def read_body_log(connection: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT * FROM body_log ORDER BY measured_on DESC, id DESC", connection
    )


def read_cardio_log(connection: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT * FROM cardio_log ORDER BY performed_on DESC, id DESC", connection
    )


def format_precise_duration(total_seconds: float) -> str:
    total_hundredths = round(float(total_seconds) * 100)
    hours, remainder = divmod(total_hundredths, 360000)
    minutes, remainder = divmod(remainder, 6000)
    seconds, hundredths = divmod(remainder, 100)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{hundredths:02d}"


def export_wellness_csvs(connection: sqlite3.Connection) -> None:
    read_body_log(connection).to_csv(BODY_HISTORY_PATH, index=False)
    read_cardio_log(connection).to_csv(CARDIO_HISTORY_PATH, index=False)


def import_wellness_csvs(connection: sqlite3.Connection) -> None:
    for path, table in (
        (BODY_HISTORY_PATH, "body_log"),
        (CARDIO_HISTORY_PATH, "cardio_log"),
    ):
        if not path.exists() or path.stat().st_size == 0:
            continue
        frame = pd.read_csv(path)
        if frame.empty:
            continue
        valid_columns = {
            row[1] for row in connection.execute(f"PRAGMA table_info({table})")
        }
        columns = [column for column in frame.columns if column in valid_columns]
        if "id" not in columns:
            continue
        connection.execute(f"DELETE FROM {table}")
        placeholders = ", ".join("?" for _ in columns)
        connection.executemany(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
            frame[columns].where(pd.notna(frame[columns]), None).itertuples(
                index=False, name=None
            ),
        )
    connection.commit()


def restore_wellness_from_github(config: dict[str, str] | None) -> bool:
    if config is None:
        return False
    restored = False
    for path, local_path in (
        ("data/body_progress.csv", BODY_HISTORY_PATH),
        ("data/cardio_progress.csv", CARDIO_HISTORY_PATH),
    ):
        remote_file = github_history_request(config, path=path)
        if remote_file is not None:
            local_path.write_bytes(base64.b64decode(remote_file["content"]))
            restored = True
    return restored


def save_wellness_to_github(
    config: dict[str, str] | None, connection: sqlite3.Connection
) -> bool:
    export_wellness_csvs(connection)
    if config is None:
        return False
    for path, local_path in (
        ("data/body_progress.csv", BODY_HISTORY_PATH),
        ("data/cardio_progress.csv", CARDIO_HISTORY_PATH),
    ):
        remote_file = github_history_request(config, path=path)
        payload = {
            "message": f"Update {local_path.stem} ({brasilia_now():%Y-%m-%d %H:%M BRT})",
            "content": base64.b64encode(local_path.read_bytes()).decode("ascii"),
            "branch": config["branch"],
        }
        if remote_file is not None:
            payload["sha"] = remote_file["sha"]
        github_history_request(config, method="PUT", payload=payload, path=path)
    return True


def exercise_label(item: dict) -> str:
    return f"{item['name']} · {item['sets']} × {item['reps']}"


def exercise_image_path(name: str) -> Path | None:
    filename = EXERCISE_IMAGES.get(name)
    path = EXERCISE_IMAGE_DIR / filename if filename else None
    return path if path and path.exists() else None


def muscle_caption(item: dict) -> str:
    groups = item.get("muscle_groups", [])
    return " · ".join(groups) if groups else "No muscle groups assigned"


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


def personal_bests(log: pd.DataFrame) -> dict[str, tuple[float, int, int, float]]:
    """Return paired weight and repetition records for each performed exercise."""
    if log.empty:
        return {}

    working = log.copy()
    working["weight_num"] = pd.to_numeric(working["weight"], errors="coerce")
    working["reps_num"] = pd.to_numeric(working["reps"], errors="coerce")
    bests = {}
    for exercise_name, sets in working.dropna(
        subset=["performed_exercise", "weight_num", "reps_num"]
    ).groupby("performed_exercise", sort=False):
        heaviest_set = sets.sort_values(
            ["weight_num", "reps_num"], ascending=False
        ).iloc[0]
        highest_rep_set = sets.sort_values(
            ["reps_num", "weight_num"], ascending=False
        ).iloc[0]
        bests[exercise_name] = (
            float(heaviest_set["weight_num"]),
            int(heaviest_set["reps_num"]),
            int(highest_rep_set["reps_num"]),
            float(highest_rep_set["weight_num"]),
        )
    return bests


def today_recommendation(log: pd.DataFrame, item: dict) -> str:
    """Suggest today's load from the exercise's most recent logged session."""
    exercise_log = log[log["performed_exercise"] == item["name"]].copy()
    target = f"{item['sets']} × {item['reps']}"
    if exercise_log.empty:
        return f"Recommended today · {target} · Choose a comfortable starting weight"

    latest_created_at = exercise_log.iloc[0]["created_at"]
    latest_sets = exercise_log[exercise_log["created_at"] == latest_created_at]
    weights = pd.to_numeric(latest_sets["weight"], errors="coerce").dropna()
    reps = pd.to_numeric(latest_sets["reps"], errors="coerce").dropna()
    current_weight = float(weights.max()) if not weights.empty else 0.0
    average_pain = pd.to_numeric(latest_sets["pain"], errors="coerce").mean()
    average_rir = pd.to_numeric(latest_sets["rir"], errors="coerce").mean()
    _, upper_target = target_rep_range(item["reps"])

    if pd.notna(average_pain) and average_pain >= 4:
        return (
            f"Recommended today · Up to {current_weight:g} kg · "
            "Review comfort before progressing"
        )
    if (
        upper_target is not None
        and not reps.empty
        and reps.min() >= upper_target
        and pd.notna(average_rir)
        and 1 <= average_rir <= 4
        and (pd.isna(average_pain) or average_pain <= 2)
    ):
        return (
            f"Recommended today · {target} · Increase slightly above "
            f"{current_weight:g} kg"
        )
    return f"Recommended today · {target} at {current_weight:g} kg"


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
      .personal-best {
        display:inline-block; margin:.2rem 0 .45rem; padding:.3rem .65rem;
        border:1px solid #365846; border-radius:999px; color:#b8e6cc;
        background:#16231d; font-size:.82rem; font-weight:600;
      }
      .personal-best .recommendation {
        display:block; margin-top:.22rem; padding-top:.22rem;
        border-top:1px solid #365846; color:#d8eadf; font-weight:500;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

plan = load_plan()
github_config = github_history_config()
github_sync_error = None
try:
    history_restored = restore_history_from_github(github_config)
    wellness_restored = restore_wellness_from_github(github_config)
except (OSError, RuntimeError, ValueError, KeyError) as error:
    history_restored = False
    wellness_restored = False
    github_sync_error = str(error)
db = connect()
if HISTORY_PATH.exists():
    try:
        import_history_csv(db)
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        github_sync_error = str(error)
try:
    import_wellness_csvs(db)
except (OSError, RuntimeError, ValueError, KeyError, sqlite3.Error) as error:
    github_sync_error = str(error)
if github_config is not None and not history_restored and github_sync_error is None:
    try:
        save_history_to_github(github_config, db)
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        github_sync_error = str(error)
if github_config is not None and not wellness_restored and github_sync_error is None:
    try:
        save_wellness_to_github(github_config, db)
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        github_sync_error = str(error)

st.markdown('<p class="eyebrow">Personal training companion</p>', unsafe_allow_html=True)
st.title("My Training Path")
st.caption("Know what to do today, swap an exercise when needed, and keep a useful record of your progress.")
if github_config is None:
    st.sidebar.warning("GitHub history backup is not configured.")
elif github_sync_error:
    st.sidebar.error(f"GitHub history sync failed: {github_sync_error}")
else:
    st.sidebar.success("History is backed up to GitHub.")

today_name = brasilia_now().strftime("%A")
default_day = DAYS.index(today_name) if today_name in DAYS else 0

tab_today, tab_plan, tab_progress, tab_body, tab_cardio = st.tabs(
    ["Today", "My plan", "Strength progress", "Body tracking", "Cardio"]
)

with tab_today:
    today_log = read_log(db)
    exercise_bests = personal_bests(today_log)
    selected_day = st.segmented_control(
        "Training day", DAYS, default=DAYS[default_day], selection_mode="single"
    )
    exercises = plan.get(selected_day, [])

    workout_date = st.date_input(
        "Date for all exercises",
        value=brasilia_today(),
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
                details_col, image_col = st.columns([3, 1.15], vertical_alignment="top")
                with details_col:
                    title_col, target_col = st.columns([3, 1])
                    title_col.markdown(f"#### {index + 1}. {item['name']}")
                    target_col.markdown(f"### {item['sets']} × {item['reps']}")
                    best = exercise_bests.get(item["name"])
                    recommendation = html.escape(today_recommendation(today_log, item))
                    if best:
                        best_weight, reps_at_best_weight, best_reps, weight_at_best_reps = best
                        st.markdown(
                            '<span class="personal-best">'
                            f"Max weight · {best_weight:g} kg × {reps_at_best_weight} reps"
                            f"&nbsp;&nbsp;|&nbsp;&nbsp; Max reps · {best_reps} × "
                            f"{weight_at_best_reps:g} kg"
                            f'<span class="recommendation">{recommendation}</span>'
                            "</span>",
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(
                            '<span class="personal-best">Personal best · No logs yet'
                            f'<span class="recommendation">{recommendation}</span></span>',
                            unsafe_allow_html=True,
                        )
                    st.caption(f"Targets: {muscle_caption(item)}")
                    if item.get("source") == "PDF":
                        st.caption("From your ChatGPT conversation PDF")
                    st.write(item.get("notes", ""))
                image_path = exercise_image_path(item["name"])
                with image_col:
                    if image_path:
                        st.image(
                            str(image_path),
                            caption="Exercise demonstration",
                            width="stretch",
                        )

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
                                logged_at = brasilia_now().isoformat(timespec="microseconds")
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
                                try:
                                    backed_up = save_history_to_github(github_config, db)
                                except (OSError, RuntimeError, ValueError, KeyError) as error:
                                    backed_up = False
                                    st.error(
                                        "Sets were saved locally, but the GitHub backup failed: "
                                        f"{error}"
                                    )
                                if backed_up:
                                    st.success(
                                        f"{len(completed)} sets saved and backed up to GitHub."
                                    )
                                elif github_config is None:
                                    st.success(f"{len(completed)} sets saved locally.")

with tab_plan:
    st.subheader("Build your Monday–Saturday plan")
    st.caption(
        "The starter schedule follows the full routine in your updated PDF. "
        "You can still add, edit, or remove any exercise."
    )
    edit_day = st.selectbox("Day to edit", DAYS)

    for index, item in enumerate(plan[edit_day]):
        with st.expander(exercise_label(item), expanded=False):
            image_path = exercise_image_path(item["name"])
            if image_path:
                preview_col, target_col = st.columns([1, 2], vertical_alignment="center")
                preview_col.image(str(image_path), width="stretch")
                target_col.markdown(f"**Target muscles:** {muscle_caption(item)}")
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
                sessions.assign(week=sessions["performed_on"].dt.to_period("W-SUN").dt.start_time)
                .groupby("week")["performed_on"]
                .nunique()
                .rename("Completed workouts")
            )
            first_week = sessions_by_week.index.min()
            current_week = brasilia_timestamp().to_period("W-SUN").start_time
            week_index = pd.date_range(first_week, current_week, freq="W-MON")
            if len(week_index) == 0:
                week_index = pd.DatetimeIndex([first_week])
            adherence = sessions_by_week.reindex(week_index, fill_value=0).to_frame()
            adherence["Planned workouts"] = 5
            if current_week in adherence.index:
                scheduled_weekdays = {0, 1, 2, 4, 5}
                elapsed_weekdays = sum(
                    weekday <= brasilia_timestamp().weekday()
                    for weekday in scheduled_weekdays
                )
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
                            "Week": set_row["performed_on"].to_period("W-SUN").start_time,
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
                log.assign(week=log["performed_on"].dt.to_period("W-SUN").dt.start_time)
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
                    try:
                        save_history_to_github(github_config, db)
                    except (OSError, RuntimeError, ValueError, KeyError) as error:
                        st.error(
                            "Entry was deleted locally, but the GitHub backup failed: "
                            f"{error}"
                        )
                        st.stop()
                    st.rerun()

with tab_body:
    st.subheader("Weekly body check-in")
    st.caption(
        "Record under similar conditions each Wednesday. Tape measurements are optional; "
        "consistency matters more than measuring every area."
    )
    most_recent_wednesday = brasilia_today() - timedelta(
        days=(brasilia_today().weekday() - 2) % 7
    )
    with st.form("body_check_in", clear_on_submit=True):
        measured_on = st.date_input("Measurement date", value=most_recent_wednesday)
        weight = st.number_input(
            "Weight (kg)", min_value=20.0, max_value=400.0, step=0.1,
            value=None, placeholder="Required",
        )
        st.markdown("**Tape measurements (cm)**")
        b1, b2, b3 = st.columns(3)
        waist = b1.number_input("Waist", 20.0, 300.0, value=None, step=0.1)
        hips = b2.number_input("Hips", 20.0, 300.0, value=None, step=0.1)
        chest = b3.number_input("Chest", 20.0, 300.0, value=None, step=0.1)
        b4, b5, b6 = st.columns(3)
        thigh = b4.number_input("Thigh", 10.0, 150.0, value=None, step=0.1)
        upper_arm = b5.number_input("Upper arm", 10.0, 100.0, value=None, step=0.1)
        neck = b6.number_input("Neck", 10.0, 100.0, value=None, step=0.1)
        body_notes = st.text_area("Notes", placeholder="Time of day, clothing, context…")
        save_body = st.form_submit_button("Save check-in", type="primary")
        if save_body:
            if weight is None:
                st.error("Enter your weight before saving.")
            elif measured_on.weekday() != 2:
                st.error("Choose a Wednesday for your weekly check-in.")
            else:
                db.execute(
                    """
                    INSERT INTO body_log (
                        measured_on, weight, waist, hips, chest, thigh, upper_arm,
                        neck, notes, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(measured_on) DO UPDATE SET
                        weight=excluded.weight, waist=excluded.waist, hips=excluded.hips,
                        chest=excluded.chest, thigh=excluded.thigh,
                        upper_arm=excluded.upper_arm, neck=excluded.neck,
                        notes=excluded.notes, created_at=excluded.created_at
                    """,
                    (
                        measured_on.isoformat(), weight, waist, hips, chest, thigh,
                        upper_arm, neck, body_notes.strip(),
                        brasilia_now().isoformat(timespec="microseconds"),
                    ),
                )
                db.commit()
                try:
                    save_wellness_to_github(github_config, db)
                except (OSError, RuntimeError, ValueError, KeyError) as error:
                    st.warning(f"Saved locally, but the GitHub backup failed: {error}")
                else:
                    st.success("Wednesday check-in saved.")

    body_log = read_body_log(db)
    if body_log.empty:
        st.info("Your weight and measurement trends will appear after the first check-in.")
    else:
        body_log["measured_on"] = pd.to_datetime(body_log["measured_on"])
        chronological_body = body_log.sort_values("measured_on")
        latest_body = chronological_body.iloc[-1]
        first_body = chronological_body.iloc[0]
        m1, m2, m3 = st.columns(3)
        m1.metric(
            "Latest weight", f"{latest_body['weight']:.1f} kg",
            f"{latest_body['weight'] - first_body['weight']:+.1f} kg overall"
            if len(chronological_body) > 1 else None,
            delta_color="inverse",
        )
        m2.metric("Check-ins", len(body_log))
        m3.metric("Latest check-in", latest_body["measured_on"].strftime("%d %b %Y"))
        st.subheader("Weight trend")
        st.line_chart(
            chronological_body.set_index("measured_on")[["weight"]].rename(
                columns={"weight": "Weight (kg)"}
            ),
            x_label="Date", y_label="Kilograms",
        )
        tape_columns = ["waist", "hips", "chest", "thigh", "upper_arm", "neck"]
        tape = chronological_body.set_index("measured_on")[tape_columns].rename(
            columns={
                "waist": "Waist", "hips": "Hips", "chest": "Chest",
                "thigh": "Thigh", "upper_arm": "Upper arm", "neck": "Neck",
            }
        )
        if tape.notna().any().any():
            st.subheader("Tape measurement trends")
            st.line_chart(tape, x_label="Date", y_label="Centimeters")
        st.dataframe(
            body_log.rename(columns={
                "measured_on": "Date", "weight": "Weight (kg)", "waist": "Waist",
                "hips": "Hips", "chest": "Chest", "thigh": "Thigh",
                "upper_arm": "Upper arm", "neck": "Neck", "notes": "Notes",
            })[["Date", "Weight (kg)", "Waist", "Hips", "Chest", "Thigh", "Upper arm", "Neck", "Notes"]],
            width="stretch", hide_index=True,
        )
        delete_body = st.selectbox(
            "Delete body check-in", body_log["id"].tolist(),
            format_func=lambda row_id: body_log.loc[
                body_log["id"] == row_id, "measured_on"
            ].iloc[0].strftime("%d %b %Y"),
        )
        if st.button("Delete selected body check-in"):
            db.execute("DELETE FROM body_log WHERE id = ?", (int(delete_body),))
            db.commit()
            save_wellness_to_github(github_config, db)
            st.rerun()

with tab_cardio:
    st.subheader("Walking, running & cycling")
    st.caption("Log outdoor or indoor sessions. Distance and heart rate are optional.")
    with st.form("cardio_workout", clear_on_submit=True):
        c1, c2 = st.columns(2)
        cardio_date = c1.date_input("Date", value=brasilia_today())
        activity = c2.selectbox(
            "Activity", ["Walking", "Running", "Cycling", "Treadmill", "Stationary bike", "Other"]
        )
        st.markdown("**Duration (HH:MM:SS.hh)**")
        t1, t2, t3, t4 = st.columns(4)
        duration_hours = t1.number_input("Hours", 0, 23, 0, step=1)
        duration_whole_minutes = t2.number_input("Minutes", 0, 59, 30, step=1)
        duration_whole_seconds = t3.number_input("Seconds", 0, 59, 0, step=1)
        duration_hundredths = t4.number_input("Hundredths", 0, 99, 0, step=1)
        duration_seconds = (
            duration_hours * 3600
            + duration_whole_minutes * 60
            + duration_whole_seconds
            + duration_hundredths / 100
        )
        duration = duration_seconds / 60
        distance = st.number_input(
            "Distance (km, optional)", 0.0, 1000.0, value=None, step=0.1
        )
        c5, c6 = st.columns(2)
        heart_rate = c5.number_input(
            "Average heart rate (optional)", 30, 240, value=None, step=1
        )
        effort = c6.select_slider("Effort (1–10)", options=list(range(1, 11)), value=5)
        cardio_notes = st.text_area("Notes", placeholder="Route, terrain, intervals, how it felt…")
        if st.form_submit_button("Save cardio workout", type="primary"):
            if duration_seconds <= 0:
                st.error("Enter a duration greater than zero.")
            else:
                db.execute(
                    """
                    INSERT INTO cardio_log (
                        performed_on, activity, duration_minutes, duration_seconds,
                        distance_km, average_heart_rate, effort, notes, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cardio_date.isoformat(), activity, duration, duration_seconds,
                        distance, heart_rate, effort, cardio_notes.strip(),
                        brasilia_now().isoformat(timespec="microseconds"),
                    ),
                )
                db.commit()
                try:
                    save_wellness_to_github(github_config, db)
                except (OSError, RuntimeError, ValueError, KeyError) as error:
                    st.warning(f"Saved locally, but the GitHub backup failed: {error}")
                else:
                    st.success("Cardio workout saved.")

    cardio_log = read_cardio_log(db)
    if cardio_log.empty:
        st.info("Your cardio totals and trends will appear after the first workout.")
    else:
        cardio_log["performed_on"] = pd.to_datetime(cardio_log["performed_on"])
        cardio_log["duration_seconds"] = cardio_log["duration_seconds"].fillna(
            cardio_log["duration_minutes"] * 60
        )
        cardio_log["Pace (min/km)"] = cardio_log.apply(
            lambda row: row["duration_seconds"] / 60 / row["distance_km"]
            if pd.notna(row["distance_km"]) and row["distance_km"] > 0 else None,
            axis=1,
        )
        k1, k2, k3 = st.columns(3)
        k1.metric("Workouts", len(cardio_log))
        k2.metric("Total time", f"{cardio_log['duration_seconds'].sum() / 3600:.1f} h")
        k3.metric("Total distance", f"{cardio_log['distance_km'].sum():.1f} km")
        weekly_cardio = (
            cardio_log.assign(
                week=cardio_log["performed_on"].dt.to_period("W-SUN").dt.start_time
            ).groupby("week").agg(
                **{"Seconds": ("duration_seconds", "sum"), "Distance (km)": ("distance_km", "sum")}
            )
        )
        weekly_cardio["Minutes"] = weekly_cardio["Seconds"] / 60
        st.subheader("Weekly cardio time")
        st.bar_chart(weekly_cardio[["Minutes"]], x_label="Week", y_label="Minutes")
        cardio_display = cardio_log.rename(columns={
            "performed_on": "Date", "activity": "Activity",
            "distance_km": "Distance (km)",
            "average_heart_rate": "Avg HR", "effort": "Effort", "notes": "Notes",
        })
        cardio_display["Duration"] = cardio_display["duration_seconds"].map(
            format_precise_duration
        )
        cardio_display["Pace (min/km)"] = cardio_display["Pace (min/km)"].round(2)
        st.dataframe(
            cardio_display[["Date", "Activity", "Duration", "Distance (km)", "Pace (min/km)", "Avg HR", "Effort", "Notes"]],
            width="stretch", hide_index=True,
        )
        delete_cardio = st.selectbox(
            "Delete cardio workout", cardio_log["id"].tolist(),
            format_func=lambda row_id: (
                f"{cardio_log.loc[cardio_log['id'] == row_id, 'performed_on'].iloc[0]:%d %b %Y} · "
                f"{cardio_log.loc[cardio_log['id'] == row_id, 'activity'].iloc[0]}"
            ),
        )
        if st.button("Delete selected cardio workout"):
            db.execute("DELETE FROM cardio_log WHERE id = ?", (int(delete_cardio),))
            db.commit()
            save_wellness_to_github(github_config, db)
            st.rerun()

st.divider()
st.caption(
    "Training guidance is educational, not medical advice. Stop if you feel sharp pain, "
    "and ask a qualified professional if an exercise causes persistent discomfort."
)
st.caption(
    "Exercise photos: Free Exercise DB (public domain / Unlicense). "
    "Some machine exercises use the closest available movement illustration."
)
db.close()
