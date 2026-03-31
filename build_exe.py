# Build script for creating standalone Windows executable
# Run this on Windows with Python installed
#
# Usage: python build_exe.py
#
# Requirements (one-time setup):
#   pip install pyinstaller

import PyInstaller.__main__
import os
import shutil

# Clean previous builds
for folder in ['build', 'dist']:
    if os.path.exists(folder):
        shutil.rmtree(folder)

# Build actor client
PyInstaller.__main__.run([
    'actor_client_ws.py',
    '--name=vrActorClient',
    '--onefile',           # Single .exe file
    '--windowed',          # No console window (GUI app)
    '--add-data=shared.py;.',  # Include shared module
    '--add-data=soundpad.py;.',  # Include soundpad module
    '--hiddenimport=websocket',
    '--hiddenimport=tkinter',
    '--clean',
])

print("\n" + "="*50)
print("Build complete!")
print("Executable: dist/vrActorClient.exe")
print("="*50)
print("\nTo distribute:")
print("1. Copy dist/vrActorClient.exe")
print("2. Actors just run the .exe - no Python needed!")
print("\nNote: First run will prompt for server URL and actor name.")