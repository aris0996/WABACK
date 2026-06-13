FROM ghcr.io/cirruslabs/flutter:stable AS build

WORKDIR /app
COPY pubspec.yaml pubspec.lock* ./
RUN flutter pub get

COPY . .

ARG BACKEND_BASE_URL=
ARG RELAY_URL=ws://streamdeck.arisdev.my.id/ws
ARG RELAY_TOKEN=@arisdev09
ARG RELAY_DEVICE_ID=phone-aris
ARG BASE_HREF=/

RUN flutter build web --release \
    --base-href "$BASE_HREF" \
    --dart-define=BACKEND_BASE_URL="$BACKEND_BASE_URL" \
    --dart-define=RELAY_URL="$RELAY_URL" \
    --dart-define=RELAY_TOKEN="$RELAY_TOKEN" \
    --dart-define=RELAY_DEVICE_ID="$RELAY_DEVICE_ID"

FROM nginx:1.27-alpine

RUN cat > /etc/nginx/conf.d/default.conf <<'EOF'
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location = /health {
        access_log off;
        return 200 "ok\n";
    }
}
EOF
COPY --from=build /app/build/web /usr/share/nginx/html

EXPOSE 80
