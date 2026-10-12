"""构建 EDU-ONTO 本体并序列化为 data/ontology/edu-onto.owl。

用法(在 backend/ 目录下):
    python3 scripts/build_ontology.py [输出路径]

默认输出 ../data/ontology/edu-onto.owl(RDF/XML,Protege/HermiT 兼容)。
打印类/属性/公理统计供人工核对。
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from services.ontology import BASE_IRI, VERSION, build_ontology  # noqa: E402

DEFAULT_OUTPUT = BACKEND_DIR.parent / "data" / "ontology" / "edu-onto.owl"

#: 序列化后必须在文件中出现的形式特征标记(防静默丢失)
REQUIRED_MARKERS = (
    "TransitiveProperty",
    "IrreflexiveProperty",
    "SymmetricProperty",
    "FunctionalProperty",
    "inverseOf",
    "minInclusive",
    "swrl:",
    "AllDisjoint",
    "equivalentClass",
)


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    onto = build_ontology()

    n_classes = len(list(onto.classes()))
    n_oprops = len(list(onto.object_properties()))
    n_dprops = len(list(onto.data_properties()))
    n_inds = len(list(onto.individuals()))

    output.parent.mkdir(parents=True, exist_ok=True)
    onto.save(file=str(output))
    content = output.read_text(encoding="utf-8")

    print(f"EDU-ONTO v{VERSION}  <{BASE_IRI}>")
    print(f"  classes={n_classes}  object_properties={n_oprops}  "
          f"data_properties={n_dprops}  individuals={n_inds}")
    for marker in REQUIRED_MARKERS:
        count = content.count(marker)
        status = "OK" if count > 0 else "MISSING!"
        print(f"  {marker:<22} x{count:<3} {status}")
    print(f"  -> {output}  ({len(content):,} bytes)")

    missing = [m for m in REQUIRED_MARKERS if content.count(m) == 0]
    if missing:
        print(f"FAILED: 公理标记未序列化: {missing}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
