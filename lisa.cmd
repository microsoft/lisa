ECHO OFF

SETLOCAL EnableDelayedExpansion

SET PYTHON_VERSION=3.8.3
SET RUNTIME_PATH=%CD%\runtime
SET RUNTIME_PYTHON_PATH=%RUNTIME_PATH%\bin\windows\python
SET RUNTIME_PYTHON_COMMAND=%RUNTIME_PYTHON_PATH%\python.exe
SET PATH=%RUNTIME_PYTHON_PATH%;%RUNTIME_PYTHON_PATH%\Scripts;%PATH%

IF EXIST "!RUNTIME_PYTHON_COMMAND!" (
    FOR /F "tokens=2 USEBACKQ" %%F IN (`!RUNTIME_PYTHON_COMMAND! -V`) DO (
        SET ORIGINAL_PYTHON_VERSION=%%F
        if !PYTHON_VERSION! NEQ %%F (
            ECHO SHELL: python version: expected: !PYTHON_VERSION!, current: %%F, removing it.
            rmdir /s /q !RUNTIME_PYTHON_PATH!
            IF %ERRORLEVEL% NEQ 0 (
                ECHO SHELL: "error on remove previous version python."
                ENDLOCAL
                exit %ERRORLEVEL%
            )
        )
    )
)

IF NOT EXIST "!RUNTIME_PYTHON_COMMAND!" (
    ECHO SHELL: !RUNTIME_PYTHON_COMMAND! doesn't exists.

    SETLOCAL EnableDelayedExpansion
    SET PYTHON_URL=https://www.python.org/ftp/python/%PYTHON_VERSION%/python-%PYTHON_VERSION%-embed-amd64.zip
    SET PIP_URL=https://bootstrap.pypa.io/get-pip.py
    SET RUNTIME_TEMP_PATH=%RUNTIME_PATH%\temp
    SET PYTHON_ZIP_NAME=!RUNTIME_TEMP_PATH!\python_windows_%PYTHON_VERSION%.zip
    mkdir !RUNTIME_TEMP_PATH! 2> nul

    ECHO SHELL: downloading from !PYTHON_URL!
    powershell /c "Import-module BitsTransfer; Start-BitsTransfer -Source $Env:PYTHON_URL -Destination $Env:PYTHON_ZIP_NAME"
    
    ECHO SHELL: extracting !PYTHON_ZIP_NAME! to !RUNTIME_PYTHON_PATH!
    powershell /c "Expand-Archive $Env:PYTHON_ZIP_NAME -DestinationPath $Env:RUNTIME_PYTHON_PATH"
    del !PYTHON_ZIP_NAME!

    ECHO SHELL: downloading and install pip to !RUNTIME_PYTHON_PATH!
    powershell /c "Import-module BitsTransfer; Start-BitsTransfer -Source $Env:PIP_URL -Destination $Env:RUNTIME_PYTHON_PATH\get-pip.py"

    !RUNTIME_PYTHON_PATH!\python !RUNTIME_PYTHON_PATH!\get-pip.py

    REM fix pip cannot be find, and add lisa to package list
    FOR %%G IN (!RUNTIME_PYTHON_PATH!\*._pth) DO (
        echo lib>> %%G
        echo lib\site-packages>> %%G
        echo scripts>> %%G
        echo %CD%>> %%G
    )
)

REM updating Python packages
%RUNTIME_PYTHON_PATH%\python -m pip install -q -r requirements.txt

pushd lisa
%RUNTIME_PYTHON_PATH%\python -m lisa.main %*
popd

ENDLOCAL
