# One image: the web server and the browser that renders the PDF.
#
# Build context is the repository root, because template.html lives there and
# is shared with the CLI path:
#
#   docker build -f web/Dockerfile -t cv-maker .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CHROME=/usr/bin/chromium \
    CHROME_NO_SANDBOX=1

# fonts-liberation is metric-compatible with Helvetica, which is what the
# template asks for; without it Chromium falls back to DejaVu and the CV comes
# out noticeably wider than the CLI renders it on a Mac.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      chromium \
      fonts-liberation \
      fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

# Map the template's font stack onto what is actually installed, so the
# container renders the same shapes as a machine that has Avenir or Helvetica.
RUN printf '%s\n' \
  '<?xml version="1.0"?>' \
  '<!DOCTYPE fontconfig SYSTEM "fonts.dtd">' \
  '<fontconfig>' \
  '  <alias><family>Avenir Next</family><prefer><family>Liberation Sans</family></prefer></alias>' \
  '  <alias><family>Avenir</family><prefer><family>Liberation Sans</family></prefer></alias>' \
  '  <alias><family>Helvetica Neue</family><prefer><family>Liberation Sans</family></prefer></alias>' \
  '  <alias><family>Helvetica</family><prefer><family>Liberation Sans</family></prefer></alias>' \
  '  <alias><family>sans-serif</family><prefer><family>Liberation Sans</family></prefer></alias>' \
  '</fontconfig>' > /etc/fonts/local.conf

WORKDIR /app

COPY web/requirements.txt web/requirements.txt
RUN pip install --no-cache-dir -r web/requirements.txt

COPY template.html ./template.html
COPY web/ ./web/

# Nothing here runs as root. The renderer writes only into per-request
# directories under /tmp, which the compose file mounts as a tmpfs.
RUN useradd --create-home --uid 10001 cv
USER cv

WORKDIR /app/web
EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
