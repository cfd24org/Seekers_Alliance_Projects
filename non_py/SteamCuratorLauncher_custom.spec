# -*- mode: python ; coding: utf-8 -*-
"""
Custom PyInstaller spec tuned for SteamCuratorLauncher.
- includes common hidden-imports used by Playwright and dynamic imports
- excludes obvious Windows-only modules to reduce irrelevant warnings
- does NOT bundle Playwright browser cache by default; add it at build time
  via --add-data or by editing the spec's `datas` list if you intentionally
  want to include browsers (not recommended unless you handle codesign).

To use this spec from the build script:
  pyinstaller --noconfirm --clean SteamCuratorLauncher_custom.spec

"""

from PyInstaller.utils.hooks import collect_submodules

# Common dynamic modules and Playwright internals
hiddenimports = [
    'playwright._impl._api',
    'playwright.sync_api',
    'playwright._impl._connection',
    'packaging.version',
    'websockets',
    'importlib_metadata',
    'pkg_resources',
]
# also collect submodules of playwright to be conservative
hiddenimports += collect_submodules('playwright')

# Analysis
a = Analysis(
    ['run_app.py'],
    pathex=['.'],
    binaries=[],
    datas=[],  # add data entries here only if you intend to bundle the Playwright cache
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=['winreg', 'nt', '_winapi', 'msvcrt'],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    name='SteamCuratorLauncher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='SteamCuratorLauncher',
)
