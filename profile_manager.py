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
    experience_facts: list[str] = field(default_factory=list)
    title_rules: list[str] = field(default_factory=list)

    def to_prompt_section(self) -> str:
        """Format profile as a prompt section for the LLM."""
        lines = ["## CRITICAL CONSTRAINTS — USER PROFILE (GROUND TRUTH FACT BASE)"]
        lines.append("You MUST respect these constraints. NEVER fabricate experience, metrics, or skills.")
        lines.append("Every claim in every bullet must be traceable to this fact base.")
        if self.experience_facts:
            lines.append("\n### Experience Facts (what the user actually did):")
            for s in self.experience_facts:
                lines.append(f"  - {s}")
        if self.skills_have:
            lines.append("\n### Known Tools & Skills (ONLY these may appear on the resume):")
            for s in self.skills_have:
                lines.append(f"  - {s}")
        if self.skills_missing:
            lines.append("\n### Tools NOT Used — BLOCKLIST (NEVER add these to the resume):")
            for s in self.skills_missing:
                lines.append(f"  - {s}")
        if self.title_rules:
            lines.append("\n### Title Adjustment Rules:")
            for t in self.title_rules:
                lines.append(f"  - {t}")
        if self.constraints:
            lines.append("\n### Additional Constraints:")
            for c in self.constraints:
                lines.append(f"  - {c}")
        if self.preferences:
            lines.append("\n### Style Preferences:")
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
    # Filter to only known fields for backward compatibility
    known_fields = {f.name for f in UserProfile.__dataclass_fields__.values()}
    filtered = {k: v for k, v in data.items() if k in known_fields}
    return UserProfile(**filtered)


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
