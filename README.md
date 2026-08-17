# My Training Path

A local Streamlit app for a five-day exercise plan, exercise alternatives,
and set-by-set workout progress tracking.

The starter plan follows a Push / Pull / Legs / Upper / Lower routine scheduled
for Monday, Tuesday, Wednesday, Friday, and Saturday, including its beginner set and
repetition targets. Every exercise and alternative can be edited in the app.

Progress features include exercise strength trends, set-by-set comparisons,
double-progression guidance, weekly adherence, editable muscle-group volume,
RIR and pain monitoring, personal records, and CSV export.

The app also includes a Wednesday body check-in for weight and optional tape
measurements (waist, hips, chest, thigh, upper arm, and neck), plus a cardio log
for walking, running, cycling, treadmill, and stationary-bike workouts. These
tabs show weight and circumference trends, weekly cardio time, total distance,
and pace when distance is recorded.

Exercise demonstration photos are displayed in both Today and My Plan. They are
sourced from the public-domain
[Free Exercise DB](https://github.com/yuhonas/free-exercise-db); details are in
`assets/exercises/ATTRIBUTION.md`.

## Run

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

If the Windows `python` alias does not point to your Python installation, use:

```powershell
& 'C:\Users\Pedro\AppData\Local\Programs\Python\Python312\python.exe' -m streamlit run app.py
```

The editable plan is saved to `data/workout_plan.json`. Progress is stored
locally in `data/progress.db`, and can also be downloaded from the app as CSV.
Durable CSV snapshots use `data/workout_progress.csv`, `data/body_progress.csv`,
and `data/cardio_progress.csv`.

## Persistent GitHub history

The app can use `data/workout_progress.csv` as a durable GitHub backup. At
startup it restores the progress CSVs into SQLite, and after every save or
deletion it commits updated CSV snapshots through the GitHub API.

Add these secrets in the Streamlit Community Cloud app settings:

```toml
GITHUB_TOKEN = "your-fine-grained-personal-access-token"
GITHUB_HISTORY_REPO = "Cazelli/App_academia_caminhadas"
GITHUB_HISTORY_BRANCH = "main"
```

The token needs **Contents: Read and write** access to the selected repository.
Do not commit the token or place it in this repository. This repository is
public, so its CSV history will also be public. To keep workout history private,
set `GITHUB_HISTORY_REPO` to a separate private repository instead.

When the same repository is used, running `git pull` locally retrieves the
latest `data/workout_progress.csv`. The SQLite database remains ignored because
it is only the app's working copy.
