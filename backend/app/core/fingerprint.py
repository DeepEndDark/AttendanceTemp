"""
DigitalPersona U.are.U fingerprint integration.
Uses the .NET SDK (DPUruNet.dll) via pythonnet.

Architecture:
  A hidden WinForms form runs on a dedicated daemon thread to provide
  the message pump required by CaptureAsync/On_Captured.
  FastAPI endpoint threads communicate with it via threading.Event
  and a shared queue — no blocking of the ASGI event loop.

Identify pattern (from working test):
  CaptureAsync → On_Captured → CreateFmdFromFid →
  Comparison.Compare() loop against all cached templates.

Enroll pattern:
  3x CaptureAsync → CreateFmdFromFid each →
  Enrollment.CreateEnrollmentFmd() → store bytes(fmd.Bytes).
"""

import base64
import logging
import os
import queue
import sys
import threading
from typing import Optional

log = logging.getLogger(__name__)

SCANNER_AVAILABLE  = False
_dp                = None        # DPUruNet module reference
_service           = None        # _FingerprintService singleton

PROBABILITY_ONE    = 0x7FFFFFFF
MATCH_THRESHOLD    = int(PROBABILITY_ONE / 100000)   # FAR ≈ 0.001 %

# ── Locate DPUruNet.dll ───────────────────────────────────────
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


# ═══════════════════════════════════════════════════════════════
# WinForms service — hidden form owns the reader and message pump
# ═══════════════════════════════════════════════════════════════

class _FingerprintService:
    """
    Runs a hidden WinForms form on a background thread.
    FastAPI threads call request_fid() which triggers one CaptureAsync
    and blocks until the On_Captured callback delivers an FID or times out.
    """

    def __init__(self, dp_module):
        self._dp        = dp_module
        self._form      = None
        self._reader    = None
        self._ready     = threading.Event()   # set when form+reader are ready
        self._fid_queue = queue.Queue()       # FID results from callback
        self._capturing = False
        self._lock      = threading.Lock()

        t = threading.Thread(target=self._run, daemon=True)
        t.start()

        # Wait up to 10 s for reader to open
        if not self._ready.wait(timeout=10):
            log.warning("Fingerprint reader did not open within 10 s.")

    def _run(self):
        """Entry point for the WinForms thread."""
        try:
            import clr
            clr.AddReference("System.Windows.Forms")
            from System.Windows.Forms import Application, Form

            class _HiddenForm(Form):
                pass

            dp   = self._dp
            form = _HiddenForm()
            form.ShowInTaskbar = False
            form.Visible       = False
            self._form = form

            # Open reader
            readers = dp.ReaderCollection.GetReaders()
            if readers.Count == 0:
                log.warning("No fingerprint readers found.")
                self._ready.set()
                return

            reader = readers[0]
            log.info(f"Fingerprint reader: {reader.Description.Name}")

            result = reader.Open(
                dp.Constants.CapturePriority.DP_PRIORITY_COOPERATIVE)
            if result != dp.Constants.ResultCode.DP_SUCCESS:
                log.warning(f"Reader open failed: {result}")
                self._ready.set()
                return

            self._reader = reader
            self._callback = dp.Reader.CaptureCallback(self._on_captured)
            reader.On_Captured += self._callback
            self._ready.set()

            Application.Run(form)

        except Exception as e:
            log.error(f"Fingerprint WinForms thread error: {e}")
            self._ready.set()

    def _on_captured(self, capture_result):
        """Called by .NET on the WinForms thread after each finger scan."""
        dp = self._dp
        try:
            if capture_result.ResultCode != dp.Constants.ResultCode.DP_SUCCESS:
                self._fid_queue.put(None)
                return
            if capture_result.Data is None:
                self._fid_queue.put(None)
                return
            self._fid_queue.put(capture_result.Data)   # put FID object
        except Exception as e:
            log.error(f"_on_captured error: {e}")
            self._fid_queue.put(None)
        finally:
            with self._lock:
                self._capturing = False

    def _start_one_capture(self):
        """Arm one CaptureAsync."""
        dp = self._dp
        with self._lock:
            if self._capturing or self._reader is None:
                return
            self._capturing = True
        resolution = self._reader.Capabilities.Resolutions[0]
        self._reader.CaptureAsync(
            dp.Constants.Formats.Fid.ANSI,
            dp.Constants.CaptureProcessing.DP_IMG_PROC_DEFAULT,
            resolution,
        )

    def request_fid(self, timeout: float = 6.0):
        """
        Arm one capture, block until FID arrives or timeout.
        Returns FID object or None.
        """
        if self._reader is None:
            return None
        # Drain stale results
        while not self._fid_queue.empty():
            try:
                self._fid_queue.get_nowait()
            except queue.Empty:
                break
        self._start_one_capture()
        try:
            return self._fid_queue.get(timeout=timeout)
        except queue.Empty:
            with self._lock:
                self._capturing = False
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


# ═══════════════════════════════════════════════════════════════
# Module initialisation
# ═══════════════════════════════════════════════════════════════

def _init():
    global SCANNER_AVAILABLE, _dp, _service

    try:
        import clr
    except ImportError:
        log.warning("pythonnet not installed (pip install pythonnet). "
                    "Fingerprint disabled.")
        return

    sdk_dir = _find_sdk_dir()
    if not sdk_dir:
        log.warning("DPUruNet.dll not found. Fingerprint disabled.")
        return

    if sdk_dir not in sys.path:
        sys.path.insert(0, sdk_dir)

    try:
        clr.AddReference("DPUruNet")
        import DPUruNet
        _dp = DPUruNet
        log.info(f"DPUruNet loaded from {sdk_dir}")
    except Exception as e:
        log.warning(f"Failed to load DPUruNet: {e}")
        return

    _service = _FingerprintService(_dp)

    if _service.available:
        SCANNER_AVAILABLE = True
        log.info("Fingerprint scanner ready.")
    else:
        log.warning("Fingerprint scanner not available — manual mode.")


