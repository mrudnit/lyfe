FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# No apt-get here on purpose. Every dependency ships prebuilt wheels for
# linux/amd64 and linux/arm64, so the image needs no compiler and the build
# never touches the Debian package servers.
COPY requirements.txt .
RUN pip install --only-binary=:all: -r requirements.txt

COPY . .

CMD ["python", "-m", "lyfe.bot.main"]
