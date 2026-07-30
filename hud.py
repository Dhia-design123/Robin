"""
Robin HUD — circular overlay that pulses while Robin speaks.
"""

import tkinter as tk
import threading
import time
import math

"""
Robin HUD — circular overlay that pulses while Robin speaks.
"""

import tkinter as tk
import threading
import time
import math

class RobinHUD:
    def __init__(self):
        self.speaking = False
        self.muted = False
        self.pulse_phase = 0

        self.root = tk.Tk()
        self.root.title("Robin")
        self.root.overrideredirect(True)       # no title bar/border
        self.root.attributes("-topmost", True)  # always on top
        self.root.attributes("-transparentcolor", "black")
        self.root.configure(bg="black")

        size = 260
        self.canvas = tk.Canvas(self.root, width=size, height=size,
                                 bg="black", highlightthickness=0)
        self.canvas.pack()

        # Position window: bottom-right corner of screen
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        self.root.geometry(f"{size}x{size}+{screen_w - size - 30}+{screen_h - size - 100}")

        self.center = size // 2
        self.base_radius = 70
        self.text_id = None

        self._draw()
        self._animate()

    def _draw(self):
        self.canvas.delete("all")
        c = self.center

        # Pulse amount: bigger swing while speaking, gentle idle breathing otherwise
        if self.speaking:
            pulse = math.sin(self.pulse_phase) * 22
        else:
            pulse = math.sin(self.pulse_phase * 0.3) * 6

        r = self.base_radius + pulse

        # Outer rings (static, decorative)
        for offset in (30, 18):
            self.canvas.create_oval(
                c - r - offset, c - r - offset, c + r + offset, c + r + offset,
                outline="#0aa8c9", width=1
            )

        # Main pulsing circle
        color = "#1de3ff" if self.speaking else "#0a7f99"
        self.canvas.create_oval(
            c - r, c - r, c + r, c + r,
            outline=color, width=3
        )

        # Inner filled circle
        inner_r = r * 0.55
        self.canvas.create_oval(
            c - inner_r, c - inner_r, c + inner_r, c + inner_r,
            fill="#052733", outline=color, width=1
        )

        self.canvas.create_text(
            c, c, text="ROBIN", fill=color,
            font=("Segoe UI", 12, "bold")
        )

    def _animate(self):
        self.pulse_phase += 0.35 if self.speaking else 0.08
        self._draw()
        self.root.after(40, self._animate)  # ~25 fps

    def set_speaking(self, is_speaking: bool):
        self.speaking = is_speaking

    def set_muted(self, is_muted: bool):
        self.muted = is_muted

    def run(self):
        self.root.mainloop()


# Shared instance other modules can import and control
hud_instance = None

def start_hud_in_thread():
    """Launches the HUD in a background thread so it doesn't block your main agent loop."""
    global hud_instance

    def _run():
        global hud_instance
        hud_instance = RobinHUD()
        hud_instance.run()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    time.sleep(0.5)  # give tkinter a moment to initialize
    return hud_instance


