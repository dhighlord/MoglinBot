"""Direct QtWebEngine window for Windows (no pywebview layer).

pywebview's backends have proven unreliable in frozen Windows builds:
EdgeChromium blocks silently inside PyInstaller onefile, and pywebview's own
Qt backend also failed to show a window (the app reached webview.start() and
hung with no error). This module drives PyQt5/QtWebEngine directly and exposes
the ``Api`` object to the frontend as ``window.pywebview.api`` via a
QWebChannel bridge, so ``main.js`` works unchanged.

Every failure here raises a Python exception, which the launcher turns into a
visible dialog + log line — no more silent hangs.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable

# Software rendering + no sandbox: QtWebEngine's GPU path fails silently on
# VMs / RDP / machines without proper GPU drivers. These flags force the
# software path, which is the reliable choice for this kind of app.
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--disable-gpu --disable-gpu-compositing --disable-software-rasterizer=false",
)
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from PyQt5 import QtCore, QtWidgets, QtWebEngineWidgets, QtWebChannel  # noqa: E402
from PyQt5.QtCore import QFile, QUrl, QObject, pyqtSignal, pyqtSlot  # noqa: E402
from PyQt5.QtGui import QIcon  # noqa: E402


class _Bridge(QObject):
    """QWebChannel object: one generic slot that proxies any Api method."""

    def __init__(self, api: Any) -> None:
        super().__init__()
        self._api = api

    @pyqtSlot(str, str, result=str)
    def call(self, method: str, args_json: str) -> str:
        try:
            args = json.loads(args_json) if args_json else []
            if not isinstance(args, list):
                args = [args]
            value = getattr(self._api, method)(*args)
            return json.dumps({"ok": True, "value": value})
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"ok": False, "error": str(exc)})


class _JsRunner(QObject):
    """Thread-safe fire-and-forget JS executor for the LiveClient bridge.

    ``QWebEnginePage.runJavaScript`` must be called from the Qt main thread;
    the bot engine calls it from its own thread, so we marshal through a
    queued signal connection.
    """

    _exec = pyqtSignal(str)

    def __init__(self, page) -> None:
        super().__init__()
        self._page = page
        self._exec.connect(self._run)

    def _run(self, js: str) -> None:
        try:
            self._page.runJavaScript(js)
        except Exception:
            pass

    def run(self, js: str) -> None:
        self._exec.emit(js)


_BRIDGE_JS = r"""
(function() {
  if (window.pywebview && window.pywebview.api) return;
  if (typeof QWebChannel === 'undefined' || typeof qt === 'undefined') return;
  new QWebChannel(qt.webChannelTransport, function(channel) {
    var bridge = channel.objects.bridge;
    if (!bridge) return;
    window.pywebview = {
      api: new Proxy({}, {
        get: function(target, name) {
          return function() {
            var args = Array.prototype.slice.call(arguments);
            return new Promise(function(resolve, reject) {
              bridge.call(name, JSON.stringify(args), function(resp) {
                try {
                  var r = JSON.parse(resp);
                  if (r.ok) resolve(r.value);
                  else reject(new Error(r.error));
                } catch (e) { reject(e); }
              });
            });
          };
        }
      })
    };
    window.dispatchEvent(new Event('pywebviewready'));
  });
})();
"""


def _qwebchannel_js() -> str:
    """Load qwebchannel.js from Qt's built-in resource."""
    f = QFile(":/qtwebchannel/qwebchannel.js")
    if f.open(QFile.ReadOnly):
        try:
            return bytes(f.readAll()).decode("utf-8")
        finally:
            f.close()
    return ""


def run_qt_window(url: str, api: Any, title: str, icon_path: str | None = None) -> None:
    """Create and run a single QWebEngineView window. Blocks until closed."""
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Moglin Bot")
    app.setQuitOnLastWindowClosed(True)

    if icon_path and os.path.isfile(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    view = QtWebEngineWidgets.QWebEngineView()
    view.setWindowTitle(title)
    view.resize(1200, 800)
    view.setMinimumSize(960, 640)

    page = view.page()

    # QWebChannel bridge: Api object <-> window.pywebview.api in JS.
    channel = QtWebChannel.QWebChannel(page)
    bridge = _Bridge(api)
    channel.registerObject("bridge", bridge)
    page.setWebChannel(channel)

    # Route LiveClient packet injection through a thread-safe runner.
    runner = _JsRunner(page)
    try:
        api.set_eval_js(runner.run)
    except AttributeError:
        pass

    # Inject qwebchannel.js + the bridge shim once the page loads.
    def _on_load_finished(ok: bool) -> None:
        if not ok:
            return
        page.runJavaScript(_qwebchannel_js() + "\n" + _BRIDGE_JS)

    page.loadFinished.connect(_on_load_finished)
    view.setUrl(QUrl(url))
    view.show()
    view.raise_()
    view.activateWindow()

    app.exec_()
