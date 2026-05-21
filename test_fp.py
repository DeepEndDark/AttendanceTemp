"""
Fingerprint test — U.are.U SDK v3 (Crossmatch/HID Global)
Fixes:
  1. dpfpdd_init() called before everything else (required by v3 SDK)
  2. dpfpdd_capture uses struct-based DPFPDD_CAPTURE_PARAM / DPFPDD_CAPTURE_RESULT
"""
import ctypes
import sys

print("=" * 56)
print("U.are.U SDK v3 — Fingerprint Test")
print("=" * 56)

# ── Load DLLs ─────────────────────────────────────────────────
print("\n[1] Loading DLLs...")
try:
    pdd = ctypes.WinDLL("dpfpdd.dll")
    print("    dpfpdd.dll  OK")
except OSError as e:
    print(f"    dpfpdd.dll  FAILED: {e}")
    sys.exit(1)

try:
    fj = ctypes.WinDLL("dpfj.dll")
    print("    dpfj.dll    OK")
except OSError as e:
    print(f"    dpfj.dll    FAILED: {e}")
    sys.exit(1)

# ── Initialise library (REQUIRED first call in SDK v3) ────────
print("\n[2] Calling dpfpdd_init()...")
pdd.dpfpdd_init.restype  = ctypes.c_int
pdd.dpfpdd_init.argtypes = []
ret = pdd.dpfpdd_init()
if ret != 0:
    print(f"    dpfpdd_init failed: {ret:#010x}")
    sys.exit(1)
print("    dpfpdd_init OK")

# ── Query devices ─────────────────────────────────────────────
print("\n[3] Querying devices...")
pdd.dpfpdd_query_devices.restype  = ctypes.c_int
pdd.dpfpdd_query_devices.argtypes = [
    ctypes.POINTER(ctypes.c_uint),
    ctypes.c_void_p
]
count = ctypes.c_uint(0)
ret = pdd.dpfpdd_query_devices(ctypes.byref(count), None)
print(f"    ret={ret:#010x}  device_count={count.value}")

# ── Open device ───────────────────────────────────────────────
print("\n[4] Opening device via dpfpdd_open(b'', ...)...")
pdd.dpfpdd_open.restype  = ctypes.c_int
pdd.dpfpdd_open.argtypes = [ctypes.c_char_p,
                             ctypes.POINTER(ctypes.c_void_p)]
pdd.dpfpdd_close.restype  = ctypes.c_int
pdd.dpfpdd_close.argtypes = [ctypes.c_void_p]

handle = ctypes.c_void_p(None)
ret = pdd.dpfpdd_open(b"", ctypes.byref(handle))
if ret != 0:
    print(f"    dpfpdd_open failed: {ret:#010x}")
    pdd.dpfpdd_exit()
    sys.exit(1)
print(f"    Opened OK  handle={handle}")

# ── Capture — try STRUCT-based signature (SDK v3 style) ───────
print("\n[5] Capture attempt — struct-based parameters...")
print("    Place finger on scanner (5s timeout)...")

# DPFPDD_CAPTURE_PARAM struct (image format, image processing, res, timeout)
class DPFPDD_CAPTURE_PARAM(ctypes.Structure):
    _fields_ = [
        ("size",       ctypes.c_uint),   # sizeof this struct
        ("image_fmt",  ctypes.c_int),    # 0 = raw grayscale
        ("image_proc", ctypes.c_uint),   # 0 = default
        ("image_res",  ctypes.c_uint),   # 500 dpi
    ]

# DPFPDD_IMAGE_INFO
class DPFPDD_IMAGE_INFO(ctypes.Structure):
    _fields_ = [
        ("size",   ctypes.c_uint),
        ("width",  ctypes.c_uint),
        ("height", ctypes.c_uint),
        ("res",    ctypes.c_uint),
        ("bpp",    ctypes.c_uint),
    ]

