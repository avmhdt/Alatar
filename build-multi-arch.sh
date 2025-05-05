#!/bin/bash
set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Print header
echo -e "${GREEN}=========================================================${NC}"
echo -e "${GREEN}      Building Multi-Architecture Docker Images          ${NC}"
echo -e "${GREEN}=========================================================${NC}"

# Check if buildx is installed
if ! docker buildx version > /dev/null 2>&1; then
    echo -e "${YELLOW}Docker Buildx not found. Please install Docker Desktop with Buildx support.${NC}"
    exit 1
fi

# Create a new builder instance if it doesn't exist
if ! docker buildx inspect alatar-builder > /dev/null 2>&1; then
    echo -e "${YELLOW}Creating new buildx builder instance...${NC}"
    docker buildx create --name alatar-builder --driver docker-container --bootstrap
fi

# Use the builder
echo -e "${YELLOW}Using alatar-builder instance...${NC}"
docker buildx use alatar-builder

# Check Docker Hub login status
IS_LOGGED_IN=1
if docker info 2>/dev/null | grep -q "Username"; then
    IS_LOGGED_IN=0
fi

# Ask user what they want to do
echo -e "${YELLOW}Choose build option:${NC}"
echo "1) Build and push to Docker Hub (requires authentication)"
echo "2) Build locally without pushing"
echo "3) Build and push to custom registry (requires authentication)"
read -p "Enter option (default: 2): " OPTION

# Set default option
OPTION=${OPTION:-2}

if [ "$OPTION" = "1" ]; then
    # Check if already logged in
    if [ $IS_LOGGED_IN -eq 1 ]; then
        echo -e "${YELLOW}You are not logged into Docker Hub. Please log in:${NC}"
        docker login
        
        # Check if login was successful
        if [ $? -ne 0 ]; then
            echo -e "${YELLOW}Login failed. Building locally without pushing instead.${NC}"
            docker buildx bake --load
            BUILD_COMPLETE=1
        else
            # Prompt for Docker Hub username
            read -p "Enter your Docker Hub username: " USERNAME
            
            # Create a temporary file with updated image names
            sed -e "s/default = \"alatar-app\"/default = \"$USERNAME\/alatar-app\"/" \
                -e "s/default = \"alatar-worker\"/default = \"$USERNAME\/alatar-worker\"/" \
                docker-bake.hcl > docker-bake.hcl.temp
            
            # Build and push
            echo -e "${YELLOW}Building and pushing multi-architecture images to Docker Hub...${NC}"
            docker buildx bake --push -f docker-bake.hcl.temp
            
            # Restore original file
            rm docker-bake.hcl.temp
        fi
    else
        # Get username from Docker info
        USERNAME=$(docker info 2>/dev/null | grep Username | awk '{print $2}')
        
        # Create a temporary file with updated image names
        sed -e "s/default = \"alatar-app\"/default = \"$USERNAME\/alatar-app\"/" \
            -e "s/default = \"alatar-worker\"/default = \"$USERNAME\/alatar-worker\"/" \
            docker-bake.hcl > docker-bake.hcl.temp
        
        # Build and push
        echo -e "${YELLOW}Building and pushing multi-architecture images to Docker Hub...${NC}"
        docker buildx bake --push -f docker-bake.hcl.temp
        
        # Restore original file
        rm docker-bake.hcl.temp
    fi
elif [ "$OPTION" = "2" ]; then
    echo -e "${YELLOW}Building multi-architecture images locally without pushing...${NC}"
    # Use --load to load the image into the local Docker daemon instead of pushing
    docker buildx bake --load
elif [ "$OPTION" = "3" ]; then
    read -p "Enter custom registry URL (e.g., ghcr.io/username): " REGISTRY
    echo -e "${YELLOW}Logging into $REGISTRY${NC}"
    docker login $REGISTRY
    
    # Check if login was successful
    if [ $? -ne 0 ]; then
        echo -e "${YELLOW}Login failed. Building locally without pushing instead.${NC}"
        docker buildx bake --load
        BUILD_COMPLETE=1
    else
        # Create a temporary file with updated image names
        sed -e "s/default = \"alatar-app\"/default = \"$REGISTRY\/alatar-app\"/" \
            -e "s/default = \"alatar-worker\"/default = \"$REGISTRY\/alatar-worker\"/" \
            docker-bake.hcl > docker-bake.hcl.temp
        
        # Build and push
        echo -e "${YELLOW}Building and pushing multi-architecture images to $REGISTRY...${NC}"
        docker buildx bake --push -f docker-bake.hcl.temp
        
        # Restore original file
        rm docker-bake.hcl.temp
    fi
else
    echo -e "${YELLOW}Invalid option. Building locally without pushing...${NC}"
    docker buildx bake --load
fi

echo -e "${GREEN}=========================================================${NC}"
echo -e "${GREEN}      Multi-Architecture Docker Images Complete!         ${NC}"
echo -e "${GREEN}=========================================================${NC}"

echo -e "Your images are now available for both amd64 and arm64 architectures."
if [ "$OPTION" = "2" ] || [ "$BUILD_COMPLETE" = "1" ]; then
    echo -e "Images have been loaded into your local Docker daemon."
else
    echo -e "You can now run: docker-compose pull"
    echo -e "Followed by: docker-compose up -d"
fi 