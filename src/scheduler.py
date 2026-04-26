import json
import os
import re
import logging
import sys

from typing import DefaultDict
from collections import defaultdict

from kubernetes import client, config, watch
from kubernetes.client import V1Pod, V1Node

config.load_incluster_config()
v1 = client.CoreV1Api()

scheduler_name = "custom-scheduler"

logging.basicConfig(
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)],
    format="%(asctime)s %(levelname)s %(message)s"
)

logger = logging.getLogger(scheduler_name)



def available_nodes() -> list[V1Node]:
    """Return the Kubernetes nodes that are currently Ready."""
    return [
        node
        for node in v1.list_node().items
        if any(
            condition.status == "True" and condition.type == "Ready"
            for condition in node.status.conditions
        )
    ]


def bind_pod_to_node(pod_name: str, node_name: str, namespace: str = "default") -> None:
    """Bind a pending pod to the selected node."""
    target = client.V1ObjectReference(kind="Node", api_version="v1", name=node_name)
    meta = client.V1ObjectMeta(name=pod_name)
    body = client.V1Binding(target=target, metadata=meta)
    v1.create_namespaced_binding(namespace, body, _preload_content=False)


def parse_memory_quantity_to_bytes(q: str | float | int | None) -> float:
    """Convert a Kubernetes memory quantity such as 600Mi or 2Gi into bytes."""
    if q is None or q == "":
        return 0.0
    quantity = str(q)
    m = re.match(r"^([0-9.]+)([KMGTE]i)?$", quantity)
    if not m:
        raise ValueError(f"Unsupported memory quantity: {quantity}")
    num = float(m.group(1))
    suf = m.group(2) or ""
    mult = {
        "Ki": 1024,
        "Mi": 1024**2,
        "Gi": 1024**3,
        "Ti": 1024**4,
        "Ei": 1024**6,
    }.get(suf, 1)
    return num * mult


def pod_memory_request(pod: V1Pod) -> float:
    """Return the total requested memory for all containers in a pod."""
    return sum(
        (
            parse_memory_quantity_to_bytes(c.resources.requests.get("memory"))
            if c.resources and c.resources.requests
            else 0.0
        )
        for c in pod.spec.containers
    )


def get_nodes_requested_memory() -> DefaultDict[str, float]:
    """Calculate requested memory already assigned to each node in the default namespace."""
    pods = v1.list_namespaced_pod("default").items
    requested_memory_per_node = defaultdict(float)
    for pod in pods:
        if not pod.spec.node_name:
            continue
        node = pod.spec.node_name
        requested_memory_per_node[node] += pod_memory_request(pod)
    return requested_memory_per_node


def get_node_available_memory_bytes() -> float:
    """
    Returns artificial memory limit (in bytes) per node used by the scheduler.

    This does not use node.status.allocatable["memory"], because when
    Minikube runs with the Docker driver, the container runtime does not necessarily
    enforce node memory limits on some OSes. As a result, the allocatable value is not a
    reliable hard limit. Instead, we rely on an explicit limit configured via
    the NODE_MEM_LIMIT_MB environment variable.
    """
    mem_mb_str = os.environ.get("NODE_MEM_LIMIT_MB", "2048")
    mem_mb = float(mem_mb_str)
    return mem_mb * 1024 * 1024


def load_balancing_assignment(pod: V1Pod, nodes: list[V1Node]) -> V1Node | None:
    """
    Select the Ready node with the lowest requested memory that can fit the pod.

    Memory requests are used instead of live memory usage because scheduling
    decisions are normally made before a pod runs. Requests are the pod owner's
    declared capacity needs and are available during scheduling.
    """
    memory_request = pod_memory_request(pod)
    requested_memory_per_node = get_nodes_requested_memory()
    pod_name = pod.metadata.name
    logger.info(f"Assigning pod {pod_name} with memory request {memory_request}:")
    optimal_node = None
    optimal_node_requested_memory = None
    for node in nodes:
        node_name = node.metadata.name
        available_memory = get_node_available_memory_bytes()
        node_requested_memory = requested_memory_per_node[node_name]
        if node_requested_memory + memory_request > available_memory:
            continue
        if (
            optimal_node is None
            or optimal_node_requested_memory > node_requested_memory
        ):
            optimal_node, optimal_node_requested_memory = node, node_requested_memory
    if optimal_node:
        logger.info(f"Optimal node for pod {pod_name}: {optimal_node.metadata.name}")
    return optimal_node


def main():
    """Watch pending pods assigned to this scheduler and bind each pod to a node."""
    w = watch.Watch()
    for event in w.stream(v1.list_namespaced_pod, "default"):
        if (
            event["object"].status.phase == "Pending"
            and event["object"].spec.scheduler_name == scheduler_name
            and event["object"].spec.node_name is None
        ):
            try:
                pod = event["object"]
                namespace = pod.metadata.namespace or "default"
                pod_name = pod.metadata.name
                current_pod = v1.read_namespaced_pod(pod_name, namespace)
                if current_pod.spec.node_name:
                    continue
                pod = current_pod
                optimal_node = load_balancing_assignment(pod, available_nodes())
                if optimal_node is None:
                    logger.info(
                        f"No available nodes for pod {pod_name}, skipping binding.",
                    )
                    continue
                node_name = optimal_node.metadata.name
                bind_pod_to_node(pod_name, node_name, namespace)
            except client.ApiException as e:
                logger.info(json.loads(e.body)["message"])


if __name__ == "__main__":
    main()
