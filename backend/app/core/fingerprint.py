"""
DigitalPersona U.are.U fingerprint integration via pythonnet.

Architecture — continuous-capture SDK mode:
  - WinForms daemon thread owns the form, reader, and message pump
  - CaptureAsync called ONCE at startup — SDK stays armed indefinitely
  - On_Captured fires continuously for every finger placement
  - NO re-arming after each callback — SDK handles this internally
  - _rearm only on: startup, reopen after sleep/wake, explicit recovery
  - _touch_queue: signals finger placement (for /finger-touch)
  - _fid_queue:   delivers FID objects    (for /scan -> identify)
"""

import base64
import logging
import os
import queue
import sys
import threading
from typing import Optional

log = logging.getLogger(__name__)

SCANNER_AVAILABLE = False
_dp               = None
_service          = None
_enroll_progress  = 0   # 0=idle, 1-3=scan count, -1=failed

PROBABILITY_ONE = 0x7FFFFFFF
MATCH_THRESHOLD = int(PROBABILITY_ONE / 100000)

_SDK_CANDIDATES = [
    r"C:\Program Files\DigitalPersona\U.are.U SDK\Windows\Bin",
    r"C:\Program Files\Crossmatch\U.are.U SDK\Windows\Bin",
    r"C:\Program Files (x86)\DigitalPersona\U.are.U SDK\Windows\Bin",
    r"C:\Program Files (x86)\Crossmatch\U.are.U SDK\Windows\Bin",
    r"C:\Program Files\DigitalPersona\U.are.U SDK\Windows\Lib\DotNET",
    os.path.dirname(sys.executable),
    os.path.dirname(os.path.abspath(__file__)),
]


def _find_sdk_dir() -> Optional[str]:
    for path in _SDK_CANDIDATES:
        if os.path.isfile(os.path.join(path, "DPUruNet.dll")):
            return path
    return None


