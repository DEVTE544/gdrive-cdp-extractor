@echo off
echo.
echo ============================================================
echo  CDP v3.4.2 - Full Build  ^(Launcher + AppCore^)
echo ============================================================
echo.

:: STEP 1: Build AppCore
echo --- STEP 1/4  Building AppCore ---
python -m nuitka --standalone ^
       --include-package=aiohttp ^
       --include-package=aiohttp.http_websocket ^
       --include-package=yarl ^
       --include-package=multidict ^
       --include-package=frozenlist ^
       --include-package=aiosignal ^
       --windows-console-mode=force ^
       --output-dir=_build_temp ^
       --output-filename=CDP-v3.4.2.exe ^
       cdp_extractor.py

if not exist "_build_temp\cdp_extractor.dist\CDP-v3.4.2.exe" (
    echo.
    echo  FAILED: AppCore build failed.
    pause
    exit /b 1
)
echo  AppCore build OK.
echo.

:: STEP 2: Build Launcher
echo --- STEP 2/4  Building Launcher ---
python -m nuitka --onefile ^
       --windows-console-mode=force ^
       --output-dir=_build_temp ^
       --output-filename=Launcher.exe ^
       launcher.py

if not exist "_build_temp\Launcher.exe" (
    echo.
    echo  FAILED: Launcher build failed.
    pause
    exit /b 1
)
echo  Launcher build OK.
echo.

:: STEP 3: Assemble layout
echo --- STEP 3/4  Assembling layout ---

if exist "dist" rmdir /s /q "dist"
mkdir "dist"
mkdir "dist\AppCore"

move "_build_temp\Launcher.exe" "dist\Launcher.exe"
xcopy "_build_temp\cdp_extractor.dist" "dist\AppCore" /E /I /Y /Q

rmdir /s /q "_build_temp"

echo  Layout assembled.
echo.

:: STEP 4: Create root-level user folders
echo --- STEP 4/4  Creating folders ---
mkdir "dist\tools"
mkdir "dist\output"
mkdir "dist\logs"
mkdir "dist\temp"

echo.
echo ============================================================
echo  BUILD COMPLETE
echo ============================================================
echo.
echo  dist\
echo  ^|-- Launcher.exe       ^<-- Run this
echo  ^|-- tools\             ^<-- Put ffmpeg.exe + ffprobe.exe here
echo  ^|-- output\
echo  ^|-- logs\
echo  ^|-- temp\
echo  ^+-- AppCore\
echo      ^|-- CDP-v3.4.2.exe  ^<-- Protected ^(do not run directly^)
echo      ^+-- ^[Nuitka DLLs^]
echo.
pause
