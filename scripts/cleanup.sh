#!/usr/bin/env bash
set -euo pipefail

kubectl delete -f pods/pod3.yaml --ignore-not-found
kubectl delete -f pods/pod2.yaml --ignore-not-found
kubectl delete -f pods/pod1.yaml --ignore-not-found
kubectl delete -k manifests --ignore-not-found
