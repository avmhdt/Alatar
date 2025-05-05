@echo off
setlocal enabledelayedexpansion

echo =========================================================
echo       Building Multi-Architecture Docker Images          
echo =========================================================

REM Check if Docker is installed
docker --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Docker is not installed or not in PATH. Please install Docker Desktop.
    exit /b 1
)

REM Check if buildx is available
docker buildx version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Docker Buildx not found. Please install Docker Desktop with Buildx support.
    exit /b 1
)

REM Create a new builder instance if it doesn't exist
docker buildx inspect alatar-builder >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Creating new buildx builder instance...
    docker buildx create --name alatar-builder --driver docker-container --bootstrap
)

REM Use the builder
echo Using alatar-builder instance...
docker buildx use alatar-builder

REM Check Docker Hub login status
docker info | findstr "Username" >nul 2>&1
set IS_LOGGED_IN=%ERRORLEVEL%

REM Ask user what they want to do
echo Choose build option:
echo 1) Build and push to Docker Hub (requires authentication)
echo 2) Build locally without pushing
echo 3) Build and push to custom registry (requires authentication)
set /p OPTION="Enter option (default: 2): "

REM Set default option
if "%OPTION%"=="" set OPTION=2

if "%OPTION%"=="1" (
    REM Check if already logged in
    if %IS_LOGGED_IN% NEQ 0 (
        echo You are not logged into Docker Hub. Please log in:
        docker login
        
        REM Check if login was successful
        if %ERRORLEVEL% NEQ 0 (
            echo Login failed. Building locally without pushing instead.
            docker buildx bake --load
            goto BUILD_COMPLETE
        )
        
        REM Prompt for Docker Hub username
        set /p USERNAME="Enter your Docker Hub username: "
        
        REM Create a temporary file with updated image names
        powershell -command "$content = Get-Content 'docker-bake.hcl'; $content = $content -replace 'default = \"alatar-app\"', 'default = \"%USERNAME%/alatar-app\"'; $content = $content -replace 'default = \"alatar-worker\"', 'default = \"%USERNAME%/alatar-worker\"'; $content | Set-Content 'docker-bake.hcl.temp'"
        
        REM Build and push
        echo Building and pushing multi-architecture images to Docker Hub...
        docker buildx bake --push -f docker-bake.hcl.temp
        
        REM Restore original file
        del docker-bake.hcl.temp
    ) else (
        REM Get username from Docker info
        for /f "tokens=2 delims=: " %%u in ('docker info ^| findstr "Username"') do (
            set USERNAME=%%u
        )
        
        REM Create a temporary file with updated image names
        powershell -command "$content = Get-Content 'docker-bake.hcl'; $content = $content -replace 'default = \"alatar-app\"', 'default = \"%USERNAME%/alatar-app\"'; $content = $content -replace 'default = \"alatar-worker\"', 'default = \"%USERNAME%/alatar-worker\"'; $content | Set-Content 'docker-bake.hcl.temp'"
        
        REM Build and push
        echo Building and pushing multi-architecture images to Docker Hub...
        docker buildx bake --push -f docker-bake.hcl.temp
        
        REM Restore original file
        del docker-bake.hcl.temp
    )
) else if "%OPTION%"=="2" (
    echo Building multi-architecture images locally without pushing...
    REM Use --load to load the image into the local Docker daemon instead of pushing
    docker buildx bake --load
) else if "%OPTION%"=="3" (
    set /p REGISTRY="Enter custom registry URL (e.g., ghcr.io/username): "
    echo Logging into %REGISTRY%
    docker login %REGISTRY%
    
    REM Check if login was successful
    if %ERRORLEVEL% NEQ 0 (
        echo Login failed. Building locally without pushing instead.
        docker buildx bake --load
        goto BUILD_COMPLETE
    )
    
    REM Create a temporary file with updated image names
    powershell -command "$content = Get-Content 'docker-bake.hcl'; $content = $content -replace 'default = \"alatar-app\"', 'default = \"%REGISTRY%/alatar-app\"'; $content = $content -replace 'default = \"alatar-worker\"', 'default = \"%REGISTRY%/alatar-worker\"'; $content | Set-Content 'docker-bake.hcl.temp'"
    
    REM Build and push
    echo Building and pushing multi-architecture images to %REGISTRY%...
    docker buildx bake --push -f docker-bake.hcl.temp
    
    REM Restore original file
    del docker-bake.hcl.temp
) else (
    echo Invalid option. Building locally without pushing...
    docker buildx bake --load
)

:BUILD_COMPLETE
echo =========================================================
echo       Multi-Architecture Docker Images Complete!         
echo =========================================================

echo Your images are now available for both amd64 and arm64 architectures.
if "%OPTION%"=="2" (
    echo Images have been loaded into your local Docker daemon.
) else (
    echo You can now run: docker-compose pull
    echo Followed by: docker-compose up -d
)

pause 