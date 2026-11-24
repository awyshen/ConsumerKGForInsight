from pathlib import Path
import yaml

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "config" / "ontology.yaml"

def load_ontology(path=DEFAULT_PATH):
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    assert data["entity_types"] and data["relations"]
    return data

def validate_relation(ontology, source_type, relation, target_type):
    rule = ontology["relations"].get(relation)
    if not rule:
        return False
    return any(source_type in r["from"] and target_type in r["to"] for r in rule.get("variants", [rule]))
