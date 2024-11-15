#!/bin/bash
# Copyright 2024 IBM Corp.

set -e

# Kill any running port-forward processes
pkill -f "kubectl port-forward pods/code-interpreter-service" || true

# Delete the kubernetes resources
kubectl delete -f k8s/local.yaml || true

# Optionally, remove the docker images
# docker rmi localhost/bee-code-interpreter:local || true
# docker rmi localhost/bee-code-executor:local || true