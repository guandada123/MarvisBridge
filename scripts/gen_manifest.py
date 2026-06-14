#!/usr/bin/env python3
"""生成 results/ 目录的清单文件 MANIFEST.json，包含执行概要"""
import json
import os
import sys
from datetime import datetime

if len(sys.argv) < 2:
    print("用法: python3 gen_manifest.py <claw|quant>")
    sys.exit(1)

project = sys.argv[1]
bridge_dir = os.path.expanduser("~/workbuddy_marvis_bridge")
results_dir = os.path.join(bridge_dir, project, "results")
done_dir = os.path.join(bridge_dir, project, "done")

entries = []

# 汇总 results/ 下的文件
for fname in sorted(os.listdir(results_dir)):
    fpath = os.path.join(results_dir, fname)
    if fname in (".DS_Store", "MANIFEST.json"):
        continue
    stat = os.stat(fpath)
    task_id = fname.rsplit(".", 1)[0]
    entries.append({
        "task_id": task_id,
        "output_file": fname,
        "size_bytes": stat.st_size,
        "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
    })

# 标记是否已有 done 记录
for entry in entries:
    done_file = os.path.join(done_dir, f"{entry['task_id']}.json")
    entry["archived"] = os.path.exists(done_file)

manifest = {
    "project": project,
    "generated_at": datetime.now().isoformat(),
    "total_results": len(entries),
    "results": entries,
}

manifest_path = os.path.join(results_dir, "MANIFEST.json")
with open(manifest_path, "w") as f:
    json.dump(manifest, f, indent=2, ensure_ascii=False)

print(f"✅ {project}/results/MANIFEST.json 已生成 ({len(entries)} 条)")
