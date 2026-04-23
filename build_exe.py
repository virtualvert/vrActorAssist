#!/usr/bin/env python3
# Build script for creating standalone executable (Windows or Linux)
# Run with: python build_exe.py [actor|director|all]
#
# Requirements (one-time setup):
#   pip install pyinstaller
#
# Usage:
#   python build_exe.py          # Build actor client (default)
#   python build_exe.py actor    # Build actor client
#   python build_exe.py director # Build director client
#   python build_exe.py all      # Build both

import subprocess
import sys
import os
import platform
import shutil

# Detect OS
IS_WINDOWS = platform.system() == 'Windows'
PATH_SEP = ';' if IS_WINDOWS else ':'

# Determine build target
target = sys.argv[1].lower() if len(sys.argv) > 1 else 'actor'

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def clean_build():
    """Clean build artifacts."""
    for folder in ['build', 'dist']:
        path = os.path.join(SCRIPT_DIR, folder)
        if os.path.exists(path):
            shutil.rmtree(path)
    # Clean spec files from previous builds
    for spec in ['vrActorClient.spec', 'vrDirectorClient.spec']:
        path = os.path.join(SCRIPT_DIR, spec)
        if os.path.exists(path):
            os.remove(path)

def run_pyinstaller(script_name, exe_name, extra_data=None):
    """Run PyInstaller as a subprocess to avoid state contamination between builds."""
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        os.path.join(SCRIPT_DIR, script_name),
        '--name=' + exe_name,
        '--onefile',
        '--windowed',
        '--add-data', f'shared.py{PATH_SEP}.',
        '--hiddenimport=websocket',
        '--hiddenimport=tkinter',
        '--clean',
        '--distpath', os.path.join(SCRIPT_DIR, 'dist'),
        '--workpath', os.path.join(SCRIPT_DIR, 'build'),
        '--specpath', SCRIPT_DIR,
    ]
    
    if extra_data:
        for data in extra_data:
            cmd.extend(['--add-data', f'{data}{PATH_SEP}.'])
    
    print(f"\nRunning: {' '.join(cmd[:8])}...")
    result = subprocess.run(cmd, cwd=SCRIPT_DIR)
    
    if result.returncode != 0:
        print(f"\n✗ Build failed for {exe_name} (exit code {result.returncode})")
        sys.exit(result.returncode)
    
    return result.returncode == 0

def build_actor():
    """Build actor client executable."""
    print("="*50)
    print("Building actor client...")
    print("="*50)
    
    success = run_pyinstaller(
        'actor_client_ws.py',
        'vrActorClient',
        extra_data=['soundpad.py']
    )
    
    exe_ext = '.exe' if IS_WINDOWS else ''
    exe_path = os.path.join(SCRIPT_DIR, 'dist', f'vrActorClient{exe_ext}')
    
    print("\n" + "="*50)
    print("Actor client build complete!")
    print(f"  Executable: {exe_path}")
    print("="*50)
    
    if IS_WINDOWS:
        print("\nTo distribute: copy vrActorClient.exe — no Python needed!")
    else:
        print("\nTo distribute: copy vrActorClient, chmod +x, run — no Python needed!")

def build_director():
    """Build director client executable."""
    print("="*50)
    print("Building director client...")
    print("="*50)
    
    success = run_pyinstaller(
        'director_client_ws.py',
        'vrDirectorClient'
    )
    
    exe_ext = '.exe' if IS_WINDOWS else ''
    exe_path = os.path.join(SCRIPT_DIR, 'dist', f'vrDirectorClient{exe_ext}')
    
    print("\n" + "="*50)
    print("Director client build complete!")
    print(f"  Executable: {exe_path}")
    print("="*50)
    
    if IS_WINDOWS:
        print("\nTo distribute: copy vrDirectorClient.exe — no Python needed!")
    else:
        print("\nTo distribute: copy vrDirectorClient, chmod +x, run — no Python needed!")

if __name__ == '__main__':
    # Clean build artifacts at the start
    clean_build()
    
    if target == 'actor':
        build_actor()
    elif target == 'director':
        build_director()
    elif target == 'all':
        build_actor()
        build_director()
    else:
        print(f"Unknown target: {target}")
        print("Usage: python build_exe.py [actor|director|all]")
        sys.exit(1)