"""TestApp model - represents a generated Python test application for an architecture."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TestApp:
    """Generated Python test code for an architecture."""

    arch_hash: str
    generated_at: datetime
    generator_version: str
    model_used: str
    input_tokens: int
    output_tokens: int
    files: dict[str, str] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        """Return total token usage."""
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON storage."""
        return {
            "arch_hash": self.arch_hash,
            "generated_at": self.generated_at.isoformat(),
            "generator_version": self.generator_version,
            "model_used": self.model_used,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict, files: dict[str, str] | None = None) -> "TestApp":
        """Deserialize from dictionary."""
        return cls(
            arch_hash=data["arch_hash"],
            generated_at=datetime.fromisoformat(data["generated_at"]),
            generator_version=data["generator_version"],
            model_used=data["model_used"],
            input_tokens=data["input_tokens"],
            output_tokens=data["output_tokens"],
            files=files or {},
        )

    def validate_files(self) -> tuple[bool, list[str]]:
        """Check that all required files exist."""
        required = {"conftest.py", "app.py", "test_app.py", "requirements.txt"}
        missing = required - set(self.files.keys())
        return len(missing) == 0, list(missing)
