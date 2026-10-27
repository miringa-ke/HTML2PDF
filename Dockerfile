FROM python:3.12-slim

# WeasyPrint renders through Pango and Cairo, so it needs real system
# libraries. These are the Debian names; getting one wrong shows up as a
# cryptic "cannot load library" at import time, not at install time.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 \
      libpangoft2-1.0-0 \
      libharfbuzz0b \
      libharfbuzz-subset0 \
      libffi8 \
      libjpeg62-turbo \
      libopenjp2-7 \
      shared-mime-info \
      fonts-liberation2 \
      fonts-dejavu-core \
      fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
# Drop brand fonts (.ttf/.otf) into ./fonts and they become available by family
# name to every document. fc-cache is what makes them visible to Pango.
COPY fonts/ /usr/share/fonts/custom/
RUN fc-cache -f

COPY css/ /app/css/

EXPOSE 5000
# Two workers is plenty; a manifesto render is ~2 seconds and the queue is a
# scheduled sweep, not user traffic. Timeout is generous for a long document.
#
# Shell form on purpose: Render injects PORT and the container must bind to it.
# The fallback keeps this identical under docker compose, where PORT is unset.
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-5000} --workers 2 --timeout 180 --access-logfile - app:app"]
