import subprocess
import sys
from pathlib import Path

# Launch gui_test.py using pythonw to hide the console window
script_path = Path(__file__).parent / "gui_test.py"
subprocess.Popen(["pythonw", str(script_path)], creationflags=subprocess.CREATE_NO_WINDOW)
