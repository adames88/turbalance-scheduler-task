# Implementation Notes

## Existing Files I Kept

### `pods/pod1.yaml`, `pods/pod2.yaml`, `pods/pod3.yaml`

I kept the pod definitions from the task unchanged. They already include `schedulerName: custom-scheduler`, which is the key field that tells Kubernetes to leave these pods for the custom scheduler instead of the default scheduler.

Keeping these files unchanged also makes the validation easier to reason about, because the only behavior being tested is the scheduler placement logic.

### `TASK.md`

I included the original task brief in the repository so the reviewer can see the exact assignment context next to the solution.

## Existing File I Updated

### `src/scheduler.py`

I kept the original scheduling algorithm, but made a few small changes while validating the scheduler in Minikube.

#### Added docstrings

I added short docstrings to the main functions so the code is easier to review:

- `available_nodes`
- `bind_pod_to_node`
- `parse_memory_quantity_to_bytes`
- `pod_memory_request`
- `get_nodes_requested_memory`
- `load_balancing_assignment`
- `main`

The goal was not to over-document the code, but to make the intent clear for an interview review.

#### Made memory parsing safer

The original parser assumed every memory value was a valid string. I changed it so missing or empty memory values return `0.0`, and unsupported formats raise a clear `ValueError`.

This matters because a real cluster can contain pods with incomplete resource requests. In production, I would likely enforce memory requests through policy, but for this task the safer fallback keeps the demo scheduler from failing on a missing value.

#### Used the pod namespace during binding

The original bind helper defaulted to the `default` namespace. I kept `default` as the fallback, but now pass the pod's actual namespace into the bind call.

This keeps the current task behavior the same while making the function less brittle if the scheduler is later extended beyond the default namespace.

#### Re-read the pod before binding

During live validation, the Kubernetes watch stream could surface more than one event for the same pod. I added a fresh API read before scheduling and skip the pod if it already has `spec.nodeName`.

This prevents repeated bind attempts and keeps the scheduler behavior easier to understand from the logs.

## New Files I Added

### `Dockerfile`

I added a Dockerfile so the scheduler can run inside the Kubernetes cluster using in-cluster configuration.

The scheduler calls `config.load_incluster_config()`, so running it as a local Python process would not match the intended runtime environment. Packaging it as a container is the cleanest way to deploy and validate it in Minikube.

### `requirements.txt`

I added this file to pin the Python Kubernetes client dependency used by the scheduler image.

This keeps the container build repeatable and avoids relying on packages installed on my laptop.

### `manifests/rbac.yaml`

I added RBAC resources for the scheduler:

- `ServiceAccount`
- `ClusterRole`
- `ClusterRoleBinding`

The scheduler needs permission to list and watch pods, list and watch nodes, and create pod bindings. I included both `bindings` and `pods/binding` create permissions because the live Minikube validation showed that `create_namespaced_binding` requires access to `bindings` in the target namespace.

### `manifests/deployment.yaml`

I added a Kubernetes Deployment to run the scheduler inside the `kube-system` namespace.

The Deployment sets:

- `serviceAccountName: custom-scheduler`
- `NODE_MEM_LIMIT_MB=2048`
- `imagePullPolicy: IfNotPresent`

The memory limit environment variable is important because the task specifically asks the scheduler to account for 2GB per node, even if the local Minikube driver reports capacity differently.

### `manifests/kustomization.yaml`

I added a small Kustomize file so all scheduler manifests can be deployed with one command:

```bash
kubectl apply -k manifests
```

This keeps the deployment steps simple and reduces the chance of applying files in the wrong order.

### `scripts/validate.sh`

I added a validation script to collect the main evidence after deployment:

- node status
- scheduler deployment status
- scheduler logs
- pod placement

This gives the reviewer a simple way to reproduce the checks I used.

### `scripts/cleanup.sh`

I added a cleanup script to remove the demo pods and scheduler resources.

This makes it easy to rerun the task from a clean state.

## Validation Summary

I validated the final solution on a two-node Minikube cluster. The observed placement was:

```text
pod1 -> minikube
pod2 -> minikube-m02
pod3 -> minikube
```

This matches the intended least-requested-memory behavior:

- `pod1` starts on an empty node.
- `pod2` goes to the other node because it has less requested memory.
- `pod3` returns to the `pod1` node because that node has `600Mi` requested while the `pod2` node has `800Mi`.
