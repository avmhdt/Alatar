# PowerShell script for building multi-architecture Docker images

Write-Host "=========================================================" -ForegroundColor Green
Write-Host "      Building Multi-Architecture Docker Images          " -ForegroundColor Green
Write-Host "=========================================================" -ForegroundColor Green

# Check if Docker is installed
try {
    $dockerVersion = docker --version
    Write-Host "Docker is installed: $dockerVersion" -ForegroundColor Yellow
}
catch {
    Write-Host "Docker is not installed or not in PATH. Please install Docker Desktop." -ForegroundColor Red
    exit 1
}

# Check if buildx is available
try {
    $buildxVersion = docker buildx version
    Write-Host "Docker Buildx is available: $buildxVersion" -ForegroundColor Yellow
}
catch {
    Write-Host "Docker Buildx not found. Please install Docker Desktop with Buildx support." -ForegroundColor Red
    exit 1
}

# Create a new builder instance if it doesn't exist
try {
    $builderExists = docker buildx inspect alatar-builder 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Creating new buildx builder instance..." -ForegroundColor Yellow
        docker buildx create --name alatar-builder --driver docker-container --bootstrap
    }
    else {
        Write-Host "Builder 'alatar-builder' already exists." -ForegroundColor Yellow
    }
}
catch {
    Write-Host "Creating new buildx builder instance..." -ForegroundColor Yellow
    docker buildx create --name alatar-builder --driver docker-container --bootstrap
}

# Use the builder
Write-Host "Using alatar-builder instance..." -ForegroundColor Yellow
docker buildx use alatar-builder

# Check Docker Hub login status
$loginStatus = docker info 2>&1 | Select-String -Pattern "Username"
$isLoggedIn = $loginStatus -ne $null

# Ask user what they want to do
Write-Host "Choose build option:" -ForegroundColor Cyan
Write-Host "1) Build and push to Docker Hub (requires authentication)" -ForegroundColor Cyan
Write-Host "2) Build locally without pushing" -ForegroundColor Cyan
Write-Host "3) Build and push to custom registry (requires authentication)" -ForegroundColor Cyan
$option = Read-Host "Enter option (default: 2)"

if (-not $option) {
    $option = "2"
}

switch ($option) {
    "1" {
        if (-not $isLoggedIn) {
            Write-Host "You are not logged into Docker Hub. Please log in:" -ForegroundColor Yellow
            docker login
            
            # Check if login was successful
            if ($LASTEXITCODE -ne 0) {
                Write-Host "Login failed. Building locally without pushing instead." -ForegroundColor Red
                docker buildx bake --load
            } else {
                # Prompt for Docker Hub username
                $username = Read-Host "Enter your Docker Hub username"
                
                # Update the docker-bake.hcl file temporarily
                $bakeFile = Get-Content "docker-bake.hcl"
                $tempBakeFile = $bakeFile -replace 'default = "alatar-app"', "default = `"$username/alatar-app`""
                $tempBakeFile = $tempBakeFile -replace 'default = "alatar-worker"', "default = `"$username/alatar-worker`""
                $tempBakeFile | Set-Content "docker-bake.hcl.temp"
                
                # Build and push
                Write-Host "Building and pushing multi-architecture images to Docker Hub..." -ForegroundColor Yellow
                docker buildx bake --push -f "docker-bake.hcl.temp"
                
                # Restore original file
                Remove-Item "docker-bake.hcl.temp"
            }
        } else {
            # Get the username
            $username = docker info | Select-String -Pattern "Username: (.*)" | ForEach-Object { $_.Matches.Groups[1].Value }
            
            # Update the docker-bake.hcl file temporarily
            $bakeFile = Get-Content "docker-bake.hcl"
            $tempBakeFile = $bakeFile -replace 'default = "alatar-app"', "default = `"$username/alatar-app`""
            $tempBakeFile = $tempBakeFile -replace 'default = "alatar-worker"', "default = `"$username/alatar-worker`""
            $tempBakeFile | Set-Content "docker-bake.hcl.temp"
            
            # Build and push
            Write-Host "Building and pushing multi-architecture images to Docker Hub..." -ForegroundColor Yellow
            docker buildx bake --push -f "docker-bake.hcl.temp"
            
            # Restore original file
            Remove-Item "docker-bake.hcl.temp"
        }
    }
    "2" {
        Write-Host "Building multi-architecture images locally without pushing..." -ForegroundColor Yellow
        # Use --load to load the image into the local Docker daemon instead of pushing
        docker buildx bake --load
    }
    "3" {
        $registry = Read-Host "Enter custom registry URL (e.g., ghcr.io/username)"
        Write-Host "Logging into $registry" -ForegroundColor Yellow
        docker login $registry
        
        # Check if login was successful
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Login failed. Building locally without pushing instead." -ForegroundColor Red
            docker buildx bake --load
        } else {
            # Update the docker-bake.hcl file temporarily
            $bakeFile = Get-Content "docker-bake.hcl"
            $tempBakeFile = $bakeFile -replace 'default = "alatar-app"', "default = `"$registry/alatar-app`""
            $tempBakeFile = $tempBakeFile -replace 'default = "alatar-worker"', "default = `"$registry/alatar-worker`""
            $tempBakeFile | Set-Content "docker-bake.hcl.temp"
            
            # Build and push
            Write-Host "Building and pushing multi-architecture images to $registry..." -ForegroundColor Yellow
            docker buildx bake --push -f "docker-bake.hcl.temp"
            
            # Restore original file
            Remove-Item "docker-bake.hcl.temp"
        }
    }
    default {
        Write-Host "Invalid option. Building locally without pushing..." -ForegroundColor Yellow
        docker buildx bake --load
    }
}

Write-Host "=========================================================" -ForegroundColor Green
Write-Host "      Multi-Architecture Docker Images Complete!         " -ForegroundColor Green
Write-Host "=========================================================" -ForegroundColor Green

Write-Host "Your images are now available for both amd64 and arm64 architectures."
if ($option -eq "2") {
    Write-Host "Images have been loaded into your local Docker daemon."
} else {
    Write-Host "You can now run: docker-compose pull"
    Write-Host "Followed by: docker-compose up -d"
}

# Pause before exit
Write-Host "Press any key to continue..." -ForegroundColor Yellow
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown") 