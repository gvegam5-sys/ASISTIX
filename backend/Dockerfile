FROM python:3.13-slim
WORKDIR /app
COPY requirements*.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt -r requirements-migrations.lock.txt
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
RUN useradd -m asistix
USER asistix
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
