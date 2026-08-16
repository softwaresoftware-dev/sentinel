"""`sentinel new <name>` — generate a watcher package from the templates, wire pyproject/systemd/brief/agent."""
from __future__ import annotations
import json, os, re, subprocess, sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TEMPLATES = Path(__file__).resolve().parent / "template"


def new(name: str, title: str | None = None, emoji: str = "🔔", enable: bool = True) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,30}", name):
        sys.exit("name must be a short lowercase python identifier, e.g. draftwatch")
    pkg = REPO / name
    if pkg.exists():
        sys.exit(f"{pkg} already exists")
    title = title or name.replace("watch", "").replace("_", " ").title() or name
    subs = {"{{name}}": name, "{{UPPER}}": name.upper(), "{{Title}}": title, "{{Emoji}}": emoji}
    pkg.mkdir()
    (pkg / "__init__.py").write_text(f'"""{name} — sentinel watcher: {title}."""\n')
    for t in TEMPLATES.glob("*.tmpl"):
        s = t.read_text()
        for k, v in subs.items(): s = s.replace(k, v)
        (pkg / t.name[:-5]).write_text(s)
    # pyproject: script + package
    pp = REPO / "pyproject.toml"; s = pp.read_text()
    s = s.replace('sentinel = "sentinel.cli:main"', f'sentinel = "sentinel.cli:main"\n{name} = "{name}.cli:main"')
    s = re.sub(r'packages = \[([^\]]*)\]', lambda m: f'packages = [{m.group(1)}, "{name}"]', s, count=1)
    pp.write_text(s)
    # config
    cdir = Path.home() / ".config" / name; cdir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not (cdir / "config.json").exists(): (cdir / "config.json").write_text("{}\n")
    # daemon registration is done by the `sentinel:new` skill through the daemon capability (cross-platform);
    # `sentinel daemons` prints the exact command lines to register.
    # register in the combined brief + tell the SMS agent about the new CLI
    scfg = Path.home() / ".config" / "sentinel" / "config.json"
    c = json.loads(scfg.read_text()) if scfg.exists() else {}
    briefs = c.setdefault("extra_briefs", [])
    entry = f"{name}.engine:brief_text"
    if entry not in briefs: briefs.append(entry)
    tools = c.setdefault("agent_extra_tools", [])
    note = f"`{name} items|status|brief` ({title})"
    if note not in tools: tools.append(note)
    scfg.write_text(json.dumps(c, indent=2) + "\n")
    # install
    subprocess.run(["uv", "sync", "--reinstall-package", "sentinel", "-q"], cwd=REPO, check=False)
    ln = Path.home() / ".local" / "bin" / name
    try:
        if ln.is_symlink() or ln.exists(): ln.unlink()
        ln.symlink_to(REPO / ".venv" / "bin" / name)
    except Exception as e:
        print("symlink:", e)
    print(f"""created {pkg}
next:
  1. edit {pkg}/source.py  → fetch(), alert(), brief()
  2. put settings in ~/.config/{name}/config.json (merged over DEFAULTS in config.py)
  3. {name} items            # see what fetch() returns
     {name} once --dry-run   # first run = silent baseline; second run alerts on new items
     {name} brief            # this watcher's section
     sentinel brief          # the combined morning text now includes it
  4. register the daemon (see `sentinel daemons` for the command line) and restart the sentinel daemon so the agent learns the new CLI
""")


def remove(name: str, purge_data: bool = False) -> None:
    import shutil
    if name in ("calwatch", "mailwatch", "ghwatch", "slackwatch", "sentinel"):
        sys.exit("refusing to remove a core package")
    print(f"(if you registered a daemon for {name}, remove its autostart via the daemon capability)")
    pkg = REPO / name
    if pkg.exists(): shutil.rmtree(pkg)
    pp = REPO / "pyproject.toml"; s = pp.read_text()
    s = s.replace(f'\n{name} = "{name}.cli:main"', "").replace(f', "{name}"', "")
    pp.write_text(s)
    scfg = Path.home() / ".config" / "sentinel" / "config.json"
    if scfg.exists():
        c = json.loads(scfg.read_text())
        c["extra_briefs"] = [b for b in c.get("extra_briefs", []) if not b.startswith(f"{name}.")]
        c["agent_extra_tools"] = [t for t in c.get("agent_extra_tools", []) if not t.startswith(f"`{name} ")]
        scfg.write_text(json.dumps(c, indent=2) + "\n")
    ln = Path.home() / ".local" / "bin" / name
    if ln.is_symlink(): ln.unlink()
    if purge_data:
        shutil.rmtree(Path.home() / ".config" / name, ignore_errors=True)
        shutil.rmtree(Path.home() / ".local" / "share" / name, ignore_errors=True)
    subprocess.run(["uv", "sync", "--reinstall-package", "sentinel", "-q"], cwd=REPO, check=False)
    print(f"removed {name}" + (" (+ config/data)" if purge_data else " (config/data kept; --purge to delete)"))
