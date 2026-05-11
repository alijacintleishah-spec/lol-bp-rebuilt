"""
PyInstaller build script for LoL BP Assistant (Rebuilt).
Usage: python build_exe.py
Output: dist/LoL_BP_Assistant.exe
"""

import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))

import PyInstaller.__main__

PyInstaller.__main__.run([
    'desktop_app.py',
    '--name=LoL_BP_Assistant',
    '--onefile',
    '--windowed',
    '--noconsole',
    '--add-data=data;data',
    '--hidden-import=champion_data',
    '--hidden-import=engine',
    '--hidden-import=recommender',
    '--hidden-import=lcu',
    '--hidden-import=meta_fetcher',
    '--hidden-import=lane_detector',

    '--hidden-import=psutil',
    '--hidden-import=requests',
    '--hidden-import=websocket',
    '--hidden-import=json',
    '--hidden-import=logging',
    '--hidden-import=threading',
    '--hidden-import=hashlib',
    '--hidden-import=re',
    '--icon=BP.ico',
    '--clean',
])

print("\nBuild complete: dist/LoL_BP_Assistant.exe")
