# Turbalance Scheduler Task

## My Understanding

I treated this task as a small workload orchestration exercise. The customer problem is memory risk: if too many memory-heavy pods land on the same node, the node is more likely to experience memory pressure and Kubernetes may kill pods.

The scheduler provided in this task applies a simple memory-aware placement policy. It watches for pods that explicitly request `schedulerName: custom-scheduler`, checks the memory already requested on each ready node, and binds each pending pod to the node with the lowest requested memory that can still fit the new pod.

## What I Built

I packaged the provided scheduler so it can run inside a local Minikube cluster:

- `src/scheduler.py`: the custom scheduler source code.
- `pods/pod1.yaml`, `pods/pod2.yaml`, `pods/pod3.yaml`: the workload pods from the task.
- `Dockerfile`: builds the scheduler image.
- `requirements.txt`: installs the Kubernetes Python client.
- `manifests/rbac.yaml`: grants the scheduler permission to watch pods and nodes and create pod bindings.
- `manifests/deployment.yaml`: runs the scheduler in `kube-system` with `NODE_MEM_LIMIT_MB=2048`.
- `scripts/validate.sh`: collects the main validation output.
- `scripts/cleanup.sh`: removes the demo resources.

## Local Setup

I would start Minikube with two nodes and at least 2GB of memory per node:

```bash
minikube start --nodes=2 --memory=2200mb
```

The task notes that node capacity may not be reported correctly depending on the Minikube driver. For that reason, I use the required scheduler environment variable:

```text
NODE_MEM_LIMIT_MB=2048
```

This keeps the scheduler's decision model aligned with the task: each node is treated as having 2GB of schedulable memory.

## Build And Deploy

From this directory:

```bash
eval "$(minikube docker-env)"
docker build -t custom-scheduler:validated .
kubectl apply -k manifests
kubectl -n kube-system rollout status deploy/custom-scheduler
```

Then I would schedule the pods in the required order:

```bash
kubectl apply -f pods/pod1.yaml
kubectl apply -f pods/pod2.yaml
kubectl apply -f pods/pod3.yaml
```

## Validation

I would validate the result with:

```bash
./scripts/validate.sh
```

The key checks are:

```bash
kubectl -n kube-system logs deploy/custom-scheduler --tail=50
kubectl get pods -o wide
```

The logs show that the custom scheduler handled each pod. The `kubectl get pods -o wide` output shows which node each pod was bound to.

## My Validation Result

I validated the solution on a local two-node Minikube cluster:

```text
NAME           STATUS   ROLES           VERSION
minikube       Ready    control-plane   v1.35.1
minikube-m02   Ready    <none>          v1.35.1
```

After applying `pod1`, `pod2`, and `pod3` in order, I observed:

```text
NAME   READY   STATUS    NODE
pod1   1/1     Running   minikube
pod2   1/1     Running   minikube-m02
pod3   1/1     Running   minikube
```

The scheduler logs showed:

```text
Assigning pod pod1 with memory request 629145600.0
Optimal node for pod pod1: minikube
Assigning pod pod2 with memory request 838860800.0
Optimal node for pod pod2: minikube-m02
Assigning pod pod3 with memory request 629145600.0
Optimal node for pod pod3: minikube
```

## Expected Placement

The pods request the following memory:

| Pod | Memory request |
| --- | ---: |
| `pod1` | `600Mi` |
| `pod2` | `800Mi` |
| `pod3` | `600Mi` |

With two 2GB nodes, the expected placement is:

| Step | Decision | Reason |
| --- | --- | --- |
| `pod1` | First available node | Both nodes are empty, so either node is valid. |
| `pod2` | Other node | The other node has lower requested memory. |
| `pod3` | Same node as `pod1` | That node has `600Mi` requested, while the `pod2` node has `800Mi`. |

The final requested-memory distribution should be approximately:

```text
node A: pod1 600Mi + pod3 600Mi = 1200Mi
node B: pod2 800Mi
```

The exact node names may differ by environment. The important part is the memory-balancing behavior.

## How The Scheduler Works

The scheduler follows this flow:

```text
Watch pending pods in the default namespace
Ignore pods not assigned to custom-scheduler
Read the pod's memory request
List ready nodes
Calculate memory already requested on each node
Skip nodes where the new pod would exceed 2048Mi
Choose the node with the lowest requested memory
Bind the pod to that node
```

This is a least-requested-memory strategy with a fit check. It balances declared memory requests, not live memory usage.

## Assumptions

I made these assumptions intentionally to keep the solution aligned with the 1-2 hour task:

- The scheduler only watches the `default` namespace.
- Memory is the only resource considered.
- The scheduler uses memory requests, not memory limits or real-time usage.
- Each node is treated as having 2048MB available through `NODE_MEM_LIMIT_MB`.
- The provided pods are applied in the order requested by the task.

## Limitations And Production Considerations

This implementation is suitable for demonstrating the scheduling policy, but I would not call it production-ready. Before using this with customers, I would consider:

- support for all relevant namespaces
- better handling of malformed or missing memory requests
- explicit tie-breaking behavior
- support for taints, tolerations, affinity, topology, and priority
- stronger logging around why a pod was or was not scheduled
- metrics for scheduler decisions and rejected placements
- tests around memory parsing and node selection
- integration with the Kubernetes scheduler framework for a production-grade plugin model

## Cleanup

```bash
./scripts/cleanup.sh
```

## References

- Minikube `start` flags: https://minikube.sigs.k8s.io/docs/commands/start/
- Kubernetes Python client package: https://github.com/kubernetes-client/python
