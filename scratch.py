import subprocess
output = subprocess.check_output(['git', 'log', '-p', '-1'], universal_newlines=True)
print(output)
