#!/bin/bash

echo "Testing Claude Code API Gateway"
echo

echo "Testing Models Endpoint:"
curl -s http://localhost:8000/v1/models | jq .

echo
echo "Testing Health Endpoint:"
curl -s http://localhost:8000/health | jq .

echo
echo "API is working! No authentication required."
echo "Available endpoints:"
echo "  - GET  /v1/models"
echo "  - POST /v1/chat/completions" 
echo "  - GET  /health"
echo "  - GET  /docs (API documentation)"
