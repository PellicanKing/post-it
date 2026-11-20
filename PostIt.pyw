# -*- coding: utf-8 -*-
"""
Post-it — todo list e note sempre a portata di mano (Windows 10/11 e macOS).

  Giallo  = solo Todo
  Verde   = Note + Todo
  Azzurro = solo Note

Scorciatoie predefinite (attive anche mentre usi altri programmi,
personalizzabili dal simbolo ⌨ in basso a destra; su Mac Ctrl+Alt = ⌃⌥, Ctrl+B = ⌘B):
  Ctrl+Alt+N      scrivi subito (premuta di nuovo: nasconde)
  Ctrl+Alt+P      fisso sopra tutto / non fisso
  Ctrl+Alt+H      nascondi / mostra
  Ctrl+Alt+G      riduci a barra / espandi (+ versione grande, se attivata)
  Ctrl+Alt+1/2/3  apri il post-it giallo / verde / azzurro
                  (premuta di nuovo: l'altro post-it dello stesso colore)
Sul post-it:
  1 / 2 / 3       cambia post-it (quando non stai scrivendo); di nuovo lo stesso
                  numero o clic sul colore già aperto = l'altro dei due
  Invio o lettere inizia a scrivere      Esc  smetti di scrivere
Nelle note:
  # / ## / ### + spazio   titolo grande / medio / piccolo
  - + spazio              elenco puntato     3. + spazio  elenco numerato (da 3)
  Tab o un secondo spazio subito dopo: annulla e lascia il testo com'era
  *testo* o Ctrl+B        grassetto          _testo_ o Ctrl+I  corsivo
Nelle liste todo: "# Titolo" crea un titolo di sezione; *attività* in grassetto.

Avvio: doppio clic su questo file (serve Python 3) oppure PostIt.exe / Post-it.app.
I dati sono salvati in %APPDATA%\\PostIt (Windows) o ~/Library/Application Support/PostIt
(Mac), insieme a postit.log, il registro di avvii ed errori.
"""
import ctypes
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
from tkinter import font as tkfont, messagebox

VERSION = "1.3"
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

# ---------------------------------------------------------------- percorsi
APP_ID = "PostIt.Note"
if IS_WIN:
    APP_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "PostIt")
elif IS_MAC:
    APP_DIR = os.path.expanduser("~/Library/Application Support/PostIt")
else:
    APP_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                           "PostIt")
DATA_FILE = os.path.join(APP_DIR, "postit.json")
LOG_FILE = os.path.join(APP_DIR, "postit.log")
BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
ICON_FILE = os.path.join(BASE_DIR, "postit.ico")


# ---------------------------------------------------------------- registro
def log(msg):
    """Annota avvii, chiusure ed errori in postit.log (utile se qualcosa non va)."""
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 200_000:
            os.replace(LOG_FILE, LOG_FILE + ".old")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except OSError:
        pass


