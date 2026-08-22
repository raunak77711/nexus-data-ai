# Alpine because this image only ever runs Vite's dev server: no native module
# in the dependency tree needs glibc, and the base is a fraction of the size of
# node:20-slim. Pinned to the Alpine release as well as the Node major, for the
# same reason the backend pins its Debian release.
FROM node:20-alpine3.20

WORKDIR /app

# package.json AND package-lock.json, then `npm ci` -- not `npm install`.
# `ci` installs exactly the lockfile, fails if the two disagree, and never
# silently updates a transitive dependency, which is the whole point of having
# committed a lockfile. It is also considerably faster.
COPY package.json package-lock.json ./
RUN npm ci

# The source is bind-mounted over this in development, so this COPY exists so
# the image is runnable on its own rather than only under compose.
COPY . .

EXPOSE 5173

# --host 0.0.0.0 or the dev server binds to the container's loopback and the
# published port answers nothing at all.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
