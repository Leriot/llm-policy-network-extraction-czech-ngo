@echo off
chcp 65001 >nul
cd /d "%~dp0..\.."

echo =====================================================
echo  Judge LLM  --  anthropic/claude-sonnet-4-6
echo  Extended thinking enabled (5,000 token budget)
echo =====================================================
echo.

:menu
echo  1. Status (how many judged so far)
echo  2. Test run -- 10 cases (see full outputs)
echo  3. Run all 289 splits  (resume-safe)
echo  4. Validation run  -- 9 unanimous + 9 majority (judge quality check)
echo  5. Exit
echo.
set /p choice=Choice:

if "%choice%"=="1" goto status
if "%choice%"=="2" goto test10
if "%choice%"=="3" goto runall
if "%choice%"=="4" goto validation
if "%choice%"=="5" exit /b
echo Invalid choice.
goto menu

:status
echo.
python scripts\llm_validation\judge_ties.py --status
echo.
pause
goto menu

:test10
echo.
echo Running 10 test cases -- full judge reasoning will be printed.
echo Output: data\final_validation_run_data\judged_ties.jsonl
echo.
python scripts\llm_validation\judge_ties.py --limit 10
echo.
pause
goto menu

:runall
echo.
echo Running all remaining splits (safe to interrupt -- resumes on next run).
echo Output: data\final_validation_run_data\judged_ties.jsonl
echo.
python scripts\llm_validation\judge_ties.py
echo.
pause
goto menu

:validation
echo.
echo Validation mode: judge sees 9 unanimous + 9 majority cases with known answers.
echo Output: data\final_validation_run_data\judged_validation.jsonl
echo.
python scripts\llm_validation\judge_ties.py --validation
echo.
pause
goto menu
