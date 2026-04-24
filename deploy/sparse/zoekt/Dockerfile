# Stage 1: Build zoekt binaries
FROM golang:1.25-alpine AS builder

ARG ZOEKT_VERSION=v0.0.0-20260413093009-c3d4afa94960

RUN apk add --no-cache git

RUN go install github.com/sourcegraph/zoekt/cmd/zoekt-webserver@${ZOEKT_VERSION} && \
    go install github.com/sourcegraph/zoekt/cmd/zoekt-index@${ZOEKT_VERSION} && \
    go install github.com/sourcegraph/zoekt/cmd/zoekt-git-index@${ZOEKT_VERSION}

# Stage 2: Runtime
FROM alpine:3.19

RUN apk add --no-cache curl

COPY --from=builder /go/bin/zoekt-webserver /usr/local/bin/
COPY --from=builder /go/bin/zoekt-index /usr/local/bin/
COPY --from=builder /go/bin/zoekt-git-index /usr/local/bin/

EXPOSE 6070

CMD ["zoekt-webserver", "-index", "/data/index"]
