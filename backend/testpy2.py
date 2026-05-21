import clr
import sys
import os

# =========================================================
# SDK PATH
# =========================================================

SDK_PATH = r"C:\Path\To\SDK"

sys.path.append(SDK_PATH)

# =========================================================
# LOAD DLLS
# =========================================================

clr.AddReference("System.Windows.Forms")
clr.AddReference("DPUruNet")

import DPUruNet

from System.Windows.Forms import Application, Form

# =========================================================
# TEMPLATE DIRECTORY
# =========================================================

TEMPLATE_DIR = r"C:\Users\johnh\Downloads\attendance_sales_v2\project2\templates"

# =========================================================
# MATCH SETTINGS
# =========================================================

PROBABILITY_ONE = 0x7fffffff
MATCH_THRESHOLD = int(PROBABILITY_ONE / 100000)

print("Match Threshold:", MATCH_THRESHOLD)

# =========================================================
# IDENTIFICATION FORM
# =========================================================

class IdentifyForm(Form):

    def __init__(self):

        Form.__init__(self)

        self.reader = None
        self.templates = []

        # =====================================================
        # LOAD SAVED TEMPLATES
        # =====================================================

        print("\n========================================")
        print("LOADING SAVED TEMPLATES")
        print("========================================")

        self.load_templates()

        if len(self.templates) == 0:
            print("No templates loaded")
            Application.Exit()
            return

        # =====================================================
        # GET READERS
        # =====================================================

        readers = DPUruNet.ReaderCollection.GetReaders()

        print("\nReader count:", readers.Count)

        if readers.Count == 0:
            print("No readers found")
            Application.Exit()
            return

        self.reader = readers[0]

        print("Using reader:")
        print(self.reader.Description.Name)

        # =====================================================
        # OPEN READER
        # =====================================================

        result = self.reader.Open(
            DPUruNet.Constants.CapturePriority.DP_PRIORITY_COOPERATIVE
        )

        print("Open result:", result)

        if result != DPUruNet.Constants.ResultCode.DP_SUCCESS:
            print("Failed to open reader")
            Application.Exit()
            return

        # =====================================================
        # CHECK STATUS
        # =====================================================

        status = self.reader.GetStatus()

        print("Status result:", status)
        print("Reader state:", self.reader.Status.Status)

        # =====================================================
        # REGISTER CALLBACK
        # =====================================================

        self.capture_callback = DPUruNet.Reader.CaptureCallback(
            self.on_captured
        )

        self.reader.On_Captured += self.capture_callback

        # =====================================================
        # START CAPTURE
        # =====================================================

        self.start_capture()

        print("\n========================================")
        print("READY - WAITING FOR FINGER")
        print("========================================")

    # =========================================================
    # LOAD SAVED TEMPLATES
    # =========================================================

    def load_templates(self):

        files = [
            f for f in os.listdir(TEMPLATE_DIR)
            if f.endswith(".fmd")
        ]

        print("FMD files found:", len(files))

        for filename in files:

            try:

                path = os.path.join(TEMPLATE_DIR, filename)

                with open(path, "rb") as f:
                    data = f.read()

                # =================================================
                # IMPORT SAVED FMD
                # =================================================

                result = DPUruNet.Importer.ImportFmd(
                    data,
                    DPUruNet.Constants.Formats.Fmd.ANSI,
                    DPUruNet.Constants.Formats.Fmd.ANSI
                )

                print("Import result:", result.ResultCode)

                if result.ResultCode != DPUruNet.Constants.ResultCode.DP_SUCCESS:
                    print("Failed to import:", filename)
                    continue

                fmd = result.Data

                self.templates.append((filename, fmd))

                print("Loaded:", filename)

            except Exception as ex:

                print("Error loading:", filename)
                print(ex)

        print("Total templates loaded:", len(self.templates))

    # =========================================================
    # START CAPTURE
    # =========================================================

    def start_capture(self):

        try:

            resolution = self.reader.Capabilities.Resolutions[0]

            print("\nStarting capture...")
            print("Using resolution:", resolution)

            result = self.reader.CaptureAsync(
                DPUruNet.Constants.Formats.Fid.ANSI,
                DPUruNet.Constants.CaptureProcessing.DP_IMG_PROC_DEFAULT,
                resolution
            )

            print("CaptureAsync result:", result)

        except Exception as ex:

            print("Capture start failed")
            print(ex)

    # =========================================================
    # CAPTURE CALLBACK
    # =========================================================

    def on_captured(self, capture_result):

        try:

            print("\n========================================")
            print("FINGER DETECTED")
            print("========================================")

            print("Capture Result:", capture_result.ResultCode)

            if capture_result.ResultCode != DPUruNet.Constants.ResultCode.DP_SUCCESS:
                print("Capture failed")
                self.start_capture()
                return

            if capture_result.Data is None:
                print("No capture data")
                self.start_capture()
                return

            # =================================================
            # CREATE FMD FROM LIVE FINGER
            # =================================================

            result = DPUruNet.FeatureExtraction.CreateFmdFromFid(
                capture_result.Data,
                DPUruNet.Constants.Formats.Fmd.ANSI
            )

            print("FMD Creation Result:", result.ResultCode)

            if result.ResultCode != DPUruNet.Constants.ResultCode.DP_SUCCESS:
                print("FMD creation failed")
                self.start_capture()
                return

            probe_fmd = result.Data

            # =================================================
            # COMPARE AGAINST SAVED TEMPLATES
            # =================================================

            print("\n========================================")
            print("COMPARING")
            print("========================================")

            matched = False

            for filename, saved_fmd in self.templates:

                compare_result = DPUruNet.Comparison.Compare(
                    probe_fmd,
                    0,
                    saved_fmd,
                    0
                )

                if compare_result.ResultCode != DPUruNet.Constants.ResultCode.DP_SUCCESS:
                    print("Compare failed:", filename)
                    continue

                score = compare_result.Score

                print(f"{filename} -> score: {score}")

                if score < MATCH_THRESHOLD:

                    print("\n========================================")
                    print("MATCH FOUND")
                    print("Template:", filename)
                    print("Score:", score)
                    print("========================================")

                    matched = True
                    break

            if not matched:

                print("\n========================================")
                print("NO MATCH FOUND")
                print("========================================")

            # =================================================
            # CONTINUE WAITING
            # =================================================

            print("\nWaiting for next finger...")

            self.start_capture()

        except Exception as ex:

            print("\nERROR:")
            print(ex)

            self.start_capture()

    # =========================================================
    # CLEANUP
    # =========================================================

    def cleanup(self):

        try:
            if self.reader:
                self.reader.CancelCapture()
        except:
            pass

        try:
            if self.reader:
                self.reader.Dispose()
        except:
            pass

        print("\nReader closed")


# =============================================================
# START APP
# =============================================================

form = IdentifyForm()

try:

    Application.Run(form)

finally:

    form.cleanup()