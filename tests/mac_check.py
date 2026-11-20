"""Prova del Post-it su macOS (usata da GitHub Actions).

    python3 tests/mac_check.py PostIt.pyw cartella_screenshot

Avvia l'app con dati di esempio in una cartella home temporanea, fa gli screenshot dei
tre post-it e dei riquadri, controlla scorciatoie globali, istanza unica e avvio al
login. Esce con codice 1 se qualcosa di importante non va.
"""
import json
import os
import subprocess
import sys
import tempfile
import types

src, shots = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
os.makedirs(shots, exist_ok=True)
os.environ["HOME"] = tempfile.mkdtemp(prefix="postit-home-")
app_dir = os.path.join(os.environ["HOME"], "Library", "Application Support", "PostIt")
os.makedirs(app_dir)
demo = {
    "current": "yellow", "topmost": True, "geometry": "320x420+120+120",
    "notes": {
        "yellow": {"text": "", "todos": [
            {"text": "Lavoro", "done": False, "h": 2},
            {"text": "Rispondere alle email", "done": True},
            {"text": "*Preparare la presentazione*", "done": False},
            {"text": "Chiamare il fornitore", "done": False},
            {"text": "Casa", "done": False, "h": 2},
            {"text": "Spesa per il weekend", "done": False},
            {"text": "Prenotare il dentista", "done": True}]},
        "green": {"text": "# Idee\nUn post-it per *ogni progetto*\n- colori diversi\n- scorciatoie",
                  "todos": [{"text": "Provare la versione Mac", "done": False},
                            {"text": "Scrivere il README", "done": True}]},
        "blue": {"text": "# Riunione\n## Punti\n1. Budget _trimestrale_\n2. Nuovo sito\n"
                         "- chiedere *preventivi*\n- fissare la data", "todos": []},
    }}
with open(os.path.join(app_dir, "postit.json"), "w", encoding="utf-8") as f:
    json.dump(demo, f)

mod = types.ModuleType("postit")
mod.__file__ = src
exec(compile(open(src, encoding="utf-8").read(), "PostIt.pyw", "exec"), mod.__dict__)
results, problems = {}, []


def check(name, cond, critical=True):
    results[name] = bool(cond)
    if not cond and critical:
        problems.append(name)
    print(("OK   " if cond else "FAIL ") + name, flush=True)


check("istanza unica: primo avvio", mod.signal_existing_instance() is False)
app = mod.PostItApp()
app.root.update()


def shot(name, win=None, pad=40):
    win = win or app.root
    win.update()
    x, y = win.winfo_rootx(), win.winfo_rooty()
    w, h = win.winfo_width(), win.winfo_height()
    region = "%d,%d,%d,%d" % (max(0, x - pad), max(0, y - pad - 28), w + 2 * pad, h + 2 * pad + 28)
    subprocess.run(["screencapture", "-x", "-R" + region, os.path.join(shots, name)])


def post_hotkey(keycode, flags):
    """Simula ⌃⌥ + tasto come se lo premesse l'utente (se il sistema lo permette)."""
    import ctypes
    q = ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
    q.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
    q.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
    q.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
    q.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    for down in (True, False):
        ev = q.CGEventCreateKeyboardEvent(None, keycode, down)
        q.CGEventSetFlags(ev, flags)
        q.CGEventPost(0, ev)


def s_start():
    app.activate()
    check("font di sistema", mod.UI_FONT[0] not in ("Segoe UI", ""), critical=False)
    print("font:", mod.UI_FONT, "Tk", app.root.tk.call("info", "patchlevel"), flush=True)
    check("scorciatoie globali registrate", not app.failed)
    shot("1-giallo.png")


def s_green():
    app.switch("green")
    shot("2-verde.png")


def s_blue():
    app.switch("blue")
    shot("3-azzurro.png")


def s_settings():
    app.switch("yellow")
    mod.SettingsPanel(app, app.title_lbl)


def s_settings_shot():
    shot("4-impostazioni.png", app.popup.win)
    app.close_popup()
    mod.ExportMenu(app, app.title_lbl)


def s_export_shot():
    shot("5-esporta.png", app.popup.win)
    app.close_popup()


def s_hotkey_send():
    app.data["current"] = "yellow"
    app.render()
    app.hide_window()
    post_hotkey(20, 0x40000 | 0x80000)   # ⌃⌥3


def s_hotkey_check():
    arrived = app.data["current"] == "blue" and not app.hidden
    check("scorciatoia ⌃⌥3 ricevuta (tasti simulati)", arrived, critical=False)
    if not arrived:
        app.activate()
    app.switch("yellow")


def s_second():
    app.hide_window()
    check("istanza unica: secondo avvio segnala il primo",
          mod.signal_existing_instance() is True)


def s_second_check():
    check("istanza unica: richiesta ricevuta", not app.hidden)
    check("avvio al login: attiva", mod.set_autostart(True) and mod.autostart_enabled())
    import plistlib
    with open(mod.LAUNCH_AGENT, "rb") as f:
        print("LaunchAgent:", plistlib.load(f)["ProgramArguments"], flush=True)
    check("avvio al login: disattiva", mod.set_autostart(False) and not mod.autostart_enabled())
    app.mode = "normal"
    app.set_mode("collapsed")
    shot("6-ridotto.png")
    app.set_mode("normal")


def s_save():
    app.toggle(1)
    app.save_now()
    with open(mod.DATA_FILE, encoding="utf-8") as f:
        saved = json.load(f)
    check("salvataggio", saved["notes"]["yellow"]["todos"][1]["done"] is False)
    app.quit()


steps = [s_start, s_green, s_blue, s_settings, s_settings_shot, s_export_shot,
         s_hotkey_send, s_hotkey_check, s_second, s_second_check, s_save]


def run(i=0):
    try:
        steps[i]()
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        problems.append("%s: %r" % (steps[i].__name__, exc))
    if i < len(steps) - 1:
        app.root.after(900, run, i + 1)


app.root.after(1500, run)
app.root.after(110000, lambda: (problems.append("tempo scaduto"), app.root.destroy()))
app.run()
log = os.path.join(app_dir, "postit.log")
if os.path.exists(log):
    print("--- postit.log\n" + open(log, encoding="utf-8").read(), flush=True)
with open(os.path.join(shots, "risultati.json"), "w") as f:
    json.dump({"results": results, "problems": problems}, f, indent=2)
print("PROBLEMI:", problems or "nessuno")
sys.exit(1 if problems else 0)