class _FingerprintService:
    """
    Mirrors testpy2.py IdentifyForm pattern exactly.
    Scanner is always armed. External threads only read queues.
    """

    def __init__(self, dp_module):
        self._dp          = dp_module
        self._reader      = None
        self._ready       = threading.Event()
        self._fid_queue   = queue.Queue()
        self._touch_queue = queue.Queue()
        self._capture_count = 0
        self._enrolling   = threading.Event()  # set during enrollment; scanner loop backs off

        t = threading.Thread(target=self._run, daemon=True, name="FPWinForms")
        t.start()
        if not self._ready.wait(timeout=15):
            log.warning("FP: reader did not open within 15s")

    def _run(self):
        log.warning("FP[thread]: _run started")
        try:
            import clr
            clr.AddReference("System.Windows.Forms")
            from System.Windows.Forms import Application, Form

            dp   = self._dp
            clr.AddReference("System.Drawing")
            from System.Drawing import Point, Size
            from System.Windows.Forms import FormBorderStyle as FBS, FormWindowState

            form = Form()
            form.ShowInTaskbar   = False
            form.Opacity         = 0
            form.WindowState     = FormWindowState.Minimized
            form.FormBorderStyle = getattr(FBS, "None")
            form.Size            = Size(1, 1)
            form.Location        = Point(-32000, -32000)

            def _on_shown(sender, args):
                form.Hide()
            from System import EventHandler
            form.Shown += EventHandler(_on_shown)

            log.warning("FP[thread]: getting readers...")
            readers = dp.ReaderCollection.GetReaders()
            log.warning(f"FP[thread]: reader count = {readers.Count}")

            if readers.Count == 0:
                log.warning("FP[thread]: no readers found")
                self._ready.set()
                return

            reader = readers[0]
            log.warning(f"FP[thread]: using reader: {reader.Description.Name}")

            result = reader.Open(dp.Constants.CapturePriority.DP_PRIORITY_EXCLUSIVE)
            log.warning(f"FP[thread]: Open result = {result}")

            if result != dp.Constants.ResultCode.DP_SUCCESS:
                log.warning("FP[thread]: failed to open reader")
                self._ready.set()
                return

            self._reader = reader

            status = reader.GetStatus()
            log.warning(f"FP[thread]: reader status = {reader.Status.Status}")

            self._callback = dp.Reader.CaptureCallback(self._on_captured)
            reader.On_Captured += self._callback
            log.warning("FP[thread]: callback registered")

            # Wire up Windows power events for sleep/wake recovery
            try:
                clr.AddReference("Microsoft.Win32.SystemEvents")
                from Microsoft.Win32 import SystemEvents, PowerModeChangedEventArgs
                from Microsoft.Win32 import PowerModes
                svc = self

                def _on_power_mode(sender, args):
                    mode = str(args.Mode)
                    log.warning(f"FP[thread]: power mode change: {mode}")
                    if "Resume" in mode or "StatusChange" in mode:
                        log.warning("FP[thread]: wake detected -- reopening reader")
                        svc._reopen_reader()

                from System import EventHandler
                _power_handler = EventHandler[PowerModeChangedEventArgs](_on_power_mode)
                SystemEvents.PowerModeChanged += _power_handler
                log.warning("FP[thread]: power event handler registered")
            except Exception:
                log.warning("FP[thread]: sleep/wake recovery not available on this runtime")

            self._arm_capture()

            self._ready.set()
            log.warning("FP[thread]: ready -- calling Application.Run")
            Application.Run(form)
            log.warning("FP[thread]: Application.Run returned")

        except Exception as e:
            log.error(f"FP[thread]: exception: {e}")
            self._ready.set()

    def _reopen_reader(self):
        import time
        dp = self._dp
        log.warning("FP[reopen]: closing reader...")
        try:
            if self._reader:
                self._reader.CancelCapture()
                self._reader.On_Captured -= self._callback
                self._reader.Dispose()
                self._reader = None
        except Exception as e:
            log.warning(f"FP[reopen]: close error (expected): {e}")

        time.sleep(2.0)

        log.warning("FP[reopen]: reopening reader...")
        for attempt in range(5):
            try:
                readers = dp.ReaderCollection.GetReaders()
                if readers.Count == 0:
                    log.warning(f"FP[reopen]: no readers (attempt {attempt+1})")
                    time.sleep(2.0)
                    continue

                reader = readers[0]
                result = reader.Open(dp.Constants.CapturePriority.DP_PRIORITY_EXCLUSIVE)
                log.warning(f"FP[reopen]: Open result = {result}")

                if result != dp.Constants.ResultCode.DP_SUCCESS:
                    log.warning(f"FP[reopen]: open failed (attempt {attempt+1})")
                    time.sleep(2.0)
                    continue

                self._reader = reader
                self._callback = dp.Reader.CaptureCallback(self._on_captured)
                reader.On_Captured += self._callback
                for q in (self._touch_queue, self._fid_queue):
                    while not q.empty():
                        try: q.get_nowait()
                        except Exception: break
                self._arm_capture()
                log.warning("FP[reopen]: reader reopened and armed successfully")
                return
            except Exception as e:
                log.error(f"FP[reopen]: attempt {attempt+1} error: {e}")
                time.sleep(2.0)

        log.error("FP[reopen]: all reopen attempts failed -- scanner unavailable")

    def _arm_capture(self):
        dp = self._dp
        import time
        for attempt in range(10):
            try:
                resolution = self._reader.Capabilities.Resolutions[0]
                result = self._reader.CaptureAsync(
                    dp.Constants.Formats.Fid.ANSI,
                    dp.Constants.CaptureProcessing.DP_IMG_PROC_DEFAULT,
                    resolution,
                )
                log.warning(f"FP: _arm_capture attempt {attempt+1} result={result}")
                if "BUSY" not in str(result):
                    return
                time.sleep(0.5)
            except Exception as e:
                log.error(f"FP: _arm_capture error: {e}")
                return
        log.warning("FP: _arm_capture gave up after 10 attempts")

    def _on_captured(self, capture_result):
        dp = self._dp
        self._capture_count += 1
        n = self._capture_count
        log.warning(f"FP[thread]: _on_captured #{n} fired, ResultCode={capture_result.ResultCode}")
        try:
            if capture_result.ResultCode != dp.Constants.ResultCode.DP_SUCCESS:
                log.warning("FP[thread]: capture result not success -- skipping touch signal")
                self._fid_queue.put(None)
                # Device failure = reader unplugged -- trigger hotplug recovery immediately
                if "FAILURE" in str(capture_result.ResultCode):
                    log.warning("FP[thread]: DP_DEVICE_FAILURE detected -- signalling hotplug")
                    import threading as _t
                    _t.Thread(target=self._handle_device_failure,
                              daemon=True).start()
                return

            if capture_result.Data is None:
                log.warning("FP[thread]: capture data is None")
                self._fid_queue.put(None)
                return

            # Only signal touch on successful captures
            self._touch_queue.put(True)
            log.warning("FP[thread]: touch signal queued")
            log.warning("FP[thread]: FID captured OK, queuing")
            self._fid_queue.put(capture_result.Data)

        except Exception as e:
            log.error(f"FP[thread]: _on_captured error: {e}")
            self._fid_queue.put(None)

    def _handle_device_failure(self):
        """Called from _on_captured on DP_DEVICE_FAILURE (unplug). Sets SCANNER_AVAILABLE=False so hotplug watcher re-enters polling."""
        global SCANNER_AVAILABLE
        import time
        time.sleep(0.5)  # brief wait for SDK to settle
        log.warning("FP[thread]: marking scanner unavailable after device failure")
        try:
            if self._reader:
                self._reader.CancelCapture()
                self._reader.Dispose()
                self._reader = None
        except Exception as e:
            log.warning(f"FP[thread]: cleanup after failure: {e}")
        SCANNER_AVAILABLE = False
        log.warning("FP[thread]: hotplug watcher will now detect and recover")

    def wait_for_touch(self, timeout: float = 30.0) -> bool:
        log.warning(f"FP: wait_for_touch called, reader={self._reader is not None}")
        if self._reader is None:
            return False
        if self._enrolling.is_set():
            log.warning("FP: wait_for_touch -- enrollment in progress, backing off")
            import time
            time.sleep(1.0)
            return False
        drained = 0
        while not self._touch_queue.empty():
            try:
                self._touch_queue.get_nowait()
                drained += 1
            except queue.Empty:
                break
        while not self._fid_queue.empty():
            try:
                self._fid_queue.get_nowait()
            except queue.Empty:
                break
        if drained:
            log.warning(f"FP: drained {drained} stale touch signal(s)")
        log.warning("FP: waiting on touch_queue...")
        try:
            self._touch_queue.get(timeout=timeout)
            log.warning("FP: touch detected!")
            return True
        except queue.Empty:
            log.warning("FP: wait_for_touch timed out")
            return False

    def request_fid(self, timeout: float = 8.0):
        log.warning(f"FP: request_fid called, timeout={timeout}")
        if self._reader is None:
            return None
        while not self._fid_queue.empty():
            try:
                self._fid_queue.get_nowait()
            except queue.Empty:
                break
        try:
            fid = self._fid_queue.get(timeout=timeout)
            log.warning(f"FP: request_fid got FID: {fid is not None}")
            return fid
        except queue.Empty:
            log.warning("FP: request_fid timed out")
            return None

    def cancel(self):
        try:
            if self._reader:
                self._reader.CancelCapture()
        except Exception:
            pass

    @property
    def available(self) -> bool:
        return self._reader is not None


