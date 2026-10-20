# Listening room

A Python audio library with SQLite storage. Requires Python 3.10+.

```sh
python3 app.py     # Run on http://localhost:8000
uv run dev.py     # Development with automatic restarts
```

The server accepts external connections on all interfaces by default. Other devices can open `http://<your-computer-ip>:8000/listening`. Use `--host 127.0.0.1` for local-only access or `--port 8080` to change the port (also supported by `uv run dev.py`).

The server shuts down automatically after **2 hours**. Use `python3 app.py --duration 60` for one hour, or `--duration 0` to disable automatic shutdown. Duration is in minutes and starts when the server starts. During development, each automatic restart starts a new timer; the watcher stays running after the server stops.

- `/listening`: listen once, or replay and seek freely when the teacher enables full access. Space toggles playback; arrow keys skip 5 seconds with full access.
- `/teacher`: upload, rename, show/hide, configure access, and delete audio. Password: `HAIDOHONG` (override with `TEACHER_PASSWORD`).

Audio lives in `audio/`; metadata lives in `listening.sqlite3`. Both are ignored by Git. Teacher visibility/access changes reset saved listening progress. Playback limits use localStorage; they do not prevent audio capture. Use HTTPS when deploying.

Run tests: `python3 -m unittest discover -s tests`.