def log_error(where, exc=None):
    exc = exc or sys.exc_info()[1]
    log("ERRORE in %s:\n%s" % (where, "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip()))


# ---------------------------------------------------------------- post-it
NOTES = {
    "yellow": dict(label="Giallo", name="Todo", bg="#fff59d", head="#fbe044",
                   ink="#4a3f00", soft="#a8994a", todo=True, notes=False),
    "green": dict(label="Verde", name="Note + Todo", bg="#d4edb5", head="#a5d46a",
                  ink="#24400c", soft="#7d9a5c", todo=True, notes=True),
    "blue": dict(label="Azzurro", name="Note", bg="#c7eafc", head="#7fd0f5",
                 ink="#0b3550", soft="#6a9ab4", todo=False, notes=True),
}
ORDER = ["yellow", "green", "blue"]


def note_id(color, page):
    """Ogni colore ha due post-it: "yellow" (1°) e "yellow2" (2°)."""
    return color + "2" if page else color


def note_color(nid):
    return nid[:-1] if nid.endswith("2") else nid


NOTE_IDS = [note_id(c, p) for c in ORDER for p in (0, 1)]
FAINT = "#a9a9a9"
WARN = "#c62828"
MAC_GREEN = "#34c759"   # verde degli interruttori di macOS

# ---------------------------------------------------------------- scorciatoie
if IS_MAC:
    # modificatori Carbon e codici dei tasti (posizione sulla tastiera, come su macOS)
    MOD_CMD, MOD_SHIFT, MOD_ALT, MOD_CONTROL = 0x100, 0x200, 0x800, 0x1000
    KEYCODES = dict(zip("ASDFHGZXCV", (0, 1, 2, 3, 4, 5, 6, 7, 8, 9)))
    KEYCODES.update(B=11, Q=12, W=13, E=14, R=15, Y=16, T=17, O=31, U=32, I=34, P=35,
                    L=37, J=38, K=40, N=45, M=46)
    KEYCODES.update({"1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "9": 25,
                     "7": 26, "8": 28, "0": 29, "space": 49, "Return": 36, "Tab": 48,
                     "Left": 123, "Right": 124, "Down": 125, "Up": 126})
    KEYCODES.update({"F%d" % (i + 1): c for i, c in enumerate(
        (122, 120, 99, 118, 96, 97, 98, 100, 101, 109, 103, 111))})
    KEY_NAMES = {c: k for k, c in KEYCODES.items()}
    KEY_NAMES.update({49: "Spazio", 36: "↩", 48: "⇥", 123: "←", 124: "→", 125: "↓", 126: "↑"})

    def key_code(ch):
        return KEYCODES[ch]
else:
    MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_CMD = 0x1, 0x2, 0x4, 0x8

    def key_code(ch):
        return ord(ch)
MOD_NOREPEAT = 0x4000
CA = MOD_CONTROL | MOD_ALT   # Ctrl+Alt su Windows, ⌃⌥ su Mac
ACTIONS = [  # (azione, descrizione, combinazione predefinita)
    ("write", "Scrivi subito (di nuovo = nascondi)", (CA, key_code("N"))),
    ("pin", "Fisso sopra tutto / non fisso", (CA, key_code("P"))),
    ("hide", "Nascondi / mostra", (CA, key_code("H"))),
    ("expand", "Riduci / espandi", (CA, key_code("G"))),
    ("note:yellow", "Apri giallo (di nuovo: l'altro giallo)", (CA, key_code("1"))),
    ("note:green", "Apri verde (di nuovo: l'altro verde)", (CA, key_code("2"))),
    ("note:blue", "Apri azzurro (di nuovo: l'altro azzurro)", (CA, key_code("3"))),
]
ACTION_TEXT = {a: t for a, t, _ in ACTIONS}
DEFAULT_KEYS = {a: list(k) for a, _, k in ACTIONS}
MODIFIER_KEYSYMS = {"Control_L", "Control_R", "Alt_L", "Alt_R", "Shift_L", "Shift_R",
                    "Win_L", "Win_R", "Super_L", "Super_R", "Caps_Lock", "Num_Lock",
                    "ISO_Level3_Shift", "App", "Meta_L", "Meta_R", "Option_L", "Option_R"}

# ---------------------------------------------------------------- Windows
if IS_WIN:
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    HWND, HANDLE, UINT, DWORD = wintypes.HWND, wintypes.HANDLE, wintypes.UINT, wintypes.DWORD

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", DWORD)]

    for fn, args, res in [
        (user32.GetParent, [HWND], HWND),
        (user32.GetForegroundWindow, [], HWND),
        (user32.GetWindowThreadProcessId, [HWND, ctypes.c_void_p], DWORD),
        (user32.AttachThreadInput, [DWORD, DWORD, wintypes.BOOL], wintypes.BOOL),
        (user32.BringWindowToTop, [HWND], wintypes.BOOL),
        (user32.SetForegroundWindow, [HWND], wintypes.BOOL),
        (user32.GetWindowLongW, [HWND, ctypes.c_int], ctypes.c_long),
        (user32.SetWindowLongW, [HWND, ctypes.c_int, ctypes.c_long], ctypes.c_long),
        (user32.RegisterHotKey, [HWND, ctypes.c_int, UINT, UINT], wintypes.BOOL),
        (user32.UnregisterHotKey, [HWND, ctypes.c_int], wintypes.BOOL),
        (user32.GetMessageW, [ctypes.POINTER(wintypes.MSG), HWND, UINT, UINT], wintypes.BOOL),
        (user32.PeekMessageW, [ctypes.POINTER(wintypes.MSG), HWND, UINT, UINT, UINT],
         wintypes.BOOL),
        (user32.PostThreadMessageW, [DWORD, UINT, wintypes.WPARAM, wintypes.LPARAM],
         wintypes.BOOL),
        (user32.MapVirtualKeyW, [UINT, UINT], UINT),
        (user32.GetKeyNameTextW, [ctypes.c_long, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
        (user32.MonitorFromPoint, [wintypes.POINT, DWORD], HANDLE),
        (user32.GetMonitorInfoW, [HANDLE, ctypes.POINTER(MONITORINFO)], wintypes.BOOL),
        (kernel32.GetCurrentThreadId, [], DWORD),
        (kernel32.CreateMutexW, [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR], HANDLE),
        (kernel32.CreateEventW, [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL,
                                 wintypes.LPCWSTR], HANDLE),
        (kernel32.SetEvent, [HANDLE], wintypes.BOOL),
        (kernel32.WaitForSingleObject, [HANDLE, DWORD], DWORD),
    ]:
        fn.argtypes, fn.restype = args, res

    def work_area(x, y):
        """(sinistra, alto, destra, basso) dello schermo più vicino al punto,
        senza la barra delle applicazioni."""
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(mi)
        mon = user32.MonitorFromPoint(wintypes.POINT(int(x), int(y)), 2)  # il più vicino
        if mon and user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
            r = mi.rcWork
            return r.left, r.top, r.right, r.bottom
        return 0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)

    def vk_name(vk):
        if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
            return chr(vk)
        if 0x70 <= vk <= 0x87:
            return "F%d" % (vk - 0x6F)
        if 0x60 <= vk <= 0x69:
            return "Num%d" % (vk - 0x60)
        named = {0x20: "Spazio", 0x0D: "Invio", 0x09: "Tab", 0x2D: "Ins", 0x2E: "Canc",
                 0x24: "Home", 0x23: "Fine", 0x21: "PagSu", 0x22: "PagGiù",
                 0x25: "←", 0x26: "↑", 0x27: "→", 0x28: "↓"}
        if vk in named:
            return named[vk]
        buf = ctypes.create_unicode_buffer(32)
        if user32.GetKeyNameTextW(user32.MapVirtualKeyW(vk, 0) << 16, buf, 32):
            return buf.value
        return "VK%d" % vk

    RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    RUN_NAME = "PostIt"

    def autostart_command():
        """Comando che Windows esegue all'accesso (exe oppure pythonw + script)."""
        if getattr(sys, "frozen", False):
            return '"%s" --autostart' % sys.executable
        exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(exe):
            exe = sys.executable
        return '"%s" "%s" --autostart' % (exe, os.path.abspath(__file__))

    def autostart_enabled():
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                winreg.QueryValueEx(k, RUN_NAME)
            return True
        except OSError:
            return False

    def set_autostart(on):
        """Aggiunge o toglie il Post-it dai programmi che partono all'accesso a Windows."""
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                if on:
                    winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, autostart_command())
                else:
                    try:
                        winreg.DeleteValue(k, RUN_NAME)
                    except FileNotFoundError:
                        pass
            return True
        except OSError:
            return False

    def documents_dir():
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:
            return buf.value
        return os.path.join(os.path.expanduser("~"), "Documents")

    def open_path(path):
        os.startfile(path)

    _MUTEX = None

    def signal_existing_instance():
        """True se il Post-it è già aperto: in quel caso gli chiede di mostrarsi."""
        global _MUTEX
        ctypes.set_last_error(0)
        _MUTEX = kernel32.CreateMutexW(None, False, "PostIt.SingleInstance")
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            ev = kernel32.CreateEventW(None, False, False, "PostIt.Show")
            if ev:
                kernel32.SetEvent(ev)
            return True
        return False

    def listen_show_requests(events):
        ev = kernel32.CreateEventW(None, False, False, "PostIt.Show")
        while ev:
            r = kernel32.WaitForSingleObject(ev, 0xFFFFFFFF)
            if r == 0:
                events.put(("show", None))
            elif r == 0xFFFFFFFF:   # attesa fallita: meglio smettere che girare a vuoto
                log("attesa delle richieste di apertura interrotta")
                return

    class HotkeyThread(threading.Thread):
        """Registra le scorciatoie in Windows: le combinazioni arrivano solo al Post-it,
        non agli altri programmi. Le registrazioni vivono in questo thread."""
        WM_HOTKEY, WM_RELOAD, WM_SUSPEND = 0x0312, 0x8001, 0x8002

        def __init__(self, events, bindings):
            super().__init__(daemon=True)
            self.events, self.bindings = events, dict(bindings)
            self.ids, self.tid, self.ready = {}, 0, threading.Event()

        def run(self):
            self.tid = kernel32.GetCurrentThreadId()
            msg = wintypes.MSG()
            user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # crea la coda messaggi
            self.ready.set()
            self._register()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == self.WM_HOTKEY and msg.wParam in self.ids:
                    self.events.put(("hotkey", self.ids[msg.wParam]))
                elif msg.message == self.WM_RELOAD:
                    self._unregister()
                    self._register()
                elif msg.message == self.WM_SUSPEND:
                    self._unregister()

        def _register(self):
            failed = []
            for i, (action, (mods, vk)) in enumerate(sorted(self.bindings.items()), start=1):
                if user32.RegisterHotKey(None, i, mods | MOD_NOREPEAT, vk):
                    self.ids[i] = action
                else:
                    failed.append(action)
            self.events.put(("status", failed))

        def _unregister(self):
            for i in self.ids:
                user32.UnregisterHotKey(None, i)
            self.ids.clear()

        def _post(self, message):
            if self.ready.wait(2):
                user32.PostThreadMessageW(self.tid, message, 0, 0)

        def reload(self, bindings):
            self.bindings = dict(bindings)
            self._post(self.WM_RELOAD)

        def suspend(self):
            self._post(self.WM_SUSPEND)

    def make_hotkeys(events, bindings):
        h = HotkeyThread(events, bindings)
        h.start()
        return h

# ---------------------------------------------------------------- macOS e altri sistemi
else:
    _SCREEN = [0, 0, 1440, 900]   # area utile, aggiornata da PostItApp con le misure vere

    def work_area(_x, _y):
        return tuple(_SCREEN)

    def documents_dir():
        return os.path.join(os.path.expanduser("~"), "Documents")

    def open_path(path):
        subprocess.Popen(["open" if IS_MAC else "xdg-open", path])

    # un solo Post-it aperto: il secondo avvio chiede al primo di mostrarsi
    # nella cartella temporanea dell'utente: i percorsi dei socket hanno un limite di lunghezza
    import tempfile
    SOCKET_FILE = os.path.join(tempfile.gettempdir(), "postit-%d.sock" % os.getuid())
    if len(SOCKET_FILE) > 100:
        SOCKET_FILE = "/tmp/postit-%d.sock" % os.getuid()
    _SERVER = None

    def signal_existing_instance():
        global _SERVER
        import socket
        try:
            os.makedirs(APP_DIR, exist_ok=True)
            s = socket.socket(socket.AF_UNIX)
            try:
                s.connect(SOCKET_FILE)
                s.sendall(b"show")
                return True
            except OSError:
                pass
            finally:
                s.close()
            if os.path.exists(SOCKET_FILE):
                os.unlink(SOCKET_FILE)
            _SERVER = socket.socket(socket.AF_UNIX)
            _SERVER.bind(SOCKET_FILE)
            _SERVER.listen(4)
        except OSError:
            log_error("controllo istanza unica")
            _SERVER = None
        return False

    def listen_show_requests(events):
        while _SERVER is not None:
            try:
                conn, _addr = _SERVER.accept()
            except OSError:
                return
            conn.close()
            events.put(("show", None))

    if IS_MAC:
        LAUNCH_AGENT = os.path.expanduser("~/Library/LaunchAgents/it.postit.note.plist")

        def autostart_args():
            if getattr(sys, "frozen", False):
                app = os.path.abspath(os.path.join(os.path.dirname(sys.executable), "..", ".."))
                if app.endswith(".app"):
                    return ["/usr/bin/open", "-a", app, "--args", "--autostart"]
                return [sys.executable, "--autostart"]
            return [sys.executable, os.path.abspath(__file__), "--autostart"]

        def autostart_enabled():
            return os.path.exists(LAUNCH_AGENT)

        def set_autostart(on):
            """Avvio all'accesso a macOS tramite un LaunchAgent dell'utente."""
            import plistlib
            try:
                if on:
                    os.makedirs(os.path.dirname(LAUNCH_AGENT), exist_ok=True)
                    with open(LAUNCH_AGENT, "wb") as f:
                        plistlib.dump({"Label": "it.postit.note", "RunAtLoad": True,
                                       "ProgramArguments": autostart_args(),
                                       "ProcessType": "Interactive"}, f)
                elif os.path.exists(LAUNCH_AGENT):
                    os.remove(LAUNCH_AGENT)
                return True
            except OSError:
                return False

        _OBJC = None

        def objc_call(obj, sel, restype=ctypes.c_void_p, argtypes=(), *args):
            """Chiamata minima all'Objective-C (per portare l'app in primo piano)."""
            global _OBJC
            import ctypes.util
            if _OBJC is None:
                _OBJC = ctypes.CDLL(ctypes.util.find_library("objc"))
                _OBJC.objc_getClass.restype = ctypes.c_void_p
                _OBJC.objc_getClass.argtypes = [ctypes.c_char_p]
                _OBJC.sel_registerName.restype = ctypes.c_void_p
                _OBJC.sel_registerName.argtypes = [ctypes.c_char_p]
            if isinstance(obj, bytes):
                obj = _OBJC.objc_getClass(obj)
            addr = ctypes.cast(_OBJC.objc_msgSend, ctypes.c_void_p).value
            f = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes)(addr)
            return f(obj, _OBJC.sel_registerName(sel), *args)

        def mac_app(method, restype=None, argtypes=(), *args):
            try:
                nsapp = objc_call(b"NSApplication", b"sharedApplication")
                return objc_call(nsapp, method, restype, argtypes, *args)
            except Exception:  # noqa: BLE001 — una funzione in meno, non un crash
                log_error("macOS " + method.decode())
                return None

        class MacHotkeys:
            """Scorciatoie globali su macOS con RegisterEventHotKey (Carbon): funzionano
            senza permessi di Accessibilità e non arrivano alle altre app."""

            def __init__(self, events, bindings):
                from ctypes import c_uint32, c_void_p, POINTER, Structure, byref
                self.events, self.bindings, self.refs = events, dict(bindings), {}

                class HotKeyID(Structure):
                    _fields_ = [("signature", c_uint32), ("id", c_uint32)]

                class EventTypeSpec(Structure):
                    _fields_ = [("eventClass", c_uint32), ("eventKind", c_uint32)]
                self.HotKeyID = HotKeyID
                c = self.carbon = ctypes.CDLL(
                    "/System/Library/Frameworks/Carbon.framework/Carbon")
                handler_t = ctypes.CFUNCTYPE(ctypes.c_int32, c_void_p, c_void_p, c_void_p)
                c.GetApplicationEventTarget.restype = c_void_p
                c.InstallEventHandler.argtypes = [c_void_p, handler_t, c_uint32,
                                                  POINTER(EventTypeSpec), c_void_p,
                                                  POINTER(c_void_p)]
                c.RegisterEventHotKey.argtypes = [c_uint32, c_uint32, HotKeyID, c_void_p,
                                                  c_uint32, POINTER(c_void_p)]
                c.UnregisterEventHotKey.argtypes = [c_void_p]
                c.GetEventParameter.argtypes = [c_void_p, c_uint32, c_uint32, c_void_p,
                                                ctypes.c_ulong, c_void_p, c_void_p]
                self.sig = int.from_bytes(b"PstI", "big")
                self._handler = handler_t(self._on_event)   # tenuto in vita qui
                spec = EventTypeSpec(int.from_bytes(b"keyb", "big"), 5)  # tasto premuto
                self._ref = c_void_p()
                c.InstallEventHandler(c.GetApplicationEventTarget(), self._handler, 1,
                                      byref(spec), None, byref(self._ref))
                self._register()

            def _on_event(self, _call, event, _data):
                try:
                    hk = self.HotKeyID()
                    self.carbon.GetEventParameter(
                        event, int.from_bytes(b"----", "big"), int.from_bytes(b"hkid", "big"),
                        None, ctypes.sizeof(hk), None, ctypes.byref(hk))
                    action = self.refs.get(hk.id, (None, None))[0]
                    if hk.signature == self.sig and action:
                        self.events.put(("hotkey", action))
                except Exception:  # noqa: BLE001
                    log_error("scorciatoia macOS")
                return 0

            def _register(self):
                failed = []
                target = self.carbon.GetApplicationEventTarget()
                for i, (action, (mods, code)) in enumerate(sorted(self.bindings.items()), 1):
                    ref = ctypes.c_void_p()
                    err = self.carbon.RegisterEventHotKey(code, mods, self.HotKeyID(self.sig, i),
                                                          target, 0, ctypes.byref(ref))
                    if err == 0:
                        self.refs[i] = (action, ref)
                    else:
                        failed.append(action)
                self.events.put(("status", failed))

            def _unregister(self):
                for _action, ref in self.refs.values():
                    self.carbon.UnregisterEventHotKey(ref)
                self.refs.clear()

            def reload(self, bindings):
                self.bindings = dict(bindings)
                self._unregister()
                self._register()

            def suspend(self):
                self._unregister()
    else:
        def autostart_enabled():
            return False

        def set_autostart(_on):
            return False

    class NoHotkeys:
        def __init__(self, events, bindings):
            self.events, self.bindings = events, bindings
            self.reload(bindings)

        def reload(self, bindings):
            self.events.put(("status", sorted(bindings)))

        def suspend(self):
            pass

    def make_hotkeys(events, bindings):
        if IS_MAC:
            try:
                return MacHotkeys(events, bindings)
            except Exception:  # noqa: BLE001
                log_error("scorciatoie macOS")
        return NoHotkeys(events, bindings)


def fit_rect(x, y, w, h, point=None):
    """Sposta (e se serve rimpicciolisce) il riquadro perché resti tutto sullo schermo."""
    left, top, right, bottom = work_area(*(point or (x + w // 2, y + min(h, 30) // 2)))
    w, h = min(w, right - left), min(h, bottom - top)
    return max(left, min(x, right - w)), max(top, min(y, bottom - h)), w, h


def combo_label(combo):
    mods, key = combo
    if IS_MAC:
        sym = "".join(s for m, s in ((MOD_CONTROL, "⌃"), (MOD_ALT, "⌥"), (MOD_SHIFT, "⇧"),
                                     (MOD_CMD, "⌘")) if mods & m)
        return sym + KEY_NAMES.get(key, "#%d" % key)
    parts = [n for m, n in ((MOD_CONTROL, "Ctrl"), (MOD_ALT, "Alt"), (MOD_SHIFT, "Maiusc"))
             if mods & m]
    return "+".join(parts + [vk_name(key)])


def event_combo(e):
    """Tasto premuto in Tk -> [modificatori, tasto] nel formato delle scorciatoie globali."""
    if IS_MAC:  # Tk su Mac: ⌘ = Mod1 (0x8), ⌥ = Mod2 (0x10); il codice tasto è nel byte alto
        mods = ((MOD_CONTROL if e.state & 0x4 else 0) | (MOD_ALT if e.state & 0x10 else 0)
                | (MOD_SHIFT if e.state & 0x1 else 0) | (MOD_CMD if e.state & 0x8 else 0))
        code = e.keycode >> 24 if e.keycode > 0xFFFFFF else None
        if code is None:
            ks = e.keysym.upper() if len(e.keysym) == 1 else e.keysym
            code = KEYCODES.get(ks)
        return [mods, code]
    mods = ((MOD_CONTROL if e.state & 0x4 else 0) | (MOD_ALT if e.state & 0x20000 else 0)
            | (MOD_SHIFT if e.state & 0x1 else 0))
    return [mods, e.keycode]


def combo_allowed(mods):
    """Serve almeno Ctrl/Alt (Windows) o ⌃/⌘ (Mac): da sola ⌥ è bloccata da macOS."""
    return bool(mods & (MOD_CONTROL | MOD_CMD)) if IS_MAC else bool(mods & CA)


# ---------------------------------------------------------------- dati
def default_data():
    return {"current": "yellow", "page": {k: 0 for k in ORDER},
            "topmost": True, "geometry": None, "large_mode": False,
            "hotkeys": {a: list(k) for a, k in DEFAULT_KEYS.items()},
            "notes": {k: {"text": "", "todos": []} for k in NOTE_IDS}}


def load_data():
    data = default_data()
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
    except FileNotFoundError:
        return data
    except (OSError, ValueError):
        log_error("lettura di postit.json")
        try:   # file rovinato: lo teniamo da parte invece di sovrascriverlo
            os.replace(DATA_FILE, DATA_FILE + ".rovinato-%d" % int(time.time()))
        except OSError:
            pass
        return data
    for key in ("current", "topmost", "geometry", "large_mode"):
        if key in saved:
            data[key] = saved[key]
    for action, combo in (saved.get("hotkeys") or {}).items():
        if action in DEFAULT_KEYS and isinstance(combo, list) and len(combo) == 2:
            try:
                combo = [int(combo[0]), int(combo[1])]
            except (TypeError, ValueError):
                continue
            if combo_allowed(combo[0]):
                data["hotkeys"][action] = combo
    for color, page in (saved.get("page") or {}).items():
        if color in NOTES and page in (0, 1):
            data["page"][color] = page
    for k in NOTE_IDS:
        note = (saved.get("notes") or {}).get(k) or {}
        data["notes"][k]["text"] = str(note.get("text", ""))
        todos = []
        for t in note.get("todos", []):
            if isinstance(t, dict):
                item = {"text": str(t.get("text", "")), "done": bool(t.get("done"))}
                if t.get("h") in (1, 2, 3):
                    item["h"] = t["h"]
                todos.append(item)
        data["notes"][k]["todos"] = todos
    if data["current"] not in NOTES:
        data["current"] = "yellow"
    return data


# ---------------------------------------------------------------- piccoli componenti grafici
UI_FONT = ["Segoe UI", 0]   # famiglia e scarto di dimensione (su Mac: San Francisco, +2)


class Tooltip:
    def __init__(self, widget, text):
        self.widget, self.text, self.tip = widget, text, None
        widget.bind("<Enter>", self.show, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")

    def show(self, _e=None):
        if self.tip or not self.widget.winfo_exists():
            return
        self.tip = tk.Toplevel(self.widget)
        self.tip.overrideredirect(True)
        self.tip.attributes("-topmost", True)
        tk.Label(self.tip, text=self.text, bg="#333333", fg="white", padx=6, pady=2,
                 font=(UI_FONT[0], 9 + UI_FONT[1])).pack()
        self.tip.update_idletasks()
        w, h = self.tip.winfo_reqwidth(), self.tip.winfo_reqheight()
        wx, wy = self.widget.winfo_rootx(), self.widget.winfo_rooty()
        x, y = wx + self.widget.winfo_width() - w, wy + self.widget.winfo_height() + 4
        if y + h > work_area(wx, wy)[3]:
            y = wy - h - 4
        x, y, _w, _h = fit_rect(x, y, w, h, (wx, wy))
        self.tip.geometry("+%d+%d" % (x, y))

    def hide(self, _e=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class Popup:
    """Riquadro in stile post-it. Su Windows è disegnato a mano (niente finestre di
    sistema) e si chiude con Esc o cliccando altrove; su Mac è una vera finestra macOS
    (angoli arrotondati, ombra, pulsante rosso). Resta ancorato in basso a destra."""

    def __init__(self, app, anchor):
        app.close_popup()
        app.popup = self
        self.app, self.c, self.br = app, app.c, None
        self.win = tk.Toplevel(app.root)
        if IS_MAC:
            self.win.resizable(False, False)
            self.win.transient(app.root)
            self.win.protocol("WM_DELETE_WINDOW", self.close)
            self.win.bind("<Command-w>", lambda _e: (self.close(), "break")[1])
        else:
            self.win.overrideredirect(True)
            self.win.bind("<FocusOut>", lambda _e: self.win.after(120, self.check_focus))
        self.win.attributes("-topmost", True)
        self.win.configure(bg=self.c["bg"] if IS_MAC else self.c["head"])
        self.card = tk.Frame(self.win, bg=self.c["bg"], padx=app.px(14 if IS_MAC else 12),
                             pady=app.px(12 if IS_MAC else 10))
        self.card.pack(padx=1, pady=1)
        self.win.bind("<Escape>", lambda _e: self.close())
        self.anchor = (anchor.winfo_rootx() + anchor.winfo_width(), anchor.winfo_rooty(),
                       anchor.winfo_rooty() + anchor.winfo_height())

    def label(self, parent, text, font=None, fg=None, **kw):
        return tk.Label(parent, text=text, bg=kw.pop("bg", self.c["bg"]),
                        fg=fg or self.c["ink"], font=font or self.app.f_norm, **kw)

    def link(self, parent, text, cmd, fg=None, font=None):
        lbl = self.label(parent, text, font=font or self.app.f_small, fg=fg or self.c["soft"],
                         cursor="hand2")
        lbl.bind("<Enter>", lambda _e: lbl.config(fg=self.c["ink"]))
        lbl.bind("<Leave>", lambda _e: lbl.config(fg=fg or self.c["soft"]))
        lbl.bind("<Button-1>", lambda _e: cmd())
        return lbl

    def menu_item(self, parent, text, cmd):
        lbl = self.label(parent, text, anchor="w", padx=self.app.px(8), pady=self.app.px(4),
                         cursor="hand2")
        lbl.bind("<Enter>", lambda _e: lbl.config(bg=self.c["head"]))
        lbl.bind("<Leave>", lambda _e: lbl.config(bg=self.c["bg"]))
        lbl.bind("<Button-1>", lambda _e: cmd())
        lbl.pack(fill="x")
        return lbl

    def header(self, title):
        row = tk.Frame(self.card, bg=self.c["bg"])
        row.pack(fill="x", pady=(0, self.app.px(6)))
        if IS_MAC:   # il titolo va nella barra della finestra, come nelle app Apple
            self.win.title(title)
            return row
        self.label(row, title, font=self.app.f_head).pack(side="left")
        self.link(row, "✕", self.close, font=self.app.f_icon).pack(side="right")
        return row

    def show(self):
        self.position()
        self.win.focus_force()

    def position(self):
        self.win.update_idletasks()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        if IS_MAC:   # finestra accanto al post-it (non sopra), ferma in alto a sinistra
            if self.br is None:
                r = self.app.root
                rx, ry, rw = r.winfo_rootx(), r.winfo_rooty(), r.winfo_width()
                x = rx + rw + 16
                if x + w > work_area(rx, ry)[2]:
                    x = rx - w - 16
                self.br = (x, ry - 28)
            x, y, _w, _h = fit_rect(self.br[0], self.br[1], w, h)
            self.win.geometry("+%d+%d" % (x, y))
            self.win.lift()
            return
        right, top, bottom = self.anchor
        if self.br is None:
            x, y = right - w, top - h - 6
            if y < work_area(right, top)[1]:
                y = bottom + 6
        else:
            x, y = self.br[0] - w, self.br[1] - h
        x, y, w, h = fit_rect(x, y, w, h, (right, top))
        self.br = (x + w, y + h)
        self.win.geometry("+%d+%d" % (x, y))

    def check_focus(self):
        if not self.win.winfo_exists():
            return
        try:
            f = self.win.focus_get()
        except (KeyError, tk.TclError):
            f = None
        if f is None or f.winfo_toplevel() is not self.win:
            self.close()

    def on_close(self):
        pass

    def close(self):
        if self.app.popup is self:
            self.app.popup = None
        self.app.last_closed = (type(self), time.monotonic())
        self.on_close()
        if self.win.winfo_exists():
            self.win.destroy()


class ExportMenu(Popup):
    def __init__(self, app, anchor):
        super().__init__(app, anchor)
        self.header("Esporta")
        self.label(self.card, "Salva un file di testo in %s" % (
                       "Documenti/Post-it" if IS_MAC else "Documenti\\Post-it"),
                   font=app.f_small, fg=self.c["soft"]).pack(anchor="w", pady=(0, app.px(4)))
        self.menu_item(self.card, "Questo post-it (%s)" % app.note_label(app.current_id()),
                       lambda: self.done(app.export([app.current_id()])))
        self.menu_item(self.card, "Tutti", lambda: self.done(app.export(app.used_ids())))
        self.show()

    def done(self, path):
        pad = self.card.cget("padx"), self.card.cget("pady")
        self.card.destroy()
        self.card = tk.Frame(self.win, bg=self.c["bg"], padx=pad[0], pady=pad[1])
        self.card.pack(padx=1, pady=1)
        if not path:
            self.header("Esportazione non riuscita")
            self.label(self.card, "Non è stato possibile scrivere il file.", fg=WARN,
                       font=self.app.f_small).pack(anchor="w")
        else:
            self.header("✓ Esportato")
            self.label(self.card, os.path.basename(path), font=self.app.f_small).pack(anchor="w")
            row = tk.Frame(self.card, bg=self.c["bg"])
            row.pack(anchor="w", pady=(self.app.px(6), 0))
            self.link(row, "Apri file", lambda: (open_path(path), self.close()),
                      fg=self.c["ink"]).pack(side="left")
            self.label(row, "  ·  ", font=self.app.f_small, fg=self.c["soft"]).pack(side="left")
            self.link(row, "Mostra nel Finder" if IS_MAC else "Apri cartella",
                      lambda: (open_path(os.path.dirname(path)), self.close()),
                      fg=self.c["ink"]).pack(side="left")
        self.position()
        self.win.after(10000, lambda: self.win.winfo_exists() and self.close())


class SettingsPanel(Popup):
    """Scorciatoie personalizzabili + modalità grande."""

    def __init__(self, app, anchor):
        super().__init__(app, anchor)
        self.capturing, self.msg, self.msg_warn = None, "", False
        self.win.bind("<KeyPress>", self.on_key)
        self.build()
        self.show()

    def build(self):
        if not self.win.winfo_exists():
            return
        app, c, px = self.app, self.c, self.app.px
        for w in self.card.winfo_children():
            w.destroy()
        self.header("Scorciatoie")
        self.label(self.card, "Clicca una combinazione per cambiarla", font=app.f_small,
                   fg=c["soft"]).pack(anchor="w")

        grid = tk.Frame(self.card, bg=c["bg"])
        grid.pack(fill="x", pady=(px(6), 0))
        for r, (action, text, _d) in enumerate(ACTIONS):
            self.label(grid, text, font=app.f_small).grid(row=r, column=0, sticky="w",
                                                          pady=px(2))
            failed = action in app.failed
            if self.capturing == action:
                chip_text, fg = "Premi i tasti…", c["ink"]
            else:
                chip_text = ("⚠ " if failed else "") + combo_label(app.data["hotkeys"][action])
                fg = WARN if failed else c["ink"]
            chip = self.label(grid, chip_text, font=app.f_small_b, fg=fg, cursor="hand2",
                              bg=c["head"], padx=px(6), pady=px(1))
            chip.grid(row=r, column=1, sticky="e", padx=(px(14), 0), pady=px(2))
            chip.bind("<Button-1>", lambda _e, a=action: self.start_capture(a))
        grid.columnconfigure(0, weight=1)

        if self.msg:
            self.label(self.card, self.msg, font=app.f_small,
                       fg=WARN if self.msg_warn else c["soft"]).pack(anchor="w", pady=(px(4), 0))
        elif app.failed:
            self.label(self.card, "⚠ = già usata da un altro programma: cambiala",
                       font=app.f_small, fg=WARN).pack(anchor="w", pady=(px(4), 0))

        self.separator()
        row = tk.Frame(self.card, bg=c["bg"])
        row.pack(fill="x")
        text = tk.Frame(row, bg=c["bg"])
        text.pack(side="left", fill="x", expand=True)
        self.label(text, "Modalità grande", font=app.f_small_b).pack(anchor="w")
        self.label(text, "Riduci/espandi passa anche per\nuna versione grande del post-it",
                   font=app.f_small, fg=c["soft"], justify="left").pack(anchor="w")
        self.switch(row, app.data["large_mode"], self.toggle_large).pack(side="right")

        row = tk.Frame(self.card, bg=c["bg"])
        row.pack(fill="x", pady=(px(8), 0))
        text = tk.Frame(row, bg=c["bg"])
        text.pack(side="left", fill="x", expand=True)
        self.label(text, "Apri al login" if IS_MAC else "Avvia con Windows",
                   font=app.f_small_b).pack(anchor="w")
        self.label(text, "Si apre da solo quando accendi %s,\ncosì le scorciatoie funzionano "
                         "subito" % ("il Mac" if IS_MAC else "il PC"),
                   font=app.f_small, fg=c["soft"], justify="left").pack(anchor="w")
        self.switch(row, autostart_enabled(), self.toggle_autostart).pack(side="right")

        self.separator()
        cmd = "⌘" if IS_MAC else "Ctrl+"
        self.label(self.card, "Sul post-it:  1·2·3 cambia colore (di nuovo: l'altro dello stesso"
                              " colore)\nInvio scrivi  ·  Esc esci  ·  ✕ nasconde (non chiude)\n"
                              "Note:  # titolo  ·  - elenco  ·  1. numerato  ·  *grassetto* "
                              "(%sB)  ·  _corsivo_ (%sI)" % (cmd, cmd),
                   font=app.f_small, fg=c["soft"], justify="left").pack(anchor="w")
        row = tk.Frame(self.card, bg=c["bg"])
        row.pack(fill="x", pady=(px(6), 0))
        self.link(row, "Ripristina predefinite", self.reset).pack(side="left")
        self.label(row, "  ·  ", font=app.f_small, fg=c["soft"]).pack(side="left")
        self.link(row, "Esci da Post-it", app.quit).pack(side="left")
        self.label(row, "versione " + VERSION, font=app.f_small, fg=c["soft"]).pack(side="right")
        if self.br is not None:
            self.position()

    def separator(self):
        tk.Frame(self.card, bg=self.c["head"], height=1).pack(fill="x", pady=self.app.px(8))

    def switch(self, parent, on, cmd):
        px = self.app.px
        w, h = px(34), px(18)
        cv = tk.Canvas(parent, width=w, height=h, bg=self.c["bg"], highlightthickness=0,
                       cursor="hand2")
        fill = (MAC_GREEN if IS_MAC else self.c["ink"]) if on else FAINT
        cv.create_oval(0, 0, h, h, fill=fill, outline=fill)
        cv.create_oval(w - h, 0, w, h, fill=fill, outline=fill)
        cv.create_rectangle(h // 2, 0, w - h // 2, h, fill=fill, outline=fill)
        k = px(3)
        x0 = w - h + k if on else k
        cv.create_oval(x0, k, x0 + h - 2 * k, h - k, fill="white", outline="white")
        cv.bind("<Button-1>", lambda _e: cmd())
        return cv

    def toggle_large(self):
        app = self.app
        app.data["large_mode"] = not app.data["large_mode"]
        if not app.data["large_mode"] and app.mode == "large":
            app.set_mode("normal")
        app.schedule_save()
        self.build()

    def toggle_autostart(self):
        on = not autostart_enabled()
        if set_autostart(on):
            self.msg, self.msg_warn = ("Partirà quando accendi %s" % (
                                           "il Mac" if IS_MAC else "il PC") if on
                                       else "Non partirà più da solo"), False
        else:
            self.msg, self.msg_warn = "Impossibile cambiare l'avvio automatico", True
        self.build()

    def reset(self):
        self.app.data["hotkeys"] = {a: list(k) for a, k in DEFAULT_KEYS.items()}
        self.app.schedule_save()
        self.capturing, self.msg, self.msg_warn = None, "Predefinite ripristinate", False
        self.app.apply_hotkeys()
        self.build()

    def start_capture(self, action):
        if self.capturing is None:
            self.app.hotkeys.suspend()  # così la combinazione premuta arriva qui
        self.capturing = action
        self.msg, self.msg_warn = ("Premi ⌃ o ⌘ (anche con ⌥ ⇧) + un tasto  ·  Esc annulla"
                                   if IS_MAC else
                                   "Premi Ctrl e/o Alt + un tasto  ·  Esc annulla"), False
        self.build()

    def stop_capture(self, msg="", warn=False):
        was_capturing = self.capturing is not None
        self.capturing, self.msg, self.msg_warn = None, msg, warn
        if was_capturing:
            self.app.apply_hotkeys()
        self.build()

    def on_key(self, e):
        if self.capturing is None:
            return None
        if e.keysym in MODIFIER_KEYSYMS:
            return "break"
        combo = event_combo(e)
        if e.keysym == "Escape" and not combo[0]:
            self.stop_capture()
            return "break"
        if not combo_allowed(combo[0]) or combo[1] is None:
            self.msg, self.msg_warn = ("Serve ⌃ o ⌘ insieme al tasto" if IS_MAC else
                                       "Serve Ctrl e/o Alt insieme al tasto"), True
            self.build()
            return "break"
        for other, val in self.app.data["hotkeys"].items():
            if other != self.capturing and list(val) == combo:
                self.msg, self.msg_warn = "Già usata per: " + ACTION_TEXT[other], True
                self.build()
                return "break"
        self.app.data["hotkeys"][self.capturing] = combo
        self.app.schedule_save()
        self.stop_capture("Salvata: " + combo_label(combo))
        return "break"

    def on_close(self):
        if self.capturing is not None:
            self.capturing = None
            self.app.apply_hotkeys()


# ---------------------------------------------------------------- testo formattato
# Le note si salvano come testo semplice in stile Markdown:
#   "# " "## " "### " titoli · "- " elenco puntato · "3. " elenco numerato
#   *grassetto* · _corsivo_ · "\" davanti a un simbolo lo rende normale.
BLOCKS = ("h1", "h2", "h3", "bullet", "num")
LISTS = ("bullet", "num")
HEADINGS = {"h1": 17, "h2": 14, "h3": 12}
BLOCK_PREFIX = {"h1": "# ", "h2": "## ", "h3": "### ", "bullet": "- "}
RE_HEADING = re.compile(r"(#{1,3}) ")
RE_NUMBERED = re.compile(r"(\d{1,4})\. ")
RE_NEEDS_ESCAPE = re.compile(r"(#{1,3} |- |\d{1,4}\. )")


def _has_closer(s, j, ch):
    while j < len(s):
        if s[j] == "\\":
            j += 2
            continue
        if s[j] == ch:
            return True
        j += 1
    return False


def parse_inline(s):
    """'a *b* _c_' -> [(testo, grassetto, corsivo), ...]"""
    segs, buf, state = [], [], {"*": False, "_": False}
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s) and s[i + 1] in "*_\\":
            buf.append(s[i + 1])
            i += 2
            continue
        if ch in "*_" and (state[ch] or _has_closer(s, i + 1, ch)):
            if buf:
                segs.append(("".join(buf), state["*"], state["_"]))
                buf = []
            state[ch] = not state[ch]
            i += 1
            continue
        buf.append(ch)
        i += 1
    if buf:
        segs.append(("".join(buf), state["*"], state["_"]))
    return segs


def parse_line(raw):
    """Riga Markdown -> (blocco, numero, segmenti)."""
    if raw.startswith("\\") and RE_NEEDS_ESCAPE.match(raw, 1):
        return None, None, parse_inline(raw[1:])
    m = RE_HEADING.match(raw)
    if m:
        return "h%d" % len(m.group(1)), None, parse_inline(raw[m.end():])
    if raw.startswith("- "):
        return "bullet", None, parse_inline(raw[2:])
    m = RE_NUMBERED.match(raw)
    if m:
        return "num", int(m.group(1)), parse_inline(raw[m.end():])
    return None, None, parse_inline(raw)


def serialize_line(block, num, chars):
    """(blocco, numero, [(carattere, grassetto, corsivo)]) -> riga Markdown."""
    out, b, i = [], False, False
    for ch, cb, ci in chars:
        if i and (not ci or cb != b):
            out.append("_")
            i = False
        if cb != b:
            out.append("*")
            b = cb
        if ci != i:
            out.append("_")
            i = ci
        out.append("\\" + ch if ch in "*_\\" else ch)
    if i:
        out.append("_")
    if b:
        out.append("*")
    body = "".join(out)
    if block == "num":
        return "%d. %s" % (num or 1, body)
    if block:
        return BLOCK_PREFIX[block] + body
    return "\\" + body if RE_NEEDS_ESCAPE.match(body) else body


def markdown_to_plain(text):
    """Versione leggibile per l'esportazione: niente simboli di formattazione."""
    lines = []
    for raw in text.split("\n"):
        block, num, segs = parse_line(raw)
        body = "".join(s for s, _b, _i in segs)
        if block in HEADINGS:
            body = body.upper() if block == "h1" else body
            lines.append(body)
        elif block == "bullet":
            lines.append("• " + body)
        elif block == "num":
            lines.append("%d. %s" % (num, body))
        else:
            lines.append(body)
    return "\n".join(lines)


class RichNote:
    """Editor delle note: titoli (# spazio), grassetto (*testo* o Ctrl+B), corsivo
    (_testo_ o Ctrl+I), elenchi puntati (- spazio) e numerati (1. spazio).
    Subito dopo una trasformazione, Tab o un secondo spazio la annullano."""

    def __init__(self, app, parent, key):
        self.app, self.key, self.c = app, key, app.c
        c, px = self.c, app.px
        self.t = t = tk.Text(parent, bg=c["bg"], fg=c["ink"], insertbackground=c["ink"],
                             font=app.f_norm, wrap="word", relief="flat", bd=0, undo=True,
                             highlightthickness=0, height=4, selectbackground=c["head"],
                             selectforeground=c["ink"], tabs=(px(24),))
        self.styles = set()
        self.just = None       # (riga, testo originale) della trasformazione appena fatta
        self.override = None   # (indice, (grassetto, corsivo)) dopo Ctrl+B/I senza selezione
        indent = app.f_norm.measure("88. ") + px(4)
        for b in LISTS:
            t.tag_configure(b, lmargin1=px(4), lmargin2=indent)
        for h in HEADINGS:
            t.tag_configure(h, spacing1=px(4), spacing3=px(2))
        t.tag_configure("mark", foreground=c["soft"])
        self.load(app.data["notes"][key]["text"])
        t.edit_reset()
        t.edit_modified(False)

        t.bind("<<Modified>>", self.on_modified)
        t.bind("<KeyPress>", self.on_key)
        t.bind("<Return>", self.on_return)
        t.bind("<KP_Enter>", self.on_return)
        t.bind("<BackSpace>", self.on_backspace)
        t.bind("<Delete>", lambda _e: self.later_normalize(0, 1))
        t.bind("<Tab>", self.on_tab)
        mod = "Command" if IS_MAC else "Control"
        for k in ("b", "B"):
            t.bind("<%s-%s>" % (mod, k), lambda _e: self.toggle_inline("bold"))
        for k in ("i", "I"):
            t.bind("<%s-%s>" % (mod, k), lambda _e: self.toggle_inline("italic"))
        t.bind("<<Paste>>", self.on_paste)
        for ev in ("<<Undo>>", "<<Redo>>", "<<Cut>>"):
            t.bind(ev, lambda _e: t.after_idle(self.normalize_all), add="+")
        t.bind("<Button-1>", self.reset_typing, add="+")

    # ----- utilità
    def style(self, block, bold, italic):
        size = HEADINGS.get(block, 11)
        bold = bool(bold or block in HEADINGS)
        name = "st_%d_%d_%d" % (size, bold, bool(italic))
        if name not in self.styles:
            self.t.tag_configure(name, font=self.app.font(size, bold, bool(italic)))
            self.styles.add(name)
        return name

    def tags(self, block, bold, italic, mark=False):
        out = [self.style(block, bold and not mark, italic and not mark)]
        if block:
            out.append(block)
        if bold and not mark:
            out.append("bold")
        if italic and not mark:
            out.append("italic")
        if mark:
            out.append("mark")
        return tuple(out)

    def line_of(self, idx):
        return int(self.t.index(idx).split(".")[0])

    def last_line(self):
        return int(self.t.index("end-1c").split(".")[0])

    def block_of(self, line):
        names = self.t.tag_names("%d.end" % line)
        for b in BLOCKS:
            if b in names:
                return b
        return None

    def mark_range(self, line):
        r = self.t.tag_nextrange("mark", "%d.0" % line, "%d.end" % line)
        if r and self.t.compare(r[0], "==", "%d.0" % line):
            return r
        return None

    def content_start(self, line):
        r = self.mark_range(line)
        return int(str(r[1]).split(".")[1]) if r else 0

    def mark_number(self, line):
        r = self.mark_range(line)
        m = re.match(r"(\d+)", self.t.get(*r)) if r else None
        return int(m.group(1)) if m else 1

    def set_mark(self, line, text):
        r = self.mark_range(line)
        if r:
            self.t.delete(*r)
        if text:
            self.t.insert("%d.0" % line, text,
                          self.tags(self.block_of(line), False, False, mark=True))

    def changed(self):
        self.app.schedule_save()

    def on_modified(self, _e=None):
        if self.t.edit_modified():
            self.t.edit_modified(False)
            self.app.schedule_save()

    def reset_typing(self, _e=None):
        self.just = self.override = None

    # ----- blocchi (titoli ed elenchi)
    def set_block(self, line, block, num=None):
        t = self.t
        self.set_mark(line, "")
        start, end = "%d.0" % line, "%d.end+1c" % line
        for b in BLOCKS:
            t.tag_remove(b, start, end)
        if block:
            t.tag_add(block, start, end)
        if block == "bullet":
            self.set_mark(line, "• ")
        elif block == "num":
            self.set_mark(line, "%d. " % (num or 1))
        self.restyle(line)
        self.changed()

    def restyle(self, line):
        """Rimette il carattere giusto (dimensione, grassetto, corsivo) su una riga."""
        t = self.t
        block = self.block_of(line)
        start, end = "%d.0" % line, "%d.end+1c" % line
        for s in list(self.styles):
            t.tag_remove(s, start, end)
        n = len(t.get(start, "%d.end" % line))
        runs = []
        for col in range(n + 1):
            names = t.tag_names("%d.%d" % (line, col))
            mark = "mark" in names
            st = self.style(block, "bold" in names and not mark, "italic" in names and not mark)
            if not runs or runs[-1][1] != st:
                runs.append((col, st))
        for k, (col, st) in enumerate(runs):
            stop = runs[k + 1][0] if k + 1 < len(runs) else n + 1
            t.tag_add(st, "%d.%d" % (line, col), "%d.%d" % (line, stop))

    def normalize(self, line):
        """Rende coerente una riga dopo modifiche libere (cancella, incolla, annulla)."""
        t = self.t
        if line < 1 or line > self.last_line():
            return
        block = self.block_of(line)
        pos = "%d.0" % line
        while True:  # niente simboli d'elenco a metà riga
            r = t.tag_nextrange("mark", pos, "%d.end" % line)
            if not r:
                break
            if t.compare(r[0], "==", "%d.0" % line):
                pos = r[1]
            else:
                t.delete(*r)
        start, end = "%d.0" % line, "%d.end+1c" % line
        for b in BLOCKS:
            t.tag_remove(b, start, end)
        if block:
            t.tag_add(block, start, end)
        r = self.mark_range(line)
        text = t.get(*r) if r else ""
        if block == "bullet" and text != "• ":
            self.set_mark(line, "• ")
        elif block == "num" and not re.fullmatch(r"\d+\. ", text):
            prev = self.mark_number(line - 1) + 1 if line > 1 and self.block_of(line - 1) == "num" else 1
            self.set_mark(line, "%d. " % prev)
        elif block not in LISTS and r:
            self.set_mark(line, "")
        self.restyle(line)

    def normalize_all(self):
        if not self.t.winfo_exists():
            return
        for line in range(1, self.last_line() + 1):
            self.normalize(line)
        for line in range(1, self.last_line() + 1):
            if self.block_of(line) == "num" and (line == 1 or self.block_of(line - 1) != "num"):
                self.renumber(line)
        self.changed()

    def later_normalize(self, before, after):
        line = self.line_of("insert")

        def run():
            if not self.t.winfo_exists():
                return
            cur = self.line_of("insert")
            for l in sorted({line - before, line, line + after, cur}):
                self.normalize(l)
            for l in (line - before, cur):
                self.renumber(l)
            self.changed()
        self.t.after_idle(run)
        return None

    def renumber(self, line):
        """Rinumera la serie di voci numerate che contiene `line`."""
        if line < 1 or line > self.last_line() or self.block_of(line) != "num":
            return
        start = line
        while start > 1 and self.block_of(start - 1) == "num":
            start -= 1
        n, l = self.mark_number(start), start
        while l <= self.last_line() and self.block_of(l) == "num":
            want = "%d. " % n
            r = self.mark_range(l)
            if not r or self.t.get(*r) != want:
                self.set_mark(l, want)
            n, l = n + 1, l + 1

    # ----- scrittura
    def current_style(self, idx):
        t = self.t
        idx = t.index(idx)
        if self.override and t.compare(self.override[0], "==", idx):
            return self.override[1]
        line, col = (int(v) for v in idx.split("."))
        names = t.tag_names(idx if col <= self.content_start(line) else idx + "-1c")
        if "mark" in names:
            return False, False
        return "bold" in names, "italic" in names

    def type_char(self, ch):
        t = self.t
        if t.tag_ranges("sel"):
            t.delete("sel.first", "sel.last")
        line = self.line_of("insert")
        if t.compare("insert", "<", "%d.%d" % (line, self.content_start(line))):
            t.mark_set("insert", "%d.%d" % (line, self.content_start(line)))
        b, i = self.current_style("insert")
        t.insert("insert", ch, self.tags(self.block_of(line), b, i))
        if self.override:
            self.override = (t.index("insert"), self.override[1])
        t.see("insert")

    def on_key(self, e):
        if IS_MAC:
            if e.state & (0x8 | 0x4):  # ⌘C, ⌘V, ⌘Z e i tasti ⌃: comportamento normale
                return None            # (⌥ invece scrive i caratteri speciali, es. ⌥5 = [)
        else:
            ctrl, alt = e.state & 0x4, e.state & 0x20000
            if ctrl != 0 and alt == 0:
                return None            # Ctrl+C, Ctrl+V, Ctrl+Z... comportamento normale
            if alt and not ctrl:
                return None
        if e.keysym == "space":
            return self.on_space()
        ch = e.char
        if ch and ch.isprintable():
            self.just = None
            if ch in "*_" and self.close_inline(ch):
                return "break"
            self.type_char(ch)
            return "break"
        if e.keysym in ("Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next"):
            self.reset_typing()
        return None

    def on_space(self):
        t = self.t
        if not t.tag_ranges("sel"):
            line, col = (int(v) for v in t.index("insert").split("."))
            if self.just and self.just[0] == line and col == self.content_start(line):
                self.revert()          # secondo spazio: torna testo normale
                return "break"
            if self.block_of(line) is None:
                before = t.get("%d.0" % line, "insert")
                block = num = None
                if before == "-":
                    block = "bullet"
                elif before in ("#", "##", "###"):
                    block = "h%d" % len(before)
                elif re.fullmatch(r"\d{1,4}\.", before):
                    block, num = "num", int(before[:-1])
                if block:
                    t.delete("%d.0" % line, "insert")
                    self.set_block(line, block, num)
                    t.mark_set("insert", "%d.%d" % (line, self.content_start(line)))
                    self.just = (line, before + " ")
                    self.renumber(line + 1)
                    return "break"
        self.just = None
        self.type_char(" ")
        return "break"

    def revert(self):
        """Annulla l'ultima trasformazione: rimette '- ', '1. ' o '# ' come testo."""
        line, text = self.just
        self.just = None
        self.set_block(line, None)
        self.t.insert("%d.0" % line, text, self.tags(None, False, False))
        self.t.mark_set("insert", "%d.%d" % (line, len(text)))
        self.renumber(line + 1)

    def on_tab(self, _e=None):
        line, col = (int(v) for v in self.t.index("insert").split("."))
        if self.just and self.just[0] == line and col == self.content_start(line):
            self.revert()
            return "break"
        self.just = None
        if self.c["todo"]:
            self.app.focus_todo_entry()   # post-it verde: Tab passa alla lista
        else:
            self.type_char("\t")
        return "break"

    def on_return(self, _e=None):
        t = self.t
        self.reset_typing()
        if t.tag_ranges("sel"):
            t.delete("sel.first", "sel.last")
        line = self.line_of("insert")
        block = self.block_of(line)
        cs = self.content_start(line)
        at_end = t.compare("insert", "==", "%d.end" % line)
        if block in LISTS and at_end and not t.get("%d.%d" % (line, cs), "%d.end" % line).strip():
            self.set_block(line, None)    # Invio su voce vuota: esce dall'elenco
            self.renumber(line + 1)
            return "break"
        if t.compare("insert", "<", "%d.%d" % (line, cs)):
            t.mark_set("insert", "%d.%d" % (line, cs))
        t.insert("insert", "\n", self.tags(block, False, False))
        new = line + 1
        if block in HEADINGS and at_end:
            self.set_block(new, None)     # dopo un titolo si torna al testo normale
        else:
            self.normalize(new)
        self.normalize(line)
        self.renumber(new)
        t.mark_set("insert", "%d.%d" % (new, self.content_start(new)))
        t.see("insert")
        self.changed()
        return "break"

    def on_backspace(self, _e=None):
        t = self.t
        if t.tag_ranges("sel"):
            return self.later_normalize(1, 1)
        line, col = (int(v) for v in t.index("insert").split("."))
        block, cs = self.block_of(line), self.content_start(line)
        if self.just and self.just[0] == line and col == cs:
            self.revert()
            return "break"
        self.just = None
        if block in LISTS and col <= cs and cs > 0:
            self.set_block(line, None)    # toglie il punto elenco, il testo resta
            self.renumber(line + 1)
            return "break"
        if block in HEADINGS and col == 0:
            self.set_block(line, None)
            return "break"
        return self.later_normalize(1, 0)

    def toggle_inline(self, tag):
        t = self.t
        if t.tag_ranges("sel"):
            s, e = t.index("sel.first"), t.index("sel.last")
            text = t.get(s, e)
            has_all = all(tag in t.tag_names("%s+%dc" % (s, k))
                          for k, ch in enumerate(text) if ch != "\n")
            (t.tag_remove if has_all else t.tag_add)(tag, s, e)
            for line in range(self.line_of(s), self.line_of(e) + 1):
                self.restyle(line)
            self.changed()
        else:
            b, i = self.current_style("insert")
            self.override = (t.index("insert"), (not b, i) if tag == "bold" else (b, not i))
        return "break"

    def close_inline(self, ch):
        """*testo* diventa grassetto, _testo_ corsivo (mentre scrivi)."""
        t = self.t
        if t.tag_ranges("sel"):
            return False
        line = self.line_of("insert")
        cs = self.content_start(line)
        before = t.get("%d.%d" % (line, cs), "insert")
        j = before.rfind(ch)
        if j < 0:
            return False
        inner = before[j + 1:]
        if not inner.strip() or inner[0] == " " or inner[-1] == " ":
            return False
        tag = "bold" if ch == "*" else "italic"
        s = "%d.%d" % (line, cs + j)
        t.delete(s)
        e = "%d.%d" % (line, cs + j + len(inner))
        t.tag_add(tag, s, e)
        self.restyle(line)
        t.mark_set("insert", e)
        b, i = self.current_style(e)
        self.override = (e, (False, i) if tag == "bold" else (b, False))
        self.changed()
        return True

    def on_paste(self, _e=None):
        t = self.t
        try:
            text = t.clipboard_get()
        except tk.TclError:
            return "break"
        if t.tag_ranges("sel"):
            t.delete("sel.first", "sel.last")
        line = self.line_of("insert")
        block = self.block_of(line)
        b, i = self.current_style("insert")
        t.insert("insert", text.replace("\r\n", "\n").replace("\r", "\n"), self.tags(None, b, i))
        end = self.line_of("insert")
        for l in range(line, end + 1):  # la prima riga resta com'era, le altre testo normale
            for bt in BLOCKS:
                t.tag_remove(bt, "%d.0" % l, "%d.end+1c" % l)
            if l == line and block:
                t.tag_add(block, "%d.0" % l, "%d.end+1c" % l)
            self.normalize(l)
        t.see("insert")
        self.reset_typing()
        self.changed()
        return "break"

    # ----- caricamento e salvataggio
    def load(self, text):
        t = self.t
        t.delete("1.0", "end")
        lines = [parse_line(raw) for raw in text.split("\n")]
        for n, (block, num, segs) in enumerate(lines):
            if block == "bullet":
                t.insert("end-1c", "• ", self.tags(block, False, False, mark=True))
            elif block == "num":
                t.insert("end-1c", "%d. " % num, self.tags(block, False, False, mark=True))
            for s, b, i in segs:
                t.insert("end-1c", s, self.tags(block, b, i))
            if n < len(lines) - 1:
                t.insert("end-1c", "\n", self.tags(block, False, False))
            else:
                for tag in self.tags(block, False, False):
                    t.tag_add(tag, "end-1c")

    def serialize(self):
        """Editor -> Markdown. Legge testo e stili con una sola chiamata (dump), così
        il salvataggio resta istantaneo anche con note lunghe."""
        out, chars, mark, on = [], [], "", set()
        for kind, value, _idx in self.t.dump("1.0", "end", tag=True, text=True):
            if kind == "tagon":
                on.add(value)
            elif kind == "tagoff":
                on.discard(value)
            elif kind == "text":
                for ch in value:
                    if ch == "\n":   # fine riga: il blocco è il tag sul ritorno a capo
                        block = next((b for b in BLOCKS if b in on), None)
                        m = re.match(r"\d+", mark)
                        num = int(m.group()) if block == "num" and m else None
                        out.append(serialize_line(block, num, chars))
                        chars, mark = [], ""
                    elif "mark" in on:
                        mark += ch
                    else:
                        chars.append((ch, "bold" in on, "italic" in on))
        return "\n".join(out)

    def insert_text(self, char):
        """Usato quando si inizia a scrivere dalla modalità comandi."""
        self.t.focus_force()
        self.t.mark_set("insert", "end-1c")
        self.t.see("insert")
        if char:
            self.type_char(char)


# ---------------------------------------------------------------- applicazione
class PostItApp:
    def __init__(self):
        self.data = load_data()
        self.mode = "normal"          # normal | collapsed | large
        self.hidden = False
        self.hwnd = None
        self.save_job = self.flash_job = None
        self.drag = self.resize = None
        self.popup = None
        self.failed = set()
        self.warning = ""
        self.notes_widget = self.entry = self.title_lbl = self.list_frame = None
        self.rich = None
        self.last_closed = None
        self._fonts = {}
        self.entry_focus_in = lambda: None
        self.row_labels = []
        self.wrap_px = 200

        self.root = tk.Tk()
        self.root.title("Post-it")
        self.root.report_callback_exception = self.on_tk_error
        if IS_WIN and os.path.exists(ICON_FILE):
            try:
                self.root.iconbitmap(default=ICON_FILE)
            except tk.TclError:
                pass
        if IS_MAC:   # punti di macOS: niente riscalatura; carattere di sistema (San Francisco)
            self.s = 1.0
            UI_FONT[:] = [tkfont.nametofont("TkDefaultFont").actual("family"), 2]
            _SCREEN[:] = [0, 25, self.root.winfo_screenwidth(), self.root.winfo_screenheight()]
        else:
            self.s = self.root.winfo_fpixels("1i") / 96.0
            if not IS_WIN:
                _SCREEN[:] = [0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()]
        self.header_h = self.px(34 if IS_MAC else 30)
        self.min_w, self.min_h = self.px(220), self.px(160)
        if IS_MAC:
            self.setup_mac()
        else:
            self.root.overrideredirect(True)
        # ✕ della finestra, Alt+F4 o ⌘W nascondono soltanto: le scorciatoie restano attive
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.root.protocol("WM_SAVE_YOURSELF", self.save_now)   # spegnimento di Windows
        self.data["geometry"] = self.initial_geometry()
        self.root.geometry(self.data["geometry"])
        self.root.attributes("-topmost", self.data["topmost"])

        self.f_norm = self.font(11)
        self.f_done = self.font(11, over=True)
        self.f_head = self.font(10, bold=True)
        self.f_small = self.font(9)
        self.f_small_b = self.font(9, bold=True)
        self.f_icon = tkfont.Font(family=UI_FONT[0] if IS_MAC else "Segoe UI Symbol",
                                  size=11 + UI_FONT[1])

        self.container = None
        self.edges = self.make_edges() if IS_WIN else {}
        self.render()

        self.root.bind("<Key>", self.on_key)
        self.root.bind("<Escape>", self.on_escape)
        for ev in ("<FocusIn>", "<FocusOut>"):
            self.root.bind(ev, lambda _e: self.root.after_idle(self.update_hint), add="+")

        self.events = queue.Queue()
        self.hotkeys = make_hotkeys(self.events, self.data["hotkeys"])
        threading.Thread(target=listen_show_requests, args=(self.events,), daemon=True).start()
        self.root.after(40, self.poll_events)
        if IS_WIN:
            self.root.after(10, self.show_in_taskbar)

    def setup_mac(self):
        """Finestra macOS vera (angoli arrotondati, ombra, semafori) e menu dell'app."""
        r = self.root
        r.createcommand("::tk::mac::ReopenApplication", self.activate)  # clic sull'icona nel Dock
        r.createcommand("::tk::mac::ShowPreferences", self.open_settings)   # ⌘,
        r.createcommand("::tk::mac::Quit", self.quit)                       # ⌘Q
        r.bind_all("<Command-w>", lambda _e: self.hide_window())
        menubar = tk.Menu(r)
        appmenu = tk.Menu(menubar, name="apple")
        menubar.add_cascade(menu=appmenu)
        appmenu.add_command(label="Informazioni su Post-it", command=lambda: messagebox.showinfo(
            "Post-it", "Post-it %s\nTodo list e note sempre a portata di mano." % VERSION))
        appmenu.add_separator()
        notes = tk.Menu(menubar)
        menubar.add_cascade(label="Post-it", menu=notes)
        for i, key in enumerate(ORDER, start=1):
            # ⌘1/2/3 li gestisce on_key; qui l'acceleratore serve solo da promemoria
            notes.add_command(label="%s · %s" % (NOTES[key]["label"], NOTES[key]["name"]),
                              accelerator="Command-%d" % i,
                              command=lambda k=key: self.switch(k))
        notes.add_separator()
        notes.add_command(label="Sempre in primo piano", command=self.toggle_topmost)
        notes.add_command(label="Riduci / espandi", command=self.cycle_size)
        notes.add_command(label="Esporta…", command=lambda: self.toggle_popup(
            ExportMenu, self.title_lbl))
        menubar.add_cascade(label="Finestra", menu=tk.Menu(menubar, name="window"))
        r.configure(menu=menubar)

    def open_settings(self):
        self.activate()
        if not isinstance(self.popup, SettingsPanel):
            SettingsPanel(self, self.title_lbl)

    def on_tk_error(self, exc_type, exc, tb):
        exc.__traceback__ = tb
        log_error("interfaccia", exc)

    def run(self):
        log("avvio %s (Python %s, %s)%s" % (VERSION, sys.version.split()[0], sys.platform,
                                            " all'accensione" if "--autostart" in sys.argv else ""))
        self.root.mainloop()

    def px(self, n):
        return int(round(n * self.s))

    def font(self, size=11, bold=False, italic=False, over=False):
        """Caratteri condivisi (creati una volta sola): Segoe UI su Windows,
        San Francisco un po' più grande su Mac."""
        key = (size, bold, italic, over)
        f = self._fonts.get(key)
        if f is None:
            f = self._fonts[key] = tkfont.Font(
                family=UI_FONT[0], size=size + UI_FONT[1], weight="bold" if bold else "normal",
                slant="italic" if italic else "roman", overstrike=int(over))
        return f

    # ------------------------------------------------------------ finestra
    def initial_geometry(self):
        default = "%dx%d+%d+%d" % (self.px(300), self.px(380), self.px(120), self.px(120))
        try:
            size, x, y = self.data["geometry"].split("+")
            w, h = (int(v) for v in size.split("x"))
            x, y = int(x), int(y)
        except (AttributeError, ValueError):
            return default
        x, y, w, h = fit_rect(x, y, max(w, self.min_w), max(h, self.min_h))
        return "%dx%d+%d+%d" % (w, h, x, y)

    def place(self, x, y, w, h, point=None):
        """Applica posizione e misura tenendo il post-it dentro lo schermo."""
        x, y, w, h = fit_rect(x, y, w, h, point)
        self.root.geometry("%dx%d+%d+%d" % (w, h, x, y))

    def keep_on_screen(self):
        self.root.update_idletasks()
        self.place(self.root.winfo_x(), self.root.winfo_y(),
                   self.root.winfo_width(), self.root.winfo_height())

    def show_in_taskbar(self):
        """Finestra senza bordi ma visibile nella barra e capace di ricevere la tastiera."""
        try:
            hwnd = user32.GetParent(self.root.winfo_id())
            self.hwnd = hwnd
            style = user32.GetWindowLongW(hwnd, -20)
            user32.SetWindowLongW(hwnd, -20, (style & ~0x00000080) | 0x00040000)
            self.root.withdraw()
            self.root.after(10, self.root.deiconify)
            self.root.after(30, lambda: self.root.attributes("-topmost", self.data["topmost"]))
        except (OSError, tk.TclError):
            pass

    def make_edges(self):
        """Bordi invisibili per ridimensionare da ogni lato e angolo."""
        b, c, hh = self.px(5), self.px(12), self.header_h
        spec = {
            "n": (dict(x=0, y=0, relwidth=1, height=b), "size_ns"),
            "s": (dict(x=0, rely=1, y=-b, relwidth=1, height=b), "size_ns"),
            "w": (dict(x=0, y=hh, width=b, relheight=1, height=-hh), "size_we"),
            "e": (dict(relx=1, x=-b, y=hh, width=b, relheight=1, height=-hh), "size_we"),
            "nw": (dict(x=0, y=0, width=c, height=c), "size_nw_se"),
            "ne": (dict(relx=1, x=-c, y=0, width=c, height=c), "size_ne_sw"),
            "sw": (dict(x=0, rely=1, y=-c, width=c, height=c), "size_ne_sw"),
            "se": (dict(relx=1, x=-c, rely=1, y=-c, width=c, height=c), "size_nw_se"),
        }
        edges = {}
        for k, (place, cursor) in spec.items():
            f = tk.Frame(self.root, cursor=cursor, bd=0, highlightthickness=0)
            f.place(**place)
            f.bind("<ButtonPress-1>", lambda e, k=k: self.start_resize(e, k))
            f.bind("<B1-Motion>", self.do_resize)
            f.bind("<ButtonRelease-1>", self.end_drag)
            edges[k] = f
        return edges

    def start_move(self, e):
        self.drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def do_move(self, e):
        if self.drag:  # lo schermo è quello sotto il mouse: si può passare all'altro monitor
            self.place(e.x_root - self.drag[0], e.y_root - self.drag[1],
                       self.root.winfo_width(), self.root.winfo_height(), (e.x_root, e.y_root))

    def start_resize(self, e, edge):
        x, y, w, h = (self.root.winfo_x(), self.root.winfo_y(),
                      self.root.winfo_width(), self.root.winfo_height())
        self.resize = (edge, e.x_root, e.y_root, x, y, w, h,
                       work_area(x + w // 2, y + self.header_h // 2))

    def do_resize(self, e):
        if not self.resize:
            return
        edge, x0, y0, x, y, w, h, (left, top, right, bottom) = self.resize
        dx, dy = e.x_root - x0, e.y_root - y0
        nx, ny, nw, nh = x, y, w, h
        if "e" in edge:
            nw = min(max(self.min_w, w + dx), right - x)
        if "w" in edge:
            nw = min(max(self.min_w, w - dx), x + w - left)
            nx = x + w - nw
        if self.mode != "collapsed":
            if "s" in edge:
                nh = min(max(self.min_h, h + dy), bottom - y)
            if "n" in edge:
                nh = min(max(self.min_h, h - dy), y + h - top)
                ny = y + h - nh
        self.root.geometry("%dx%d+%d+%d" % (nw, nh, nx, ny))

    def end_drag(self, _e=None):
        self.drag = self.resize = None
        self.remember_geometry()

    def normal_size(self):
        w, h = self.data["geometry"].split("+")[0].split("x")
        return int(w), int(h)

    def remember_geometry(self):
        x, y = self.root.winfo_x(), self.root.winfo_y()
        if self.mode == "normal":
            w, h = self.root.winfo_width(), self.root.winfo_height()
        elif self.mode == "collapsed":
            w, h = self.root.winfo_width(), self.normal_size()[1]
        else:
            w, h = self.normal_size()
        self.data["geometry"] = "%dx%d+%d+%d" % (w, h, x, y)
        self.schedule_save()

    def set_mode(self, mode):
        self.remember_geometry()
        x, y = self.root.winfo_x(), self.root.winfo_y()
        w, h = self.normal_size()
        if mode == "collapsed":
            h = self.header_h
        elif mode == "large":
            top, bottom = work_area(x + w // 2, y)[1::2]
            w, h = max(w, self.px(460)), int((bottom - top) * 0.7)
        self.mode = mode
        self.place(x, y, w, h)
        self.render()

    def toggle_collapse(self):
        self.set_mode("normal" if self.mode == "collapsed" else "collapsed")

    def cycle_size(self):
        if self.hidden:
            self.show_window()
        if self.mode == "collapsed":
            self.set_mode("normal")
        elif self.mode == "normal" and self.data["large_mode"]:
            self.set_mode("large")
        else:
            self.set_mode("collapsed")

    def toggle_topmost(self):
        self.data["topmost"] = not self.data["topmost"]
        self.root.attributes("-topmost", self.data["topmost"])
        self.schedule_save()
        self.render()

    def show_window(self):
        self.hidden = False
        self.root.deiconify()
        self.keep_on_screen()  # es. dopo aver staccato un monitor
        self.root.after(30, lambda: self.root.attributes("-topmost", self.data["topmost"]))

    def hide_window(self):
        self.close_popup()
        self.remember_geometry()
        self.hidden = True
        self.root.withdraw()
        if IS_MAC:   # come ⌘H: il controllo torna subito all'app che stavi usando
            mac_app(b"hide:", None, (ctypes.c_void_p,), None)

    def toggle_visible(self):
        if self.hidden:
            self.show_window()
        else:
            self.hide_window()

    def is_foreground(self):
        if IS_MAC:
            return bool(mac_app(b"isActive", ctypes.c_bool))
        if not IS_WIN:
            return self.root.focus_get() is not None
        return bool(self.hwnd) and user32.GetForegroundWindow() == self.hwnd

    def force_foreground(self):
        """Porta il Post-it davanti all'app che si sta usando."""
        if IS_MAC:
            self.root.lift()
            mac_app(b"activateIgnoringOtherApps:", None, (ctypes.c_bool,), True)
            return
        if not IS_WIN:
            self.root.lift()
            return
        # Windows non lascia rubare il primo piano: ci agganciamo al programma attivo
        hwnd = self.hwnd or user32.GetParent(self.root.winfo_id())
        fg_tid = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
        my_tid = kernel32.GetCurrentThreadId()
        attach = bool(fg_tid) and fg_tid != my_tid
        if attach:
            user32.AttachThreadInput(my_tid, fg_tid, True)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        if attach:
            user32.AttachThreadInput(my_tid, fg_tid, False)

    def activate(self):
        """Post-it davanti, pronto a ricevere 1/2/3 o testo."""
        if self.hidden:
            self.show_window()
        if self.mode == "collapsed":
            self.set_mode("normal")
        self.force_foreground()
        self.root.focus_force()
        self.update_hint()

    def close(self):
        self.close_popup()
        self.remember_geometry()
        self.save_now()
        self.root.destroy()

    def quit(self):
        """Chiude davvero il programma (da «Esci da Post-it» o ⌘Q)."""
        log("chiuso dall'utente")
        self.close()

    def close_popup(self):
        if self.popup is not None:
            self.popup.close()

    def toggle_popup(self, cls, anchor):
        """Primo clic apre il riquadro, secondo clic lo chiude."""
        if isinstance(self.popup, cls):
            self.close_popup()
            return
        last = self.last_closed
        if last and last[0] is cls and time.monotonic() - last[1] < 0.35:
            return  # appena chiuso da questo stesso clic
        cls(self, anchor)

    # ------------------------------------------------------------ eventi e scorciatoie
    def poll_events(self):
        """Legge le scorciatoie arrivate. Si ripianifica sempre per prima cosa: un errore
        in un'azione non deve mai spegnere le scorciatoie per il resto della giornata."""
        self.root.after(40, self.poll_events)
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                return
            try:
                if kind == "hotkey":
                    self.on_hotkey(value)
                elif kind == "status":
                    self.on_hotkey_status(value)
                elif kind == "show":
                    self.activate()
            except Exception as exc:  # noqa: BLE001
                log_error("azione %s %s" % (kind, value), exc)

    def on_hotkey(self, action):
        if action == "write":
            if not self.hidden and self.is_foreground():
                self.hide_window()
            else:
                self.activate()
        elif action == "pin":
            if self.hidden:
                self.show_window()
            self.toggle_topmost()
        elif action == "hide":
            self.toggle_visible()
        elif action == "expand":
            self.cycle_size()
        elif action.startswith("note:"):
            # già in vista sullo stesso colore: passa all'altro post-it di quel colore
            visible = (not self.hidden and self.mode != "collapsed"
                       and (self.data["topmost"] or self.is_foreground()))
            self.switch(action[5:], toggle=visible)
            self.activate()

    def on_hotkey_status(self, failed):
        self.failed = set(failed)
        if isinstance(self.popup, SettingsPanel):
            self.popup.build()
        elif failed:
            names = ", ".join(combo_label(self.data["hotkeys"][a]) for a in failed)
            self.flash("⚠ già in uso: " + names + " (⌨ per cambiarle)")

    def apply_hotkeys(self):
        self.hotkeys.reload(self.data["hotkeys"])

    def flash(self, text, ms=8000):
        self.warning = text
        self.update_hint()
        if self.flash_job:
            self.root.after_cancel(self.flash_job)

        def clear():
            self.warning, self.flash_job = "", None
            self.update_hint()
        self.flash_job = self.root.after(ms, clear)

    def is_command_mode(self):
        try:
            return self.root.focus_get() is self.root
        except (KeyError, tk.TclError):
            return False

    def update_hint(self):
        if self.title_lbl is None or not self.title_lbl.winfo_exists():
            return
        if self.warning:
            self.title_lbl.configure(text=self.warning, fg=WARN)
        else:
            hint = "   1·2·3  o scrivi" if self.is_command_mode() else ""
            page = self.data["page"][self.data["current"]] + 1
            self.title_lbl.configure(text="%s · %d%s" % (self.c["name"], page, hint),
                                     fg=self.c["ink"])

    def on_key(self, e):
        editing = isinstance(e.widget, (tk.Text, tk.Entry))
        ctrl = bool(e.state & (0x8 if IS_MAC else 0x4))   # ⌘ su Mac, Ctrl altrove
        if e.keysym in ("1", "2", "3") and (ctrl or not editing):
            self.switch(ORDER[int(e.keysym) - 1])
            self.root.focus_force()
            self.update_hint()
            return "break"
        if editing or ctrl:
            return None
        if e.keysym in ("Return", "KP_Enter"):
            self.start_edit()
            return "break"
        if e.char and e.char.isprintable():
            self.start_edit(e.char)
            return "break"
        return None

    def on_escape(self, e):
        if isinstance(e.widget, (tk.Text, tk.Entry)):
            self.root.focus_force()
            self.update_hint()
            return "break"
        return None

    def focus_todo_entry(self):
        if self.entry is not None:
            self.entry_focus_in()
            self.entry.focus_force()

    def start_edit(self, char=None):
        if self.c["notes"] and self.rich is not None:
            self.rich.insert_text(char)
        elif self.entry is not None:
            self.entry_focus_in()
            self.entry.focus_force()
            self.entry.icursor("end")
            if char:
                self.entry.insert("end", char)

    # ------------------------------------------------------------ dati
    def current_id(self):
        color = self.data["current"]
        return note_id(color, self.data["page"][color])

    def note(self):
        return self.data["notes"][self.current_id()]

    @staticmethod
    def note_label(nid):
        color = note_color(nid)
        return "%s %d" % (NOTES[color]["label"], 2 if nid != color else 1)

    def used_ids(self):
        """Per «Esporta tutti»: i primi post-it sempre, i secondi solo se usati."""
        self.sync_notes()
        notes = self.data["notes"]
        return [k for k in NOTE_IDS
                if k in ORDER or notes[k]["text"].strip() or notes[k]["todos"]]

    def schedule_save(self):
        if self.save_job:
            self.root.after_cancel(self.save_job)
        self.save_job = self.root.after(400, self.save_now)

    def sync_notes(self):
        """Copia nei dati il testo dell'editor aperto (sempre nel suo post-it)."""
        r = self.rich
        if r is not None and r.t.winfo_exists():
            self.data["notes"][r.key]["text"] = r.serialize()

    def save_now(self):
        self.save_job = None
        self.sync_notes()
        try:
            os.makedirs(APP_DIR, exist_ok=True)
            tmp = DATA_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, DATA_FILE)
        except OSError:
            self.flash("⚠ impossibile salvare")

    def switch(self, color, toggle=True):
        """Altro colore: apre il suo ultimo post-it. Stesso colore: passa all'altro dei due."""
        if color == self.data["current"]:
            if not toggle:
                return
            self.data["page"][color] ^= 1
        else:
            self.data["current"] = color
        self.schedule_save()
        self.close_popup()
        self.render()
        self.root.focus_set()
        self.update_hint()

    def export(self, keys):
        """Scrive i post-it scelti in un file di testo; restituisce il percorso o None."""
        self.sync_notes()
        lines = ["Post-it — esportato il " + time.strftime("%d/%m/%Y %H:%M"), ""]
        for k in keys:
            n, d = NOTES[note_color(k)], self.data["notes"][k]
            lines.append("■ %s · %s" % (self.note_label(k), n["name"]))
            if n["notes"]:
                lines.append(markdown_to_plain(d["text"]).strip() or "(nessuna nota)")
                if n["todo"]:
                    lines.append("")
            if n["todo"]:
                for t in d["todos"]:
                    text = "".join(s for s, _b, _i in parse_inline(t["text"]))
                    if t.get("h"):
                        lines.append(("" if lines[-1] == "" else "\n") + text.upper())
                    else:
                        lines.append("%s %s" % ("☑" if t["done"] else "☐", text))
                if not d["todos"]:
                    lines.append("(nessuna attività)")
            lines.append("")
        which = "tutti" if len(keys) > 1 else self.note_label(keys[0])
        folder = os.path.join(documents_dir(), "Post-it")
        path = os.path.join(folder, "Post-it %s %s.txt" % (which, time.strftime("%Y-%m-%d %H-%M-%S")))
        try:
            os.makedirs(folder, exist_ok=True)
            with open(path, "w", encoding="utf-8-sig") as f:
                f.write("\n".join(lines))
        except OSError:
            return None
        return path

    # ------------------------------------------------------------ interfaccia
    def render(self):
        self.sync_notes()
        if self.container is not None:
            self.container.destroy()
        self.notes_widget = self.entry = self.list_frame = self.rich = None
        self.row_labels = []
        c = self.c = NOTES[self.data["current"]]
        self.root.configure(bg=c["bg"])
        self.container = tk.Frame(self.root, bg=c["bg"])
        self.container.pack(fill="both", expand=True)
        self.build_header(c)
        if self.mode != "collapsed":
            self.build_footer(c)
            body = tk.Frame(self.container, bg=c["bg"])
            body.pack(fill="both", expand=True, padx=self.px(10), pady=(self.px(6), 0))
            if c["notes"] and c["todo"]:
                # note e task divisi esattamente a metà
                body.rowconfigure(0, weight=1, uniform="half")
                body.rowconfigure(2, weight=1, uniform="half")
                body.columnconfigure(0, weight=1)
                self.build_notes(body).grid(row=0, column=0, sticky="nsew")
                tk.Frame(body, bg=c["soft"], height=1).grid(row=1, column=0, sticky="ew",
                                                             pady=self.px(6))
                self.build_todo(body).grid(row=2, column=0, sticky="nsew")
            elif c["notes"]:
                self.build_notes(body).pack(fill="both", expand=True)
            else:
                self.build_todo(body).pack(fill="both", expand=True)
        for k, f in self.edges.items():
            top = k in ("n", "nw", "ne") or self.mode == "collapsed"
            f.configure(bg=c["head"] if top else c["bg"])
            f.lift()
        self.update_hint()

    def icon_button(self, parent, text, cmd, tip, fg, font=None):
        b = tk.Label(parent, text=text, bg=parent["bg"], fg=fg, font=font or self.f_icon,
                     cursor="hand2", padx=self.px(5))
        b.bind("<Button-1>", lambda _e: cmd())
        Tooltip(b, tip)
        return b

    def drawn_icon(self, parent, kind, color, cursor="hand2"):
        """Icone disegnate a mano (nitide a ogni risoluzione)."""
        p = self.px
        w, h = p(20), p(18)
        cv = tk.Canvas(parent, width=w, height=h, bg=parent["bg"], highlightthickness=0,
                       cursor=cursor)
        lw = max(1, p(1.5))
        line = dict(width=lw, tags="line", capstyle="round", joinstyle="round")
        if kind == "export":   # freccia verso il basso su una base
            cv.create_line(w / 2, p(3), w / 2, p(11), **line)
            cv.create_line(w / 2 - p(4), p(7), w / 2, p(11), w / 2 + p(4), p(7), **line)
            cv.create_line(p(4), p(14.5), w - p(4), p(14.5), **line)
        elif kind == "keys":   # tastiera
            cv.create_rectangle(p(2), p(3.5), w - p(2), p(14.5), width=lw, tags="frame")
            for y in (p(6.5), p(9)):
                for i in range(4):
                    x = p(5) + i * p(3.3)
                    cv.create_rectangle(x, y, x + p(1.3), y + p(1.2), tags="box")
            cv.create_line(p(7), p(12), w - p(7), p(12), **line)
        elif kind == "grip":   # angolo per ridimensionare
            for d in (p(5), p(9), p(13)):
                cv.create_line(w - p(3), h - p(3) - d, w - p(3) - d, h - p(3),
                               width=max(1, p(1)), tags="line")
        elif kind == "share":  # «condividi» di Apple: riquadro aperto con freccia in su
            cv.create_line(p(7), p(7.5), p(5), p(7.5), p(5), p(16), w - p(5), p(16),
                           w - p(5), p(7.5), w - p(7), p(7.5), **line)
            cv.create_line(w / 2, p(2), w / 2, p(11), **line)
            cv.create_line(w / 2 - p(3), p(5), w / 2, p(2), w / 2 + p(3), p(5), **line)
        elif kind in ("pin", "pin_off"):  # puntina in stile SF Symbols
            fill = "line" if kind == "pin" else ""
            cv.create_oval(w / 2 - p(4.5), p(2), w / 2 + p(4.5), p(9), width=lw,
                           tags=("frame", "dot") if fill else "frame")
            cv.create_line(w / 2, p(9), w / 2, p(16), **line)
        elif kind in ("up", "down"):  # freccia a V per riduci / espandi
            a, b = (p(11), p(7)) if kind == "up" else (p(7), p(11))
            cv.create_line(w / 2 - p(4.5), a, w / 2, b, w / 2 + p(4.5), a, **line)
        self.color_icon(cv, color)
        return cv

    @staticmethod
    def color_icon(cv, color):
        cv.itemconfigure("line", fill=color)
        cv.itemconfigure("box", fill=color, outline=color)
        cv.itemconfigure("frame", outline=color)
        cv.itemconfigure("dot", fill=color)

    def faint_button(self, parent, kind, cmd, tip):
        cv = self.drawn_icon(parent, kind, FAINT)
        cv.bind("<Button-1>", lambda _e: cmd())
        cv.bind("<Enter>", lambda _e: self.color_icon(cv, self.c["ink"]), add="+")
        cv.bind("<Leave>", lambda _e: self.color_icon(cv, FAINT), add="+")
        Tooltip(cv, tip)
        return cv

    def build_header(self, c):
        h = tk.Frame(self.container, bg=c["head"], height=self.header_h)
        h.pack(fill="x", side="top")
        h.pack_propagate(False)

        tabs = tk.Frame(h, bg=c["head"])
        tabs.pack(side="left", padx=(self.px(8), self.px(4)))
        size = self.px(18 if IS_MAC else 16)
        for i, key in enumerate(ORDER, start=1):
            n = NOTES[key]
            page = self.data["page"][key]
            cur = key == self.data["current"]
            if IS_MAC:   # pallini come i tag colorati del Finder
                dot = tk.Canvas(tabs, width=size, height=size, bg=c["head"], cursor="hand2",
                                highlightthickness=0)
                dot.create_oval(1, 1, size - 1, size - 1, fill=n["bg"], width=2 if cur else 1,
                                outline=c["ink"] if cur else n["soft"])
            else:
                dot = tk.Canvas(tabs, width=size, height=size, bg=n["bg"], cursor="hand2",
                                highlightthickness=0)
                dot.create_rectangle(1, 1, size - 1, size - 1, width=2,
                                     outline=c["ink"] if cur else n["head"])
            dot.pack(side="left", padx=self.px(3 if IS_MAC else 2))
            if cur:  # quale dei due post-it di questo colore è aperto
                dot.create_text(size / 2, size / 2 + 0.5, text=str(page + 1),
                                fill=n["ink"], font=self.font(7, bold=True))
            dot.bind("<Button-1>", lambda _e, k=key: self.switch(k))
            other = note_id(key, 1 - page)
            tip = ("%s · %s  (%d)" % (self.note_label(note_id(key, page)), n["name"], i) +
                   ("\nClicca di nuovo: %s" % self.note_label(other) if cur else ""))
            Tooltip(dot, tip)

        title = tk.Label(h, text=c["name"], bg=c["head"], fg=c["ink"], font=self.f_head,
                         anchor="w", cursor="fleur")
        self.title_lbl = title

        collapsed = self.mode == "collapsed"
        on = self.data["topmost"]
        pin_tip = "Sempre in primo piano: " + ("ATTIVO" if on else "SPENTO")
        if IS_MAC:   # icone sottili in stile SF Symbols; per chiudere c'è il pallino rosso
            for kind, cmd, tip, color in (
                    ("down" if collapsed else "up", self.toggle_collapse,
                     "Espandi" if collapsed else "Riduci", c["ink"]),
                    ("pin" if on else "pin_off", self.toggle_topmost, pin_tip,
                     c["ink"] if on else c["soft"])):
                b = self.drawn_icon(h, kind, color)
                b.bind("<Button-1>", lambda _e, f=cmd: f())
                Tooltip(b, tip)
                b.pack(side="right", padx=(0, self.px(6)))
        else:
            self.icon_button(h, "✕", self.hide_window,
                             "Nascondi (riapri con %s)" % combo_label(
                                 self.data["hotkeys"]["write"]),
                             c["ink"]).pack(side="right", padx=(0, self.px(4)))
            self.icon_button(h, "▾" if collapsed else "▴", self.toggle_collapse,
                             "Espandi" if collapsed else "Riduci", c["ink"]).pack(side="right")
            self.icon_button(h, "📌" if on else "📍", self.toggle_topmost, pin_tip,
                             c["ink"] if on else c["soft"]).pack(side="right")
        # il titolo per ultimo: se un avviso è lungo si accorcia lui, non i pulsanti
        title.pack(side="left", fill="both", expand=True, padx=4)

        for w in (h, title):
            w.bind("<ButtonPress-1>", self.start_move)
            w.bind("<B1-Motion>", self.do_move)
            w.bind("<ButtonRelease-1>", self.end_drag)
            w.bind("<Double-Button-1>", lambda _e: self.toggle_collapse())

    def build_footer(self, c):
        f = tk.Frame(self.container, bg=c["bg"])
        f.pack(fill="x", side="bottom")
        if c["todo"]:
            clr = tk.Label(f, text="Rimuovi completate", bg=c["bg"], fg=c["soft"],
                           font=self.f_small, cursor="hand2")
            clr.pack(side="left", padx=self.px(10), pady=2)
            clr.bind("<Button-1>", lambda _e: self.clear_done())
        if IS_WIN:   # su Mac l'angolo per ridimensionare lo dà già la finestra
            grip = self.drawn_icon(f, "grip", c["soft"], cursor="size_nw_se")
            grip.pack(side="right", padx=(0, 1), pady=(0, 1))
            grip.bind("<ButtonPress-1>", lambda e: self.start_resize(e, "se"))
            grip.bind("<B1-Motion>", self.do_resize)
            grip.bind("<ButtonRelease-1>", self.end_drag)
        keys = self.faint_button(f, "keys", lambda: self.toggle_popup(SettingsPanel, keys),
                                 "Scorciatoie e impostazioni")
        keys.pack(side="right", padx=(0, self.px(8 if IS_MAC else 2)))
        exp = self.faint_button(f, "share" if IS_MAC else "export",
                                lambda: self.toggle_popup(ExportMenu, exp), "Esporta")
        exp.pack(side="right", padx=(0, self.px(2)))

    # ----- note
    def build_notes(self, parent):
        self.rich = RichNote(self, parent, self.current_id())
        t = self.notes_widget = self.rich.t
        t.bind("<Button-1>", lambda _e: t.focus_force(), add="+")
        return t

    # ----- todo
    def build_todo(self, parent):
        c = self.c
        wrap = tk.Frame(parent, bg=c["bg"])
        add = tk.Frame(wrap, bg=c["bg"])
        add.pack(fill="x", pady=(0, 4))
        tk.Label(add, text="+", bg=c["bg"], fg=c["soft"], font=self.f_head).pack(side="left")
        placeholder = "Aggiungi attività e premi Invio"
        e = tk.Entry(add, bg=c["bg"], fg=c["soft"], insertbackground=c["ink"], relief="flat",
                     font=self.f_norm, highlightthickness=0, bd=0)
        e.pack(side="left", fill="x", expand=True, padx=(4, 0))
        e.insert(0, placeholder)
        tk.Frame(wrap, bg=c["soft"], height=1).pack(fill="x", pady=(0, 4))

        def showing_placeholder():
            return e.cget("fg") == c["soft"]

        def focus_in(_e=None):
            if showing_placeholder():
                e.delete(0, "end")
                e.config(fg=c["ink"])

        def focus_out(_e=None):
            if not e.get():
                e.insert(0, placeholder)
                e.config(fg=c["soft"])

        def submit(_e=None):
            txt = e.get().strip()
            if txt and not showing_placeholder():
                m = re.match(r"(#{1,3})\s+(\S.*)", txt)   # "# Spesa" = titolo di sezione
                item = {"text": m.group(2), "done": False, "h": len(m.group(1))} if m else \
                    {"text": txt, "done": False}
                self.note()["todos"].append(item)
                self.schedule_save()
                e.delete(0, "end")
                self.refresh_list()
                self.root.after(10, lambda: canvas.yview_moveto(1.0))

        e.bind("<FocusIn>", focus_in)
        e.bind("<FocusOut>", focus_out)
        e.bind("<Return>", submit)
        e.bind("<Button-1>", lambda _e: e.focus_force(), add="+")
        if c["notes"]:  # post-it verde: Tab torna alle note
            def to_notes(_e):
                if self.notes_widget is not None:
                    self.notes_widget.focus_force()
                return "break"
            e.bind("<Tab>", to_notes)
        self.entry, self.entry_focus_in, self.entry_submit = e, focus_in, submit

        canvas = tk.Canvas(wrap, bg=c["bg"], highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        self.list_frame = tk.Frame(canvas, bg=c["bg"])
        win = canvas.create_window((0, 0), window=self.list_frame, anchor="nw")

        def on_canvas(ev):
            canvas.itemconfigure(win, width=ev.width)
            self.wrap_px = max(80, ev.width - self.px(50))
            for lbl in self.row_labels:
                lbl.configure(wraplength=self.wrap_px)

        def on_wheel(ev):
            if canvas.winfo_exists() and self.list_frame.winfo_reqheight() > canvas.winfo_height():
                # Windows: multipli di 120 per scatto; Mac: piccoli passi del trackpad
                step = -ev.delta if IS_MAC else int(-ev.delta / 120)
                if step:
                    canvas.yview_scroll(step, "units")

        self.list_frame.bind("<Configure>",
                             lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", on_canvas)
        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", on_wheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))
        self.refresh_list()
        return wrap

    def refresh_list(self):
        c = self.c
        for w in self.list_frame.winfo_children():
            w.destroy()
        self.row_labels = []
        todos = self.note()["todos"]
        if not todos:
            tk.Label(self.list_frame, text="Nessuna attività", bg=c["bg"], fg=c["soft"],
                     font=self.f_small).pack(anchor="w", pady=4)
        for i, item in enumerate(todos):
            segs = parse_inline(item["text"])
            text = "".join(s for s, _b, _i in segs) or item["text"]
            bold = bool(segs) and all(b for _s, b, _i in segs)
            italic = bool(segs) and all(it for _s, _b, it in segs)
            row = tk.Frame(self.list_frame, bg=c["bg"])
            row.pack(fill="x", pady=(self.px(6) if item.get("h") and i else 1, 1))
            dl = tk.Label(row, text="✕", bg=c["bg"], fg=c["soft"], font=self.f_small,
                          cursor="hand2")
            dl.pack(side="right", anchor="n", padx=(4, 0))
            dl.bind("<Button-1>", lambda _e, k=i: self.delete(k))
            if item.get("h"):           # titolo di sezione: niente casella
                size = HEADINGS["h%d" % item["h"]]
                lbl = tk.Label(row, text=text, bg=c["bg"], fg=c["ink"], anchor="w",
                               font=self.font(size, True, italic), justify="left",
                               wraplength=self.wrap_px)
                lbl.pack(side="left", fill="x", expand=True)
                self.row_labels.append(lbl)
                continue
            done = item["done"]
            fg = c["soft"] if done else c["ink"]
            row.configure(cursor="hand2")
            if IS_MAC:   # cerchio come in Promemoria: pieno con la spunta quando è fatto
                s = self.px(18)
                box = tk.Canvas(row, width=s + 2, height=s + 4, bg=c["bg"], highlightthickness=0,
                                cursor="hand2")
                if done:
                    box.create_oval(1, 3, s, s + 2, fill=c["soft"], outline=c["soft"])
                    box.create_line(s * .3, s * .55 + 2, s * .45, s * .72 + 2, s * .72, s * .36 + 2,
                                    fill="white", width=2, capstyle="round", joinstyle="round")
                else:
                    box.create_oval(1, 3, s, s + 2, outline=c["soft"], width=1.5)
            else:
                box = tk.Label(row, text="☑" if done else "☐", bg=c["bg"], fg=fg,
                               font=self.f_icon, cursor="hand2")
            box.pack(side="left", anchor="n")
            lbl = tk.Label(row, text=text, bg=c["bg"], fg=fg,
                           font=self.font(11, bold, italic, over=done), justify="left",
                           anchor="w", wraplength=self.wrap_px, cursor="hand2")
            lbl.pack(side="left", fill="x", expand=True, padx=(4, 0))
            for w in (row, box, lbl):
                w.bind("<Button-1>", lambda _e, k=i: self.toggle(k))
            self.row_labels.append(lbl)

    def toggle(self, i):
        t = self.note()["todos"][i]
        t["done"] = not t["done"]
        self.schedule_save()
        self.refresh_list()

    def delete(self, i):
        del self.note()["todos"][i]
        self.schedule_save()
        self.refresh_list()

    def clear_done(self):
        self.note()["todos"] = [t for t in self.note()["todos"] if not t["done"]]
        self.schedule_save()
        self.refresh_list()


def main():
    sys.excepthook = lambda t, e, tb: log_error("programma", e.with_traceback(tb))
    threading.excepthook = lambda a: log_error("thread %s" % a.thread, a.exc_value)
    try:   # anche gli arresti gravi (rari) finiscono nel registro
        import faulthandler
        os.makedirs(APP_DIR, exist_ok=True)
        faulthandler.enable(open(LOG_FILE + ".crash", "a"))
    except (OSError, RuntimeError, AttributeError):
        pass
    if IS_WIN:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # testo nitido
        except (AttributeError, OSError):
            user32.SetProcessDPIAware()
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except (AttributeError, OSError):
            pass
    if signal_existing_instance():
        log("già aperto: chiedo all'altra copia di mostrarsi")
        return
    if autostart_enabled():
        set_autostart(True)  # aggiorna il percorso se il programma è stato spostato
    # all'accensione il desktop può non essere ancora pronto: se l'avvio fallisce si
    # riprova qualche volta invece di sparire in silenzio
    attempts = 4 if "--autostart" in sys.argv else 1
    for attempt in range(1, attempts + 1):
        try:
            PostItApp().run()
            log("uscita normale")
            return
        except Exception as exc:  # noqa: BLE001
            log_error("avvio, tentativo %d di %d" % (attempt, attempts), exc)
            if attempt < attempts:
                time.sleep(5 * attempt)


if __name__ == "__main__":
    main()
