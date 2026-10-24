@echo off
REM Build the portable Windows app into dist\PhotoColorSorter
REM Uses a clean virtual environment (.venv) so the build only contains pinned dependencies.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe python -m venv .venv || exit /b 1
set PY=.venv\Scripts\python.exe
%PY% -m pip install -q -r requirements.txt pyinstaller==6.22.3 || exit /b 1
%PY% -m unittest discover tests || exit /b 1
%PY% -m PyInstaller --noconfirm --clean --windowed --name PhotoColorSorter ^
  --add-data "face_detection_yunet_2023mar.onnx;." ^
  photo_color_sorter.py || exit /b 1
copy /y LICENSE dist\PhotoColorSorter\ >nul
copy /y *.md dist\PhotoColorSorter\ >nul
copy /y docs\*.pdf dist\PhotoColorSorter\ >nul
echo Done: dist\PhotoColorSorter\PhotoColorSorter.exe
