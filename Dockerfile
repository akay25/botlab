# The harness needs exactly the interpreter the Pipfile pins: pipenv's
# --deploy flag refuses to install against any other.
FROM python:3.14.0-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Inside a container loopback reaches nobody; the published port does.
    APP_HOST=0.0.0.0

WORKDIR /app

# Runtime packages only, straight from the lock. The dev packages hold the
# automation clients, which run on the host against the published port.
COPY Pipfile Pipfile.lock ./
RUN pip install --no-cache-dir pipenv \
 && pipenv install --system --deploy \
 && pip uninstall -y pipenv

COPY src ./src

# The ClientHello front end listens here. uvicorn's upstream port stays bound
# to the container's loopback, so it cannot be published by mistake.
EXPOSE 8443

CMD ["python", "-m", "src"]
