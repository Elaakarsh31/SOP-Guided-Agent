FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# GEMINI_API_KEY must be supplied at run time.
# SOP_CONSENT_SCENARIO switches the third-party consent fixture:
#   default (approves) | timeout (never approves) | declined (refuses)
ENV SOP_CONSENT_SCENARIO=default

EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
