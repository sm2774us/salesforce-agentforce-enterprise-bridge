FROM python:3.12-slim AS build
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim
RUN useradd --system --uid 10001 bridge
COPY --from=build /install /usr/local
USER 10001
EXPOSE 8080
HEALTHCHECK CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8080/healthz')"
ENTRYPOINT ["bridge", "serve", "--host", "0.0.0.0", "--port", "8080"]
