FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# GEMINI_API_KEY must be supplied at run time; the image never bakes one in.
# SOP_MODEL overrides the Gemini model.
# SOP_CONSENT_SCENARIO picks a script from consent_scenarios.json:
#   default (approves) | timeout (never answers) | denied (refuses)
ENV SOP_CONSENT_SCENARIO=default

EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