# ── Module init ───────────────────────────────────────────────

def _init():
    global SCANNER_AVAILABLE, _dp, _service
    log.warning("FP: _init called")
    try:
        import clr
    except ImportError:
        log.warning("FP: pythonnet not installed")
        return

    sdk_dir = _find_sdk_dir()
    if not sdk_dir:
        log.warning("FP: DPUruNet.dll not found")
        return
    log.warning(f"FP: SDK found at {sdk_dir}")

    if sdk_dir not in sys.path:
        sys.path.insert(0, sdk_dir)

    try:
        clr.AddReference("DPUruNet")
        import DPUruNet
        _dp = DPUruNet
        log.warning("FP: DPUruNet loaded")
    except Exception as e:
        log.warning(f"FP: failed to load DPUruNet: {e}")
        return

    _service = _FingerprintService(_dp)

    if _service.available:
        SCANNER_AVAILABLE = True
        log.warning("FP: scanner READY")
    else:
        log.warning("FP: scanner NOT available")


_init()

# ── Hot-plug watcher ──────────────────────────────────────────

def _hotplug_watcher():
    """
    Permanent background thread monitoring reader presence.
    - If reader absent on startup: polls every 5s until it appears.
    - If reader unplugged at runtime: detects via health check,
      marks scanner unavailable, waits for re-plug, re-initializes.
    Runs forever as a daemon thread.
    """
    global SCANNER_AVAILABLE
    import time
    log.warning("FP[hotplug]: watcher started")

    while True:
        # ── Phase 1: wait for reader to become available ──────
        if not SCANNER_AVAILABLE:
            log.warning("FP[hotplug]: scanner unavailable -- polling for reader every 5s")
            while not SCANNER_AVAILABLE:
                time.sleep(5)
                try:
                    if _dp is None:
                        _init()
                    else:
                        readers = _dp.ReaderCollection.GetReaders()
                        if readers.Count > 0 and (
                                _service is None or not _service.available):
                            log.warning("FP[hotplug]: reader detected -- initializing")
                            _init()
                            if SCANNER_AVAILABLE:
                                load_templates()
                                log.warning("FP[hotplug]: templates reloaded")
                except Exception as e:
                    log.warning(f"FP[hotplug]: poll error: {e}")
            log.warning("FP[hotplug]: scanner online")

        # ── Phase 2: monitor for unplug while available ───────
        time.sleep(5)
        if not SCANNER_AVAILABLE:
            continue   # already gone, loop back to phase 1

        try:
            if _service and _service._reader:
                _service._reader.GetStatus()
                state = str(_service._reader.Status.Status)
                # Unexpected states indicate reader was unplugged or reset
                if "FAILURE" in state or "DISCONNECT" in state or "UNAVAIL" in state:
                    raise RuntimeError(f"Reader state: {state}")
            elif _service and not _service.available:
                raise RuntimeError("Reader handle lost")
        except Exception as e:
            log.warning(f"FP[hotplug]: reader lost ({e}) -- marking unavailable")
            SCANNER_AVAILABLE = False
            # Clean up stale service
            try:
                if _service and _service._reader:
                    _service._reader.CancelCapture()
                    _service._reader.Dispose()
                    _service._reader = None
            except Exception:
                pass
            # Loop back to phase 1 to wait for re-plug


