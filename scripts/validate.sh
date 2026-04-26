#!/usr/bin/env bash
set -euo pipefail

kubectl get nodes
kubectl -n kube-system get deploy custom-scheduler
kubectl -n kube-system logs deploy/custom-scheduler --tail=50
kubectl get pods -o wide
