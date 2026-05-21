"""
Fingerprint device enumeration + open probe.
Tries multiple open strategies to find what works.
"""
import ctypes
import sys

pdd = ctypes.WinDLL("dpfpdd.dll")

# Configure signatures
pdd.dpfpdd_open.restype  = ctypes.c_int
pdd.dpfpdd_open.argtypes = [ctypes.c_char_p,
                             ctypes.POINTER(ctypes.c_void_p)]

pdd.dpfpdd_query_devices.restype  = ctypes.c_int
pdd.dpfpdd_query_devices.argtypes = [ctypes.POINTER(ctypes.c_uint),
                                      ctypes.c_void_p]

pdd.dpfpdd_close.restype  = ctypes.c_int
pdd.dpfpdd_close.argtypes = [ctypes.c_void_p]

print("[A] Enumerating devices...")
count = ctypes.c_uint(0)

# First call: get count
ret = pdd.dpfpdd_query_devices(ctypes.byref(count), None)
print(f"    query_devices (count pass): ret={ret:#010x}  count={count.value}")

if count.value == 0:
    print("    No devices enumerated. Trying blind open strategies...")
else:
    # Second call: allocate large buffer and get device info
    # DPFPDD_DEV_INFO struct: first UINT is size, then char[1024] name
    # Total struct ~2048 bytes to be safe
    STRUCT_SIZE = 2048
    buf = (ctypes.c_ubyte * (count.value * STRUCT_SIZE))()
    # Write size field into each struct slot
    for i in range(count.value):
        ctypes.c_uint.from_buffer(buf, i * STRUCT_SIZE).value = STRUCT_SIZE

    ret2 = pdd.dpfpdd_query_devices(ctypes.byref(count), buf)
    print(f"    query_devices (info pass): ret={ret2:#010x}")

    # Extract device name — starts at offset 4 (after size uint)
    for i in range(count.value):
        offset = i * STRUCT_SIZE + 4
        name_bytes = bytes(buf[offset:offset + 512])
        name = name_bytes.split(b'\x00')[0].decode('utf-8', errors='replace')
        print(f"    Device {i}: '{name}'")

        print(f"\n[B] Trying dpfpdd_open with '{name}'...")
        handle = ctypes.c_void_p(None)
        name_b = name.encode('utf-8') + b'\x00'
        ret3 = pdd.dpfpdd_open(name_b, ctypes.byref(handle))
        print(f"    ret={ret3:#010x}  handle={handle}")
        if ret3 == 0:
            print("    SUCCESS with enumerated name!")
            pdd.dpfpdd_close(handle)

print("\n[C] Trying dpfpdd_open with NULL...")
handle = ctypes.c_void_p(None)
ret = pdd.dpfpdd_open(None, ctypes.byref(handle))
print(f"    ret={ret:#010x}  handle={handle}")
if ret == 0:
    print("    SUCCESS with NULL!")
    pdd.dpfpdd_close(handle)

print("\n[D] Trying dpfpdd_open with empty string b''...")
handle = ctypes.c_void_p(None)
ret = pdd.dpfpdd_open(b"", ctypes.byref(handle))
print(f"    ret={ret:#010x}  handle={handle}")
if ret == 0:
    print("    SUCCESS with empty string!")
    pdd.dpfpdd_close(handle)

print("\n[E] Known DigitalPersona device path patterns...")
paths = [
    b"\\\\?\\usb#vid_05ba",
    b"DigitalPersona U.are.U 4500",
    b"DigitalPersona U.are.U 4000",
    b"DigitalPersona U.are.U 5100",
    b"U.are.U 4500",
]
for path in paths:
    handle = ctypes.c_void_p(None)
    ret = pdd.dpfpdd_open(path, ctypes.byref(handle))
    if ret == 0:
        print(f"    SUCCESS with path: {path}")
        pdd.dpfpdd_close(handle)
    else:
        print(f"    {path!r}: {ret:#010x}")

print("\nDone. Share full output above.")