import threading as _ht
_ht.Thread(target=_hotplug_watcher, daemon=True,
           name="FPHotPlug").start()

# ── Graceful shutdown ─────────────────────────────────────────

import atexit as _atexit

def _shutdown():
    global SCANNER_AVAILABLE
    if _service and _service._reader:
        try:
            _service._reader.CancelCapture()
            _service._reader.Dispose()
            log.warning("FP: reader closed gracefully on shutdown")
        except Exception as e:
            log.warning(f"FP: shutdown close error: {e}")
    SCANNER_AVAILABLE = False

_atexit.register(_shutdown)


# ── Template cache ────────────────────────────────────────────

_cache: dict[str, bytes] = {}


def load_templates() -> None:
    if not SCANNER_AVAILABLE:
        return
    from app.core.firestore_client import clients as col
    _cache.clear()
    for doc in col().stream():
        d    = doc.to_dict()
        tmpl = d.get("fingerprint_template")
        if tmpl:
            try:
                _cache[doc.id] = base64.b64decode(tmpl.encode())
            except Exception:
                pass
    log.warning(f"FP: loaded {len(_cache)} template(s) into cache")


def update_template_cache(client_name: str, b64: str) -> None:
    try:
        _cache[client_name] = base64.b64decode(b64.encode())
    except Exception:
        pass


def remove_from_cache(client_name: str) -> None:
    _cache.pop(client_name, None)


# ── Internal helpers ──────────────────────────────────────────

def _fid_to_fmd_bytes(fid) -> Optional[bytes]:
    dp = _dp
    try:
        result = dp.FeatureExtraction.CreateFmdFromFid(
            fid, dp.Constants.Formats.Fmd.ANSI)
        if result.ResultCode != dp.Constants.ResultCode.DP_SUCCESS:
            log.error(f"FP: CreateFmdFromFid failed: {result.ResultCode}")
            return None
        return bytes(result.Data.Bytes)
    except Exception as e:
        log.error(f"FP: _fid_to_fmd_bytes error: {e}")
        return None


def _bytes_to_fmd(raw: bytes):
    dp = _dp
    try:
        result = dp.Importer.ImportFmd(
            raw, dp.Constants.Formats.Fmd.ANSI, dp.Constants.Formats.Fmd.ANSI)
        if result.ResultCode != dp.Constants.ResultCode.DP_SUCCESS:
            return None
        return result.Data
    except Exception as e:
        log.error(f"FP: _bytes_to_fmd error: {e}")
        return None


# ── Public API ────────────────────────────────────────────────

def wait_for_touch(timeout: float = 30.0) -> bool:
    if not SCANNER_AVAILABLE:
        log.warning("FP: wait_for_touch -- scanner not available")
        return False
    return _service.wait_for_touch(timeout=timeout)


def get_enroll_progress() -> int:
    """Returns current enrollment scan count: 0=idle, 1-3=scanning, -1=failed."""
    return _enroll_progress


