import subprocess
from pathlib import Path


def register(mcp):
    @mcp.tool()
    def open_application(app_name: str) -> str:
        """Open an application by name (e.g. 'notepad', 'chrome', 'calculator', 'explorer')."""
        try:
            subprocess.Popen(app_name, shell=True)
            return f"Opening {app_name}."
        except Exception as e:
            return f"Couldn't open {app_name}: {e}"

    @mcp.tool()
    def list_directory(path: str = "~") -> str:
        """List files and folders in a given directory. Defaults to the user's home folder."""
        p = Path(path).expanduser()
        if not p.exists():
            return f"Path {p} doesn't exist."
        try:
            items = [f.name for f in p.iterdir()][:50]
            return ", ".join(items) if items else "That folder is empty."
        except Exception as e:
            return f"Couldn't list {p}: {e}"

    @mcp.tool()
    def run_shell_command(command: str) -> str:
        """Run a safe, whitelisted shell command and return its output.
        Allowed commands: dir, echo, systeminfo, tasklist, ipconfig."""
        ALLOWED = ["dir", "echo", "systeminfo", "tasklist", "ipconfig"]
        first_word = command.strip().split(" ")[0].lower()
        if first_word not in ALLOWED:
            return f"Command '{first_word}' isn't in the allowed list for safety."
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=10
            )
            output = result.stdout or result.stderr
            return output[:1000] if output else "(no output)"
        except Exception as e:
            return f"Command failed: {e}"

    @mcp.tool()
    def workspace_launch() -> str:
        """Opens the user's typical daily workspace: apps and folders they use every day."""
        opened = []
        try:
            # Adjust these to match what you actually want opened every morning
            subprocess.Popen("chrome", shell=True)
            opened.append("Chrome")

            subprocess.Popen("code", shell=True)  # VS Code
            opened.append("VS Code")

            subprocess.Popen("explorer C:\\Users\\hello\\Downloads", shell=True)
            opened.append("Downloads folder")

            # Add more as needed, e.g.:
            # subprocess.Popen("outlook", shell=True)
            # opened.append("Outlook")

            return f"Opened: {', '.join(opened)}."
        except Exception as e:
            return f"Ran into an issue launching the workspace: {e}"