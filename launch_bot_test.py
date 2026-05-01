import subprocess
import sys
import time

# Start bot with unbuffered output
bot_proc = subprocess.Popen(
    [sys.executable, "-u", "main.py"],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    bufsize=1,
    universal_newlines=True
)

# Wait and read output
time.sleep(5)
output = []
while bot_proc.poll() is None:
    line = bot_proc.stdout.readline()
    if line:
        output.append(line.strip())
    else:
        break

print("\n".join(output) if output else "No output received")
print(f"Process running: {bot_proc.poll() is None}")
print(f"Return code: {bot_proc.returncode}")
