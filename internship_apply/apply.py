"""Load a candidate profile and resume, and build the goal string for the agent."""

import json
import sys
from pathlib import Path


def load_profile(path):
    data = json.loads(Path(path).read_text())
    resume_path = Path(data.get("resume_path", "resume.txt"))
    if not resume_path.is_absolute():
        resume_path = Path(path).parent / resume_path
    resume_text = resume_path.read_text() if resume_path.exists() else ""
    if not resume_text.strip():
        print(f"warning: no resume text found at {resume_path}; fields drawn from it will be left blank", file=sys.stderr)
    return data, resume_text


def build_goal(profile, resume_text):
    facts = {k: v for k, v in profile.items() if k not in ("resume_path",)}
    return (
        "Fill out this internship application completely and accurately using ONLY the "
        "candidate information given below. Never invent a fact that is not present in "
        "it -- if a required field has no matching information, leave it and move on "
        "rather than guessing.\n\n"
        f"CANDIDATE PROFILE (JSON):\n{json.dumps(facts, indent=2)}\n\n"
        f"RESUME TEXT:\n{resume_text[:8000]}"
    )
