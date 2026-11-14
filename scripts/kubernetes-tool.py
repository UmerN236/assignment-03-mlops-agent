#!/usr/bin/env python3
"""Call one structured read-only tool; no admin credential fallback."""

import argparse
import json

from mlops_agent.config import load_settings
from mlops_agent.kubernetes_tools import KubernetesTools

parser = argparse.ArgumentParser()
parser.add_argument("tool", choices=["workloads", "services", "diagnostics", "logs", "health"])
parser.add_argument("--arguments", default="{}")
args = parser.parse_args()
settings = load_settings()
tools = KubernetesTools(settings.kubernetes_readonly_kubeconfig, settings.tool_timeout_seconds)
result = tools.registry.call("kubernetes_" + args.tool, json.loads(args.arguments))
print(result.model_dump_json(indent=2))
raise SystemExit(0 if result.status == "ok" else 1)
