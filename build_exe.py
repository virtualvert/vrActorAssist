# Build script for creating standalone executable (Windows or Linux)
# Run with: python build_exe.py [actor|director]
#
# Requirements (one-time setup):
#   pip install pyinstaller
#
# Usage:
#   python build_exe.py          # Build actor client (default)
#   python build_exe.py actor    # Build actor client
#   python build_exe.py director # Build director client
#   python build_exe.py all      # Build both

import PyInstaller.__main__
import os
import shutil
import sys
import platform

# Detect OS
IS_WINDOWS = platform.system() == 'Windows'
PATH_SEP = ';' if IS_WINDOWS else ':'  # PyInstaller uses ; on Windows, : on Unix

# Determine build target
target = sys.argv[1].lower() if len(sys.argv) > 1 else 'actor'

def clean_build():
    """Clean build artifacts."""
    for folder in ['build', 'dist']:
        if os.path.exists(folder):
            shutil.rmtree(folder)

def build_actor():
    """Build actor client executable."""
    print("Building actor client...")
    
    # Build executable
    PyInstaller.__main__.run([
        'actor_client_ws.py',
        '--name=vrActorClient',
        '--onefile',           # Single file
        '--windowed',          # No console window (GUI app)
        f'--add-data=shared.py{PATH_SEP}.',    # Include shared module
        f'--add-data=soundpad.py{PATH_SEP}.',  # Include soundpad module
        '--hiddenimport=websocket',
        '--hiddenimport=tkinter',
        '--clean',
    ])
    
    # Report result
    exe_name = 'vrActorClient.exe' if IS_WINDOWS else 'vrActorClient'
    exe_path = os.path.join('dist', exe_name)
    
    print("\n" + "="*50)
    print("Actor client build complete!")
    print(f"Executable: {exe_path}")
    print("="*50)
    print("\nTo distribute:")
    print(f"1. Copy {exe_path}")
    print(f"2. Actors just run the {'exe' if IS_WINDOWS else 'binary'} - no Python needed!")
    print("\nNote: First run will prompt for server URL and actor name.")

def build_director():
    """Build director client executable."""
    print("Building director client...")
    
    # Build executable
    PyInstaller.__main__.run([
        'director_client_ws.py',
        '--name=vrDirectorClient',
        '--onefile',           # Single file
        '--windowed',          # No console window (GUI app)
        f'--add-data=shared.py{PATH_SEP}.',    # Include shared module
        '--hiddenimport=websocket',
        '--hiddenimport=tkinter',
        '--clean',
    ])
    
    # Report result
    exe_name = 'vrDirectorClient.exe' if IS_WINDOWS else 'vrDirectorClient'
    exe_path = os.path.join('dist', exe_name)
    
    print("\n" + "="*50)
    print("Director client build complete!")
    print(f"Executable: {exe_path}")
    print("="*50)
    print("\nTo distribute:")
    print(f"1. Copy {exe_path}")
    print(f"2. Directors just run the {'exe' if IS_WINDOWS else 'binary'} - no Python needed!")
    print("\nNote: First run will prompt for server URL and director secret.")

if __name__ == '__main__':
    # Clean once at the start
    clean_build()
    
    if target == 'actor':
        build_actor()
    elif target == 'director':
        build_director()
    elif target == 'all':
        build_actor()
        print("\n")
        build_director()
    else:
        print(f"Unknown target: {target}")
        print("Usage: python build_exe.py [actor|director|all]")
        sys.exit(1)