"""Persistent user profile management for resume constraints and preferences."""

import json
import os
from dataclasses import dataclass, field, asdict

PROFILES_DIR = os.path.join(os.path.dirname(__file__), "user_profiles")


@dataclass
class UserProfile:
    name: str = "Default"
    skills_have: list[str] = field(default_factory=list)
    skills_missing: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    preferences: list[str] = field(default_factory=list)

    def to_prompt_section(self) -> str:
        """Format profile as a prompt section for Claude."""
        lines = ["## CRITICAL CONSTRAINTS — USER PROFILE"]
        lines.append("You MUST respect these constraints. NEVER fabricate experience or skills.")
        if self.skills_have:
            lines.append("\nSkills/experience the user HAS:")
            for s in self.skills_have:
                lines.append(f"  - {s}")
        if self.skills_missing:
            lines.append("\nSkills/experience the user does NOT have (DO NOT add these):")
            for s in self.skills_missing:
                lines.append(f"  - {s}")
        if self.constraints:
            lines.append("\nAdditional constraints:")
            for c in self.constraints:
                lines.append(f"  - {c}")
        if self.preferences:
            lines.append("\nStyle preferences:")
            for p in self.preferences:
                lines.append(f"  - {p}")
        return "\n".join(lines)


def save_profile(profile: UserProfile) -> str:
    os.makedirs(PROFILES_DIR, exist_ok=True)
    filename = profile.name.lower().replace(" ", "_") + ".json"
    filepath = os.path.join(PROFILES_DIR, filename)
    with open(filepath, "w") as f:
        json.dump(asdict(profile), f, indent=2)
    return filepath


def load_profile(name: str) -> UserProfile | None:
    filename = name.lower().replace(" ", "_") + ".json"
    filepath = os.path.join(PROFILES_DIR, filename)
    if not os.path.exists(filepath):
        return None
    with open(filepath) as f:
        data = json.load(f)
    return UserProfile(**data)


def list_profiles() -> list[str]:
    os.makedirs(PROFILES_DIR, exist_ok=True)
    profiles = []
    for f in os.listdir(PROFILES_DIR):
        if f.endswith(".json"):
            try:
                with open(os.path.join(PROFILES_DIR, f)) as fh:
                    data = json.load(fh)
                profiles.append(data.get("name", f.replace(".json", "")))
            except (json.JSONDecodeError, KeyError):
                continue
    return sorted(profiles)


def delete_profile(name: str) -> bool:
    filename = name.lower().replace(" ", "_") + ".json"
    filepath = os.path.join(PROFILES_DIR, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
        return True
    return False
