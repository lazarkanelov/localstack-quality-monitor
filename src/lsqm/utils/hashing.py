"""Content hash computation for architecture deduplication."""

import hashlib
import re


def normalize_terraform(content: str) -> str:
    """Normalize Terraform content for consistent hashing.

    - Remove comments (# and // style)
    - Remove blank lines
    - Normalize whitespace
    """
    lines = []
    for line in content.split("\n"):
        # Remove inline comments
        line = re.sub(r"#.*$", "", line)
        line = re.sub(r"//.*$", "", line)

        # Skip empty lines
        stripped = line.strip()
        if not stripped:
            continue

        # Normalize whitespace (collapse multiple spaces)
        normalized = " ".join(stripped.split())
        lines.append(normalized)

    return "\n".join(lines)


def compute_architecture_hash(tf_files: dict[str, str]) -> str:
    """Compute SHA-256 hash of normalized Terraform content.

    Args:
        tf_files: Dictionary mapping filename to content

    Returns:
        16-character hexadecimal hash
    """
    normalized_parts = []

    # Sort files alphabetically for deterministic ordering
    for filename in sorted(tf_files.keys()):
        content = normalize_terraform(tf_files[filename])
        normalized_parts.append(f"# {filename}\n{content}")

    combined = "\n".join(normalized_parts)
    full_hash = hashlib.sha256(combined.encode()).hexdigest()

    # Return first 16 characters (64 bits - sufficient for ~10K architectures)
    return full_hash[:16]


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 hash of arbitrary content.

    Args:
        content: String content to hash

    Returns:
        16-character hexadecimal hash
    """
    full_hash = hashlib.sha256(content.encode()).hexdigest()
    return full_hash[:16]


def validate_hash(hash_value: str) -> bool:
    """Validate that a hash is properly formatted.

    Args:
        hash_value: Hash string to validate

    Returns:
        True if hash is 16 hexadecimal characters
    """
    if len(hash_value) != 16:
        return False
    try:
        int(hash_value, 16)
        return True
    except ValueError:
        return False
