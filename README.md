# Listening room

A Python audio library with SQLite storage. Requires Python 3.10+.

```sh
python3 app.py     # Run on http://localhost:8000
uv run dev.py     # Development with automatic restarts
```

- `/listening`: listen once, or replay and seek freely when the teacher enables full access. Space toggles playback; arrow keys skip 5 seconds with full access.
- `/teacher`: upload, rename, show/hide, configure access, and delete audio. Password: `HAIDOHONG` (override with `TEACHER_PASSWORD`).

Audio lives in `audio/`; metadata lives in `listening.sqlite3`. Both are ignored by Git. Teacher visibility/access changes reset saved listening progress. Playback limits use localStorage; they do not prevent audio capture. Use HTTPS when deploying.

Run tests: `python3 -m unittest discover -s tests`.
