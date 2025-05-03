# Use an official Python runtime as a parent image
FROM python:3.12 as builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set work directory
WORKDIR /app

# Install poetry
RUN pip install poetry

# Copy project definition files
COPY poetry.lock pyproject.toml /app/

# Install dependencies
# --no-root: Don't install the project itself, only dependencies
# --only main: Install only main dependencies (no dev)
RUN poetry config virtualenvs.create false && \
    poetry install --no-root --only main

# --- Final Stage ---
FROM python:3.12

# Create a non-root user and group
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Copy installed dependencies from builder stage
# Ensure permissions are appropriate for the appuser
COPY --from=builder --chown=appuser:appuser /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder --chown=appuser:appuser /usr/local/bin /usr/local/bin

# Copy application code
# Ensure permissions are appropriate for the appuser
COPY --chown=appuser:appuser ./app /app/app
COPY --chown=appuser:appuser ./worker.py /app/worker.py
COPY --chown=appuser:appuser ./migrations /app/migrations
COPY --chown=appuser:appuser ./alembic.ini /app/alembic.ini

# Change ownership of the work directory
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose port 8000
EXPOSE 8000

# Add a basic healthcheck (adjust path and interval as needed)
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/_health || exit 1

# Command to run the application using uvicorn
# Use multiple workers in production, e.g., based on CPU cores
# Ensure the number of workers is appropriate for your server resources
# Example: Using 2 workers
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
