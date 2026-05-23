"""
Standalone test for ClientDisplayWindow.
Cycles through all banner types so you can verify colors and layout.
Run from: frontend/
"""
import queue
import tkinter as tk
from fapp.views.client_display import ClientDisplayWindow

eq = queue.Queue()

root = tk.Tk()
root.withdraw()   # hide root, only show client display

win = ClientDisplayWindow(root, eq)

events = [
    {"type": "scanning",    "title": "Reading...",      "subtitle": "Please hold still"},
    {"type": "time_in",     "title": "John Doe",        "subtitle": "Timed in at 08:42:01"},
    {"type": "time_out",    "title": "John Doe",        "subtitle": "Timed out at 17:05:33"},
    {"type": "expiry_warn", "title": "Jane Smith",      "subtitle": "Timed in at 09:00:00  |  2 day(s) remaining"},
    {"type": "expired",     "title": "Bob Torres",      "subtitle": "Subscription expired — please renew"},
    {"type": "no_match",    "title": "No Match Found",  "subtitle": "Please try again or see staff"},
    {"type": "clear"},
]

idx = [0]

def send_next():
    if idx[0] < len(events):
        e = events[idx[0]]
        print(f"Sending event: {e}")
        eq.put(e)
        idx[0] += 1
        root.after(3000, send_next)
    else:
        print("All events sent. Close the window to exit.")

root.after(1000, send_next)
root.mainloop()
