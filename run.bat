@echo off
if "%1"=="" goto help
if /i "%1"=="install" goto install
if /i "%1"=="folders" goto folders
if /i "%1"=="details" goto details
if /i "%1"=="build"   goto build
if /i "%1"=="all"     goto all
if /i "%1"=="open"    goto open
if /i "%1"=="serve"   goto serve
if /i "%1"=="admin"   goto admin
if /i "%1"=="types"   goto types
if /i "%1"=="scrape"  goto scrape
if /i "%1"=="links"   goto links
echo Unknown command: %1
echo.

:help
echo Usage:  run [command]
echo.
echo Commands:
echo   folders   Scan folder/map names  -^>  folders.json  (fast, ~1 min)
echo   details   Scrape details for include=Y items  -^>  mapy_data.json
echo   build     Generate index.html from mapy_data.json
echo   all       folders + details + build
echo   open      Open index.html in the default browser
echo   types     Update map types only (fast, headless)  -^>  mapy_data.json
echo   serve     Serve via HTTP on localhost:8000
echo   admin     Open admin panel (requires serve)
echo   install   Install Python dependencies (run once)
echo.
echo Deprecated (replaced by folders + details):
echo   scrape    Old full scrape  -^>  mapy_data.json
echo   links     Old share-link pass
goto end

:folders
python scrape_folders.py
goto end

:details
python scrape_details.py
goto end

:build
python generate_site.py
goto end

:all
python scrape_folders.py
if errorlevel 1 (echo Folders scan failed & goto end)
python scrape_details.py
if errorlevel 1 (echo Details scrape failed & goto end)
python generate_site.py
goto end

:open
start index.html
goto end

:types
python scrape_details.py --types
goto end

:serve
start http://localhost:8000
python server.py
goto end

:admin
start http://localhost:8000/admin.html
goto end

:install
pip install playwright jinja2
python -m playwright install chromium
goto end

:scrape
python scrape_mapy.py
goto end

:links
python scrape_links.py
goto end

:end