def identify_from_cache(rearm: bool = False) -> Optional[str]:
    """
    Read next FID from queue and compare against cached templates.
    rearm is ignored -- scanner is always armed.
    """
    if not SCANNER_AVAILABLE or not _cache:
        log.warning(f"FP: identify_from_cache -- available={SCANNER_AVAILABLE} cache={len(_cache)}")
        return None

    log.warning("FP: identify_from_cache -- reading FID from queue")
    try:
        fid = _service._fid_queue.get(timeout=7)
    except queue.Empty:
        log.warning("FP: identify_from_cache -- FID queue timeout")
        return None

    if fid is None:
        log.warning("FP: identify_from_cache -- FID is None")
        return None

    log.warning("FP: identify_from_cache -- extracting FMD")
    probe_bytes = _fid_to_fmd_bytes(fid)
    if probe_bytes is None:
        return None

    probe_fmd = _bytes_to_fmd(probe_bytes)
    if probe_fmd is None:
        return None

    dp         = _dp
    best_name  = None
    best_score = MATCH_THRESHOLD

    for client_name, stored_bytes in _cache.items():
        try:
            stored_fmd = _bytes_to_fmd(stored_bytes)
            if stored_fmd is None:
                continue
            cmp = dp.Comparison.Compare(probe_fmd, 0, stored_fmd, 0)
            if cmp.ResultCode != dp.Constants.ResultCode.DP_SUCCESS:
                continue
            if cmp.Score < best_score:
                best_score = cmp.Score
                best_name  = client_name
        except Exception as e:
            log.warning(f"FP: compare error for {client_name}: {e}")

    log.warning(f"FP: identify result = {best_name!r} score={best_score}")
    return best_name


def enroll_finger() -> Optional[str]:
    if not SCANNER_AVAILABLE:
        return None

    global _enroll_progress
    dp   = _dp

    _service._enrolling.set()
    log.warning("FP: enroll mode ON -- scanner loop backing off")

    import time
    time.sleep(0.5)
    while not _service._fid_queue.empty():
        try: _service._fid_queue.get_nowait()
        except queue.Empty: break
    while not _service._touch_queue.empty():
        try: _service._touch_queue.get_nowait()
        except queue.Empty: break

    fmds = []
    try:
        for i in range(3):
            _enroll_progress = i + 1
            log.warning(f"FP: enroll scan {i+1}/3 -- waiting for finger...")
            try:
                fid = _service._fid_queue.get(timeout=8)
            except queue.Empty:
                log.error(f"FP: enroll scan {i+1} timed out")
                _enroll_progress = -1
                return None
            if fid is None:
                _enroll_progress = -1
                return None
            fmd_bytes = _fid_to_fmd_bytes(fid)
            if fmd_bytes is None:
                _enroll_progress = -1
                return None
            fmds.append(fmd_bytes)
            log.warning(f"FP: enroll scan {i+1} captured OK")
    finally:
        _enroll_progress = 0
        _service._enrolling.clear()
        log.warning("FP: enroll mode OFF -- scanner loop resuming")

    try:
        dotnet_fmds = [_bytes_to_fmd(fb) for fb in fmds]
        if None in dotnet_fmds:
            return None
        from System.Collections.Generic import List
        import DPUruNet as _DPNet
        fmd_list = List[_DPNet.Fmd](dotnet_fmds)
        enroll   = dp.Enrollment.CreateEnrollmentFmd(
            dp.Constants.Formats.Fmd.ANSI, fmd_list)
        if enroll.ResultCode == dp.Constants.ResultCode.DP_SUCCESS:
            return base64.b64encode(bytes(enroll.Data.Bytes)).decode()
        log.warning(f"FP: enrollment FMD failed ({enroll.ResultCode}), using first capture")
        return base64.b64encode(fmds[0]).decode()
    except Exception as e:
        log.warning(f"FP: enrollment error: {e}, using first capture")
        return base64.b64encode(fmds[0]).decode()


def verify(client_name: str) -> bool:
    if not SCANNER_AVAILABLE or client_name not in _cache:
        return False
    try:
        fid = _service._fid_queue.get(timeout=7)
    except queue.Empty:
        return False
    if fid is None:
        return False
    probe_bytes = _fid_to_fmd_bytes(fid)
    if probe_bytes is None:
        return False
    dp         = _dp
    probe_fmd  = _bytes_to_fmd(probe_bytes)
    stored_fmd = _bytes_to_fmd(_cache[client_name])
    if probe_fmd is None or stored_fmd is None:
        return False
    try:
        cmp = dp.Comparison.Compare(probe_fmd, 0, stored_fmd, 0)
        return cmp.ResultCode == dp.Constants.ResultCode.DP_SUCCESS \
               and cmp.Score < MATCH_THRESHOLD
    except Exception as e:
        log.error(f"FP: verify error: {e}")
        return False