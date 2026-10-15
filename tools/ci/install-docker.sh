#!/bin/sh
# Same Docker socket topology as reYunPlex; no SSH or host path assumptions.
set -eu
image='docker:27.5.1-cli@sha256:851f91d241214e7c6db86513b270d58776379aacc5eb9c4a87e5b47115e3065c'
api() {
  endpoint=$1
  shift
  curl --fail-with-body --silent --show-error --unix-socket /var/run/docker.sock \
    "http://localhost/v${DOCKER_API_VERSION:-1.43}$endpoint" "$@"
}
if ! api "/images/$image/json" >/dev/null 2>&1; then
  api "/images/create?fromImage=$image" --request POST
fi
temporary=$(mktemp -d)
container_id=''
cleanup() {
  if [ -n "$container_id" ]; then
    api "/containers/$container_id" --request DELETE >/dev/null || true
  fi
  rm -rf "$temporary"
}
trap cleanup EXIT HUP INT TERM
api /containers/create --header 'Content-Type: application/json' \
  --data "{\"Image\":\"$image\",\"HostConfig\":{\"NetworkMode\":\"none\"}}" \
  --output "$temporary/container.json"
container_id=$(node -e 'process.stdout.write(JSON.parse(require("node:fs").readFileSync(process.argv[1], "utf8")).Id)' "$temporary/container.json")
api "/containers/$container_id/archive?path=/usr/local/bin/docker" --output "$temporary/docker.tar"
tar -xf "$temporary/docker.tar" -C /usr/local/bin
docker version
