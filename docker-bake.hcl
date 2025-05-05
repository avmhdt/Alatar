// Define the variables for image names and tags
variable "APP_IMAGE" {
  default = "alatar-app"
}

variable "WORKER_IMAGE_PREFIX" {
  default = "alatar-worker"
}

variable "TAG" {
  default = "latest"
}

// Define the target platforms
variable "PLATFORMS" {
  default = ["linux/amd64", "linux/arm64"]
}

// Common attributes for all targets
group "default" {
  targets = ["app", "worker-c1", "worker-data-retrieval", "worker-quantitative-analysis", 
             "worker-qualitative-analysis", "worker-recommendation-generation", 
             "worker-comparative-analysis", "worker-predictive-analysis"]
}

// Base target with common settings
target "docker-metadata-action" {
  platforms = "${PLATFORMS}"
}

// App service
target "app" {
  inherits = ["docker-metadata-action"]
  context = "."
  dockerfile = "Dockerfile"
  tags = ["${APP_IMAGE}:${TAG}"]
  args = {
    BUILDKIT_INLINE_CACHE = "1"
  }
}

// Worker C1 service
target "worker-c1" {
  inherits = ["docker-metadata-action"]
  context = "."
  dockerfile = "Dockerfile"
  tags = ["${WORKER_IMAGE_PREFIX}-c1:${TAG}"]
  args = {
    BUILDKIT_INLINE_CACHE = "1"
  }
}

// Worker Data Retrieval service
target "worker-data-retrieval" {
  inherits = ["docker-metadata-action"]
  context = "."
  dockerfile = "Dockerfile"
  tags = ["${WORKER_IMAGE_PREFIX}-data-retrieval:${TAG}"]
  args = {
    BUILDKIT_INLINE_CACHE = "1"
  }
}

// Worker Quantitative Analysis service
target "worker-quantitative-analysis" {
  inherits = ["docker-metadata-action"]
  context = "."
  dockerfile = "Dockerfile"
  tags = ["${WORKER_IMAGE_PREFIX}-quantitative-analysis:${TAG}"]
  args = {
    BUILDKIT_INLINE_CACHE = "1"
  }
}

// Worker Qualitative Analysis service
target "worker-qualitative-analysis" {
  inherits = ["docker-metadata-action"]
  context = "."
  dockerfile = "Dockerfile"
  tags = ["${WORKER_IMAGE_PREFIX}-qualitative-analysis:${TAG}"]
  args = {
    BUILDKIT_INLINE_CACHE = "1"
  }
}

// Worker Recommendation Generation service
target "worker-recommendation-generation" {
  inherits = ["docker-metadata-action"]
  context = "."
  dockerfile = "Dockerfile"
  tags = ["${WORKER_IMAGE_PREFIX}-recommendation-generation:${TAG}"]
  args = {
    BUILDKIT_INLINE_CACHE = "1"
  }
}

// Worker Comparative Analysis service
target "worker-comparative-analysis" {
  inherits = ["docker-metadata-action"]
  context = "."
  dockerfile = "Dockerfile"
  tags = ["${WORKER_IMAGE_PREFIX}-comparative-analysis:${TAG}"]
  args = {
    BUILDKIT_INLINE_CACHE = "1"
  }
}

// Worker Predictive Analysis service
target "worker-predictive-analysis" {
  inherits = ["docker-metadata-action"]
  context = "."
  dockerfile = "Dockerfile"
  tags = ["${WORKER_IMAGE_PREFIX}-predictive-analysis:${TAG}"]
  args = {
    BUILDKIT_INLINE_CACHE = "1"
  }
} 