import subprocess
import pystray
from PIL import Image, ImageDraw

processes = {}

def make_icon():
    img = Image.new('RGB', (64, 64), color=(30, 30, 30))
    d = ImageDraw.Draw(img)
    d.ellipse((16, 16, 48, 48), fill=(0, 200, 255))
    return img

def start_robin(icon, item):
    if "server" not in processes:
        processes["server"] = subprocess.Popen(
            ["uv", "run", "friday"], shell=True
        )
    if "voice" not in processes:
        processes["voice"] = subprocess.Popen(
            ["uv", "run", "robin_voice"], shell=True
        )
    icon.notify("Robin started")

def stop_robin(icon, item):
    for name, proc in list(processes.items()):
        proc.terminate()
    processes.clear()
    icon.notify("Robin stopped")

def quit_app(icon, item):
    stop_robin(icon, item)
    icon.stop()

icon = pystray.Icon(
    "Robin",
    make_icon(),
    "Robin Assistant",
    menu=pystray.Menu(
        pystray.MenuItem("Start", start_robin),
        pystray.MenuItem("Stop", stop_robin),
        pystray.MenuItem("Quit", quit_app),
    ),
)

icon.run()