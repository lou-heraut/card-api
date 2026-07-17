FROM python:3.12-slim

# card et stase épinglés par révision (mettre à jour délibérément :
# une image = des versions traçables de toute la pile).
ARG CARD_REF=main
ARG STASE_REF=main

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src

# Tarballs GitHub plutôt que git+https : l'image slim n'a pas git, et
# pip installe une archive directement (branche, tag ou commit).
RUN pip install --no-cache-dir \
        "https://github.com/lou-heraut/stase/archive/${STASE_REF}.tar.gz" \
        "https://github.com/lou-heraut/card/archive/${CARD_REF}.tar.gz" \
    && pip install --no-cache-dir .

# cache des chroniques + journal d'usage (volume, cf. compose.yaml)
VOLUME /data
ENV CARD_API_DATA=/data

EXPOSE 8000
CMD ["uvicorn", "card_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
