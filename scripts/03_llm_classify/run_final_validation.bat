@echo off
cd /d "%~dp0..\.."
setlocal

:: ─────────────────────────────────────────────────────────────────────────────
::  Final Validation Run — 4 Models x 3,086 Datapoints
::  Scout · Mistral · Gemma 4 · GPT-5.4 Nano
::  Input:  data/processed/final_validation/datapoints.jsonl
::  Output: data/processed/final_validation/results_{model}.jsonl
:: ─────────────────────────────────────────────────────────────────────────────

:MAIN
cls
echo.
echo  +======================================================+
echo  ^|     FINAL VALIDATION RUN - 4 Models                  ^|
echo  ^|     Scout / Mistral / Gemma 4 / GPT-5.4 Nano         ^|
echo  +======================================================+
echo.
echo  [1] Status + agreement overview
echo  [2] Dry run (validate data, show expected costs)
echo  [3] Run single model
echo  [4] Run ALL models (sequential)
echo  [5] Run ALL models (parallel threads)
echo  [6] Build/rebuild datapoints.jsonl from step6
echo  [Q] Quit
echo.
set /p CHOICE="  Choice: "

if /i "%CHOICE%"=="1" goto STATUS
if /i "%CHOICE%"=="2" goto DRY_RUN
if /i "%CHOICE%"=="3" goto PICK_MODEL
if /i "%CHOICE%"=="4" goto RUN_ALL_SEQ
if /i "%CHOICE%"=="5" goto RUN_ALL_PAR
if /i "%CHOICE%"=="6" goto BUILD
if /i "%CHOICE%"=="Q" goto END
goto MAIN


:STATUS
echo.
python scripts\llm_validation\run_final_validation.py --status
pause
goto MAIN


:DRY_RUN
echo.
python scripts\llm_validation\run_final_validation.py --dry-run
pause
goto MAIN


:PICK_MODEL
cls
echo.
echo  Select model:
echo.
echo  [1] Scout        (meta-llama/llama-4-scout)
echo  [2] Mistral      (mistralai/mistral-small-2603)
echo  [3] Gemma 4      (google/gemma-4-31b-it)
echo  [4] GPT-5.4 Nano (openai/gpt-5.4-nano)
echo  [B] Back
echo.
set /p MSEL="  Choice: "

if /i "%MSEL%"=="1" goto RUN_SCOUT
if /i "%MSEL%"=="2" goto RUN_MISTRAL
if /i "%MSEL%"=="3" goto RUN_GEMMA
if /i "%MSEL%"=="4" goto RUN_GPT
if /i "%MSEL%"=="B" goto MAIN
goto PICK_MODEL


:RUN_SCOUT
echo.
python scripts\llm_validation\run_final_validation.py --model scout
pause
goto MAIN

:RUN_MISTRAL
echo.
python scripts\llm_validation\run_final_validation.py --model mistral
pause
goto MAIN

:RUN_GEMMA
echo.
python scripts\llm_validation\run_final_validation.py --model gemma
pause
goto MAIN

:RUN_GPT
echo.
python scripts\llm_validation\run_final_validation.py --model gpt
pause
goto MAIN


:RUN_ALL_SEQ
echo.
echo  Running all 4 models sequentially...
echo.
python scripts\llm_validation\run_final_validation.py --all
echo.
echo  All models done!
pause
goto MAIN


:RUN_ALL_PAR
echo.
echo  Running all 4 models in parallel threads...
echo.
python scripts\llm_validation\run_final_validation.py --all --parallel
echo.
echo  All models done!
pause
goto MAIN


:BUILD
echo.
echo  Building/rebuilding datapoints.jsonl from full_dataset...
echo.
python scripts\llm_validation\build_final_validation_dataset.py --force
echo.
pause
goto MAIN


:END
endlocal
exit /b 0
