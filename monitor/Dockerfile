FROM python:3.13-alpine
WORKDIR /app
COPY monitor.py .
RUN adduser -D -H dw
USER dw
ENV PYTHONUNBUFFERED=1
CMD ["python", "-u", "monitor.py"]
