# Turbalance Scheduler Task

## My Understanding

The customer problem is memory risk: if too many memory-heavy pods land on the same node, the node is more likely to experience memory pressure and Kubernetes may kill pods.

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

### Evidence From Logs

The useful evidence from the run is the link between the pod request, the scheduler decision, and the final pod placement.

| Pod | Request confirmed by pod spec | Scheduler selected | Final node | Restarts |
| --- | ---: | --- | --- | ---: |
| `pod1` | `600Mi` | `minikube` | `minikube` | `0` |
| `pod2` | `800Mi` | `minikube-m02` | `minikube-m02` | `0` |
| `pod3` | `600Mi` | `minikube` | `minikube` | `0` |

This is the clearest validation output because it connects the scheduler's input to its decision and then to the actual Kubernetes placement.

### Log Analysis And Conclusion

The scheduler logs confirm that all three pods were handled by `custom-scheduler`. The memory values are shown in bytes:

| Pod | Log value | Original request |
| --- | ---: | ---: |
| `pod1` | `629145600.0` | `600Mi` |
| `pod2` | `838860800.0` | `800Mi` |
| `pod3` | `629145600.0` | `600Mi` |

The observed placement was:

```text
pod1 -> minikube
pod2 -> minikube-m02
pod3 -> minikube
```

My conclusion is that the scheduler behaved as intended. `pod1` was placed on the first available empty node. `pod2` was placed on the other node because that node had less requested memory at the time. `pod3` was then placed back on the `pod1` node because that node had `600Mi` requested, while the `pod2` node had `800Mi` requested.

This result shows the scheduler is balancing declared memory requests, not live memory usage. That distinction matters because Kubernetes scheduling decisions are made before the pod is running. Kubernetes uses resource requests to decide whether a pod fits on a node, while memory limits are enforced later by the kubelet and container runtime.

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

## Algorithmic Analysis

The algorithm used here is a simple least-requested-memory strategy:

```text
Filter out nodes where requested memory + new pod request > node memory limit
Score the remaining nodes by current requested memory
Choose the node with the lowest requested memory
Bind the pod to that node
```

This mirrors the shape of Kubernetes scheduling at a small scale. The default Kubernetes scheduler uses a filtering step to find feasible nodes and a scoring step to rank the feasible nodes. In this task, the filter is the memory fit check and the score is based only on already-requested memory.

### Why This Strategy Fits The Task

This strategy fits the customer goal because the customer wants to reduce the chance that memory-heavy pods concentrate on one node. By spreading requested memory across nodes, the scheduler reduces the chance of creating an obvious memory hotspot.

The tradeoff is that it optimises safety and balance more than density. It may leave more fragmented free capacity than a packing strategy, but it gives a clearer reliability story for memory-sensitive workloads.

### Other Deployment Strategies And Tradeoffs

| Strategy | How it works | Benefit | Tradeoff |
| --- | --- | --- | --- |
| Least requested memory | Place the pod on the node with the lowest current requested memory. | Reduces memory hotspots and is easy to explain. | Can leave capacity fragmented across nodes. |
| Bin packing / most allocated | Place the pod on the node that is already most used but still has enough space. | Improves density and can reduce infrastructure cost. | Increases risk if workloads spike above requests. |
| Round robin | Alternate placements across nodes. | Simple and predictable. | Ignores pod size, so one large pod can still create imbalance. |
| Random placement | Pick any node that can fit the pod. | Very simple and can spread load over many pods. | Individual placements are hard to justify and can be inefficient. |
| Constraint-based placement | Use labels, node selectors, affinity, anti-affinity, taints, tolerations, or topology spread constraints. | Good when workloads have location, isolation, or topology requirements. | More policy complexity and more ways for pods to remain pending. |
| Metrics-aware placement | Use live memory metrics rather than only requests. | Can react to actual runtime behaviour. | More moving parts, possible stale metrics, and less deterministic scheduling. |

For this task, I would keep the least-requested-memory approach. It directly answers the requested memory-balancing scenario, is deterministic, and maps clearly to the observed result.

For a production customer environment, I would not stop here. I would combine requested-memory scheduling with stronger policy controls, observability, and eventually real workload data. Memory requests are the right scheduling input, but they are only as good as the workload sizing behind them.

## Assumptions

I made these assumptions intentionally to keep the solution simple:

- The scheduler only watches the `default` namespace.
- Memory is the only resource considered.
- The scheduler uses memory requests, not memory limits or real-time usage.
- Each node is treated as having 2048MB available through `NODE_MEM_LIMIT_MB`.
- The provided pods are applied in the order requested by the task.

## Limitations And Production Considerations

This implementation is suitable for demonstrating the scheduling policy, but I would not call it production-ready. Before using this with customers, I would consider:

- support for all relevant namespaces
- better handling of malformed or missing memory requests
- explicit tie-breaking behaviour
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
- Kubernetes scheduler overview: https://kubernetes.io/docs/concepts/scheduling-eviction/kube-scheduler/
- Kubernetes resource requests and limits: https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/
- Kubernetes assigning pods to nodes: https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/
- Kubernetes node-pressure eviction: https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/