# DPFPDD_CAPTURE_RESULT struct
class DPFPDD_CAPTURE_RESULT(ctypes.Structure):
    _fields_ = [
        ("size",       ctypes.c_uint),
        ("success",    ctypes.c_int),    # 1 = success
        ("quality",    ctypes.c_int),    # image quality code
        ("score",      ctypes.c_uint),   # quality score
        ("info",       DPFPDD_IMAGE_INFO),
    ]

try:
    pdd.dpfpdd_capture.restype  = ctypes.c_int
    pdd.dpfpdd_capture.argtypes = [
        ctypes.c_void_p,                              # handle
        ctypes.POINTER(DPFPDD_CAPTURE_PARAM),         # param
        ctypes.c_uint,                                # timeout ms
        ctypes.POINTER(DPFPDD_CAPTURE_RESULT),        # result
        ctypes.POINTER(ctypes.c_uint),                # image size in/out
        ctypes.POINTER(ctypes.c_ubyte),               # image data
    ]

    param = DPFPDD_CAPTURE_PARAM(
        size=ctypes.sizeof(DPFPDD_CAPTURE_PARAM),
        image_fmt=0,   # raw
        image_proc=0,
        image_res=500,
    )
    result = DPFPDD_CAPTURE_RESULT(
        size=ctypes.sizeof(DPFPDD_CAPTURE_RESULT))

    BUF = 600_000
    buf      = (ctypes.c_ubyte * BUF)()
    buf_size = ctypes.c_uint(BUF)

    ret = pdd.dpfpdd_capture(
        handle,
        ctypes.byref(param),
        5000,
        ctypes.byref(result),
        ctypes.byref(buf_size),
        buf,
    )

    if ret == 0 and result.success:
        w = result.info.width
        h = result.info.height
        r = result.info.res
        print(f"    Capture OK  {buf_size.value}B  {w}x{h}px  {r}dpi")
        STRUCT_OK = True
    else:
        print(f"    Struct capture ret={ret:#010x}  "
              f"success={result.success}  quality={result.quality}")
        STRUCT_OK = False

except Exception as ex:
    print(f"    Struct capture exception: {ex}")
    STRUCT_OK = False

# ── Fallback: flat-parameter signature (SDK v1 style) ─────────
if not STRUCT_OK:
    print("\n[5b] Fallback — flat parameters (v1 style)...")
    try:
        pdd.dpfpdd_capture.restype  = ctypes.c_int
        pdd.dpfpdd_capture.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_int),
        ]
        BUF  = 600_000
        buf      = (ctypes.c_ubyte * BUF)()
        buf_size = ctypes.c_uint(BUF)
        w = ctypes.c_uint(0)
        h = ctypes.c_uint(0)
        d = ctypes.c_uint(0)
        cr = ctypes.c_int(0)

        ret = pdd.dpfpdd_capture(
            handle, 0, 0, 500, 5000,
            buf, ctypes.byref(buf_size),
            ctypes.byref(w), ctypes.byref(h),
            ctypes.byref(d), ctypes.byref(cr),
        )
        if ret == 0:
            print(f"    Flat capture OK  {buf_size.value}B  "
                  f"{w.value}x{h.value}px  {d.value}dpi")
            STRUCT_OK = True
        else:
            print(f"    Flat capture ret={ret:#010x}  "
                  f"cap_result={cr.value:#010x}")
    except Exception as ex:
        print(f"    Flat capture exception: {ex}")

# ── Cleanup ───────────────────────────────────────────────────
pdd.dpfpdd_close(handle)

pdd.dpfpdd_exit.restype  = ctypes.c_int
pdd.dpfpdd_exit.argtypes = []
pdd.dpfpdd_exit()

print("\n" + ("=" * 56))
if STRUCT_OK:
    print("Capture SUCCEEDED — scanner is ready.")
else:
    print("Capture FAILED — share full output above.")
print("=" * 56)
