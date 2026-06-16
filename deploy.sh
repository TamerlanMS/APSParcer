#!/bin/bash
set -e

echo "=== APSParcer Deploy Script ==="

# Check .env exists
if [ ! -f ".env" ]; then
    echo ""
    echo "ERROR: .env file not found!"
    echo "Creating from .env.example — please edit values before continuing."
    cp .env.example .env

    # Auto-generate JWT secret
    JWT=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    sed -i "s/change_me_jwt_secret/$JWT/" .env

    echo ""
    echo ">>> Edit .env now, then re-run this script <<<"
    echo "    Required: DB_PASS, ADM_PASS_HASH, SUPERADMIN_PASSWORD"
    echo ""
    echo "    Generate admin password hash:"
    echo "    python3 -c \"import bcrypt; print(bcrypt.hashpw(b'YOUR_PASS', bcrypt.gensalt()).decode())\""
    echo ""
    exit 1
fi

# Create data directory
mkdir -p server/data

echo ""
echo ">>> Building and starting containers..."
docker compose -f docker-compose.prod.yml up -d --build

echo ""
echo ">>> Waiting for API to be ready..."
for i in $(seq 1 30); do
    if curl -sf http://localhost/health > /dev/null 2>&1; then
        echo "API is up!"
        break
    fi
    echo "  waiting... ($i/30)"
    sleep 3
done

echo ""
echo "=== Deploy complete ==="
echo "Server: http://192.168.2.78"
echo ""
echo "Useful commands:"
echo "  docker compose -f docker-compose.prod.yml logs -f api     # view logs"
echo "  docker compose -f docker-compose.prod.yml restart api     # restart api"
echo "  docker compose -f docker-compose.prod.yml down            # stop all"
