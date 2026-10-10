# agent/memory

Hermes keeps its own agent state under `$HERMES_HOME` (defaults to `~/.hermes`
on POSIX and `%LOCALAPPDATA%\hermes` on Windows), **not** in this directory.

This placeholder exists because the project layout lists `agent/memory/` as the
location for snapshot-able agent state. Putting a Hermes memory store here would
be wrong: Hermes would never read it, and a checked-in store could capture
identifiers from a real session.

What to do instead:

* point `HERMES_HOME` at a directory outside the repository (see
  `agent/hermes.env.example`), and snapshot *that* directory;
* never commit a memory snapshot — a Haven session's memory can legitimately
  contain identifiers that are marked high-sensitivity in
  `src/haven/models.py`;
* if a snapshot is ever attached as demo evidence, treat it the way the
  dashboard treats the family card: synthetic seed data only, and nothing from
  `src/haven/seed.py` replaced with real values.
