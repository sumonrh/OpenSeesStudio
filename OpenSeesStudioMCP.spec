# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build definition for the OpenSees Studio MCP server."""

block_cipher = None

hidden = [
    "mcp",
    "mcp.server.mcpserver",
    "openseespy",
    "openseespywin",
    "openseespywin.opensees",
]

excludes = [
    "PySide6", "shiboken6",
    "tkinter", "unittest", "pydoc", "doctest", "pytest",
    "matplotlib", "scipy", "pandas", "PIL", "setuptools", "pip",
]

a = Analysis(
    ["mcp_launcher.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OpenSeesStudioMCP",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/opensees_studio.ico",
    version="assets/version_info_mcp.txt",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="OpenSeesStudioMCP",
)
