import clr
import time
import threading

clr.AddReference("System.Windows.Forms")
clr.AddReference("DPUruNet")

import DPUruNet as dp

from System.Windows.Forms import (
    Application,
    Form,
    Label,
    FormWindowState,
    DockStyle,
)

# =========================================================
# GLOBAL STATE
# =========================================================

reader = None
callback = None

scan_count = 0
arm_count = 0

# =========================================================
# ARM FUNCTION
# =========================================================

def arm():

    global reader, arm_count

    arm_count += 1

    print(f"\n[ARM ATTEMPT #{arm_count}] CaptureAsync...")

    try:

        resolution = reader.Capabilities.Resolutions[0]

        result = reader.CaptureAsync(
            dp.Constants.Formats.Fid.ANSI,
            dp.Constants.CaptureProcessing.DP_IMG_PROC_DEFAULT,
            resolution,
        )

        print(f"[ARM #{arm_count}] result: {result}")

        return result

    except Exception as e:

        print("[ARM ERROR]:", e)
        return None

# =========================================================
# FIXED 3-SECOND RE-ARM
# =========================================================

def safe_rearm():

    def worker():

        import time

        delay = 2.0

        print("\n[RE-ARM] Fixed 3-second cooldown started")
        time.sleep(delay)

        print("[RE-ARM] Attempting CaptureAsync after 3s...")

        result = arm()

        if result == dp.Constants.ResultCode.DP_SUCCESS:
            print("[RE-ARM SUCCESS] Scanner ready")

        elif result == dp.Constants.ResultCode.DP_DEVICE_BUSY:
            print("[RE-ARM BUSY] Still busy after 3 seconds")

        else:
            print("[RE-ARM STATE]", result)

    threading.Thread(target=worker, daemon=True).start()

# =========================================================
# CALLBACK
# =========================================================

def on_captured(result):

    global scan_count

    scan_count += 1

    print("\n====================================")
    print(f"[SCAN DETECTED #{scan_count}]")
    print("====================================")

    try:

        print("[RESULT]:", result.ResultCode)

        if result.ResultCode == dp.Constants.ResultCode.DP_SUCCESS:

            if result.Data is not None:
                print("[SCAN] Fingerprint captured ✔")
            else:
                print("[SCAN] Empty data")

        else:
            print("[SCAN] Capture failed")

    except Exception as e:
        print("[SCAN ERROR]:", e)

    finally:

        print(f"[SCAN #{scan_count}] Scheduling 3-second re-arm...")
        safe_rearm()

# =========================================================
# MAIN
# =========================================================

print("========================================")
print("U.ARE.U 4500 FIXED 3-SECOND TEST")
print("========================================")

readers = dp.ReaderCollection.GetReaders()

print("[READY] Reader count:", readers.Count)

if readers.Count == 0:
    print("[ERROR] No fingerprint reader found")
    raise SystemExit

reader = readers[0]

print("[READY] Device:", reader.Description.Name)

# =========================================================
# OPEN DEVICE
# =========================================================

print("\n[INIT] Opening EXCLUSIVE...")

result = reader.Open(
    dp.Constants.CapturePriority.DP_PRIORITY_EXCLUSIVE
)

print("[INIT] Open result:", result)

if result != dp.Constants.ResultCode.DP_SUCCESS:
    print("[FATAL] Cannot open reader")
    raise SystemExit

# =========================================================
# CALLBACK REGISTER
# =========================================================

callback = dp.Reader.CaptureCallback(on_captured)
reader.On_Captured += callback

print("[READY] Callback registered")

# =========================================================
# HIDDEN WINDOW (REQUIRED MESSAGE LOOP)
# =========================================================

form = Form()
form.Text = "4500 Test - 3s Delay"

form.ShowInTaskbar = False
form.WindowState = FormWindowState.Minimized
form.Opacity = 0

label = Label()
label.Text = "4500 scanner running (3s re-arm)"
label.Dock = DockStyle.Fill

form.Controls.Add(label)

# =========================================================
# INITIAL ARM
# =========================================================

print("\n[READY] Initial arm...")

arm()

print("\n========================================")
print("[SYSTEM READY] WAITING FOR FINGERPRINTS")
print("========================================")

Application.Run(form)