_init()


# ═══════════════════════════════════════════════════════════════
# Template cache  {client_name: raw_fmd_bytes}
# ═══════════════════════════════════════════════════════════════

_cache: dict[str, bytes] = {}


def load_templates() -> None:
    """Load all client fingerprint templates into memory at startup."""
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
    log.info(f"Loaded {len(_cache)} fingerprint template(s) into cache.")


def update_template_cache(client_name: str, b64: str) -> None:
    try:
        _cache[client_name] = base64.b64decode(b64.encode())
    except Exception:
        pass


def remove_from_cache(client_name: str) -> None:
    _cache.pop(client_name, None)


# ═══════════════════════════════════════════════════════════════
# Internal: FID → FMD bytes
# ═══════════════════════════════════════════════════════════════

def _fid_to_fmd_bytes(fid) -> Optional[bytes]:
    """Convert a captured FID object to raw FMD bytes."""
    dp = _dp
    try:
        result = dp.FeatureExtraction.CreateFmdFromFid(
            fid,
            dp.Constants.Formats.Fmd.ANSI,
        )
        if result.ResultCode != dp.Constants.ResultCode.DP_SUCCESS:
            log.error(f"CreateFmdFromFid failed: {result.ResultCode}")
            return None
        return bytes(result.Data.Bytes)
    except Exception as e:
        log.error(f"_fid_to_fmd_bytes error: {e}")
        return None


def _bytes_to_fmd(raw: bytes):
    """Import raw FMD bytes back into a DPUruNet Fmd object."""
    dp = _dp
    try:
        result = dp.Importer.ImportFmd(
            raw,
            dp.Constants.Formats.Fmd.ANSI,
            dp.Constants.Formats.Fmd.ANSI,
        )
        if result.ResultCode != dp.Constants.ResultCode.DP_SUCCESS:
            return None
        return result.Data
    except Exception as e:
        log.error(f"_bytes_to_fmd error: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════

def enroll_finger() -> Optional[str]:
    """
    Capture 3 placements → enrollment FMD → base64 string.
    Returns None on failure.
    """
    if not SCANNER_AVAILABLE:
        return None

    dp   = _dp
    fmds = []

    for i in range(3):
        log.info(f"Enrollment scan {i + 1}/3 — place finger on scanner...")
        fid = _service.request_fid(timeout=8)
        if fid is None:
            log.error(f"Enrollment scan {i + 1} failed (timeout or error).")
            return None
        fmd_bytes = _fid_to_fmd_bytes(fid)
        if fmd_bytes is None:
            return None
        fmds.append(fmd_bytes)

    # Build enrollment FMD from the 3 captures
    try:
        dotnet_fmds = []
        for fb in fmds:
            fmd_obj = _bytes_to_fmd(fb)
            if fmd_obj is None:
                return None
            dotnet_fmds.append(fmd_obj)

        # Use Enrollment.CreateEnrollmentFmd with a list of FMDs
        from System.Collections.Generic import List
        import DPUruNet as _DPNet

        fmd_list = List[_DPNet.Fmd](dotnet_fmds)
        enroll   = dp.Enrollment.CreateEnrollmentFmd(
            dp.Constants.Formats.Fmd.ANSI,
            fmd_list,
        )

        if enroll.ResultCode == dp.Constants.ResultCode.DP_SUCCESS:
            return base64.b64encode(bytes(enroll.Data.Bytes)).decode()

        log.warning(f"Enrollment FMD failed ({enroll.ResultCode}); "
                    f"storing first capture as template.")
        return base64.b64encode(fmds[0]).decode()

    except Exception as e:
        log.warning(f"Enrollment FMD error: {e}; storing first capture.")
        return base64.b64encode(fmds[0]).decode()


def identify_from_cache() -> Optional[str]:
    """
    Capture one scan → compare against all cached templates
    using Comparison.Compare() loop (same pattern as working test).
    Returns matched client_name or None.
    """
    if not SCANNER_AVAILABLE or not _cache:
        return None

    fid = _service.request_fid(timeout=7)
    if fid is None:
        return None

    probe_bytes = _fid_to_fmd_bytes(fid)
    if probe_bytes is None:
        return None

    probe_fmd = _bytes_to_fmd(probe_bytes)
    if probe_fmd is None:
        return None

    dp = _dp
    best_name:  Optional[str] = None
    best_score: int           = MATCH_THRESHOLD   # only accept below threshold

    for client_name, stored_bytes in _cache.items():
        try:
            stored_fmd = _bytes_to_fmd(stored_bytes)
            if stored_fmd is None:
                continue

            cmp = dp.Comparison.Compare(probe_fmd, 0, stored_fmd, 0)

            if cmp.ResultCode != dp.Constants.ResultCode.DP_SUCCESS:
                continue

            score = cmp.Score
            if score < best_score:
                best_score = score
                best_name  = client_name

        except Exception as e:
            log.warning(f"Compare error for {client_name}: {e}")

    if best_name:
        log.info(f"Identified: {best_name}  score={best_score}")
    else:
        log.info("No match found.")

    return best_name


def verify(client_name: str) -> bool:
    """1:1 verify a specific client against their stored template."""
    if not SCANNER_AVAILABLE or client_name not in _cache:
        return False

    fid = _service.request_fid(timeout=7)
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
        if cmp.ResultCode != dp.Constants.ResultCode.DP_SUCCESS:
            return False
        return cmp.Score < MATCH_THRESHOLD
    except Exception as e:
        log.error(f"verify error: {e}")
        return False
