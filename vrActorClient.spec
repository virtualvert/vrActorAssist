# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for vrActorClient
# Usage: pyinstaller vrActorClient.spec

import os

block_cipher = None

a = Analysis(
    ['actor_client_ws.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('shared.py', '.'),
        ('soundpad.py', '.'),
    ],
    hiddenimports=[
        'websocket',
        'tkinter',
        'tkinter.messagebox',
        'tkinter.scrolledtext',
        'tkinter.ttk',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='vrActorClient',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window (GUI app)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)