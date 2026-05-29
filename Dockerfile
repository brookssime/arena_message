# A Dockerfile describes how to build the container image the cloud host runs.
# Think of it like a reproducible "from a clean machine, do exactly these steps" recipe.

# Start from a small official Python image. "slim" = Debian without the extra bulk.
FROM python:3.12-slim

# Don't write .pyc files, and stream logs straight to stdout (so the host captures them live).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy + install dependencies FIRST, separately from the app code. Docker caches each layer,
# so as long as requirements.txt doesn't change, rebuilds skip re-installing everything.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Now copy the rest of the application code.
COPY . .

# Document the port the app listens on. Most hosts inject their own $PORT at runtime.
EXPOSE 8080

# Run the production server. gunicorn imports the `app` object from app.py and serves it.
# We bind to 0.0.0.0 so the container accepts external connections. The `sh -c` form lets us
# expand $PORT if the host provides one, defaulting to 8080 otherwise.
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-8080} app:app"]
