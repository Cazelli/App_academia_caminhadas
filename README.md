# My Training Path

A local Streamlit app for a Monday–Friday exercise plan, exercise alternatives,
and workout progress tracking.

The starter plan follows the complete Upper / Lower / Push / Pull / Legs routine
in `data/Workout Split Monday to Friday.pdf`, including its beginner set and
repetition targets. Every exercise and alternative can be edited in the app.

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
