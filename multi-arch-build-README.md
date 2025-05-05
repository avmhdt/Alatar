# Multi-Architecture Docker Builds for Alatar

This guide explains how to build and use multi-architecture Docker images for the Alatar application. This setup allows your application to run on both ARM64 (e.g., Apple Silicon Macs, AWS Graviton instances) and AMD64 (traditional x86_64) architectures.

## Prerequisites

- Docker Desktop with BuildKit enabled
- Docker Buildx (included in Docker Desktop)
- Docker Compose

## Understanding Multi-Architecture Images

Multi-architecture images contain variants of the same container for different CPU architectures. When you run a multi-architecture image, Docker automatically selects the variant that matches your CPU architecture. This approach allows you to:

- Develop on M1/M2 Macs and deploy to x86 servers seamlessly
- Deploy to AWS Graviton (ARM) instances for better cost-performance
- Use the same images across a variety of hardware platforms

## Building Multi-Architecture Images

We've configured the project with different methods to build multi-architecture images. All of our build scripts now offer three options:

1. Build and push to Docker Hub (requires authentication)
2. Build locally without pushing (default)
3. Build and push to a custom registry (requires authentication)

### Method 1: Using Docker Compose with Buildx Bake Directly

The `docker-compose.yml` file has been configured with `x-bake` sections to support multi-architecture builds. This allows Docker Buildx to build images for both AMD64 and ARM64 platforms.

```bash
# Create a buildx builder instance (if not already created)
docker buildx create --name alatar-builder --use --bootstrap

# Build and load the images locally (no push)
docker buildx bake --load

# OR to build and push to a registry (requires authentication)
docker buildx bake --push
```

### Method 2: Using the Build Script

We've provided convenience scripts that handle the entire process and offer multiple build options:

#### For Linux/macOS:

```bash
# Make the script executable
chmod +x build-multi-arch.sh

# Run the build script
./build-multi-arch.sh
```

#### For Windows:

**Option 1: Batch File**
```
# Run the Windows batch file
build-multi-arch.bat
```

**Option 2: PowerShell Script**
```powershell
# Run the PowerShell script
.\build-multi-arch.ps1
```

The scripts will:
1. Check if Docker Buildx is installed
2. Create a builder instance if needed
3. Present build options (build locally or push to registry)
4. Handle Docker registry authentication
5. Build the multi-architecture images according to your choice

## Configuration Files

The multi-architecture build is controlled by these files:

- **docker-compose.yml**: Contains `x-bake` sections for each service with platform configuration
- **docker-bake.hcl**: Provides advanced configuration for Docker Buildx
- **Dockerfile**: Optimized for multi-architecture builds with BuildKit features

## Building Images Without Pushing

If you don't need to push your images to a registry (for example, if you're testing locally), all scripts now offer an option to build the images and load them into your local Docker daemon:

```bash
# Using the script (select option 2)
./build-multi-arch.sh

# OR directly with buildx
docker buildx bake --load
```

## Handling Authentication Issues

When pushing to Docker Hub or another registry, you need to ensure:

1. You're logged in to the registry
2. You have permission to push to the repositories
3. The repository names include your username or organization prefix

Our scripts now handle these requirements automatically by:
- Checking your login status
- Prompting for credentials if needed
- Adding your username to the image names

## Deploying to Different Architectures

Once the multi-architecture images are built and pushed to a registry, you can deploy them to any supported architecture:

```bash
# Pull the images (Docker will automatically select the correct architecture)
docker-compose pull

# Start the services
docker-compose up -d
```

## Troubleshooting

### QEMU Errors

If you encounter QEMU-related errors during emulation, ensure QEMU is properly set up:

```bash
docker run --privileged --rm tonistiigi/binfmt --install all
```

### Registry Authentication

If you're pushing to a private registry, ensure you're authenticated:

```bash
docker login <your-registry>
```

### Windows-Specific Issues

On Windows, if you encounter issues with script execution, you may need to adjust your PowerShell execution policy:

```powershell
# Run PowerShell as Administrator and execute:
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Push Access Denied

If you see an error like `failed to push: push access denied`, this means either:
- You're not logged into the registry
- The repository doesn't exist (and auto-creation isn't enabled)
- The repository name doesn't include your username (e.g., `username/image-name`)

Use the updated build scripts to handle this properly, or manually build with:

```bash
# Replace YOUR_USERNAME with your Docker Hub username
docker buildx bake --push -f <(sed "s/alatar-app/YOUR_USERNAME\/alatar-app/g" docker-bake.hcl)
```

### Build Performance

Building for non-native architectures with emulation can be slower. For production builds, consider:

1. Using native builders for each architecture
2. Using Docker Build Cloud for faster multi-architecture builds
3. Focusing on cross-compilation instead of emulation for compute-intensive tasks

## Registry Configuration

The build scripts now provide an interactive way to configure registry settings. To manually edit the registry configuration:

1. Edit the `docker-bake.hcl` file to update the image tags with your registry prefix
2. Authenticate with your registry: `docker login <your-registry>`

## Further Resources

- [Docker Multi-Platform Builds Documentation](https://docs.docker.com/build/building/multi-platform/)
- [Docker Buildx Documentation](https://docs.docker.com/buildx/working-with-buildx/)
- [BuildKit Documentation](https://github.com/moby/buildkit) 