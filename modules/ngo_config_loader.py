"""
NGO Configuration Loader

Loads the retained NGO CSV configuration.
"""

from pathlib import Path
from typing import List, Dict
import yaml


def load_ngo_config(config_path: Path = None) -> List[Dict]:
    """
    Load NGO configuration from CSV.

    Args:
        config_path: Path to config file. If None, uses config/ngo_config.csv.

    Returns:
        List of NGO dicts with keys: name, aliases, url, depth_limit, scrape_priority
    """

    if config_path is None:
        csv_path = Path("config/ngo_config.csv")

        if csv_path.exists():
            config_path = csv_path
        else:
            raise FileNotFoundError("No NGO config found at config/ngo_config.csv")

    config_path = Path(config_path)

    if config_path.suffix == '.yaml' or config_path.suffix == '.yml':
        return _load_yaml(config_path)
    elif config_path.suffix == '.csv':
        return _load_csv(config_path)
    else:
        raise ValueError(f"Unsupported config format: {config_path.suffix}")


def _load_yaml(yaml_path: Path) -> List[Dict]:
    """Load NGO config from YAML file"""

    with open(yaml_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    ngos = config.get('ngos', [])

    # Standardize format
    result = []
    for ngo in ngos:
        result.append({
            'name': ngo['name'],
            'aliases': ngo.get('aliases', []),
            'url': ngo.get('url', ''),
            'depth_limit': ngo.get('depth_limit', 5),
            'scrape_priority': ngo.get('scrape_priority', 1)
        })

    return result


def _load_csv(csv_path: Path) -> List[Dict]:
    """Load NGO config from CSV file (fallback)"""

    import csv

    ngos = []

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            ngo_name = row.get('ngo_name', '').strip()
            if not ngo_name:
                continue

            aliases_str = row.get('aliases', '').strip()
            aliases = [a.strip() for a in aliases_str.split(';') if a.strip()] if aliases_str else []

            ngos.append({
                'name': ngo_name,
                'aliases': aliases,
                'url': row.get('url', '').strip(),
                'depth_limit': int(row.get('depth_limit', 5)),
                'scrape_priority': int(row.get('scrape_priority', 1))
            })

    return ngos


def get_ngo_names(config_path: Path = None) -> List[str]:
    """Get list of NGO names only"""
    ngos = load_ngo_config(config_path)
    return [ngo['name'] for ngo in ngos]


def get_ngo_with_variants(config_path: Path = None) -> Dict[str, List[str]]:
    """
    Get NGO names with all their variants (name + aliases)

    Returns:
        Dict mapping canonical name -> list of all variants
    """
    ngos = load_ngo_config(config_path)

    variants = {}
    for ngo in ngos:
        canonical = ngo['name']
        all_variants = [canonical] + ngo['aliases']
        variants[canonical] = all_variants

    return variants


def get_variant_to_canonical_mapping(config_path: Path = None) -> Dict[str, str]:
    """
    Get mapping from any variant (name or alias) to canonical name

    Returns:
        Dict mapping variant -> canonical name
    """
    ngos = load_ngo_config(config_path)

    mapping = {}
    for ngo in ngos:
        canonical = ngo['name']
        all_variants = [canonical] + ngo['aliases']

        for variant in all_variants:
            mapping[variant.lower()] = canonical

    return mapping


# Example usage
if __name__ == "__main__":
    # Load config
    ngos = load_ngo_config()
    print(f"Loaded {len(ngos)} NGOs")

    # Test UTF-8 handling
    for ngo in ngos:
        print(f"\n{ngo['name']}")
        if ngo['aliases']:
            print(f"  Aliases: {', '.join(ngo['aliases'])}")
