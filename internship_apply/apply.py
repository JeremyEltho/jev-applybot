"""Fill one internship application from a resume and a Q&A profile, then stop before submit.

    uv run --env-file .env python -m internship_apply.apply \
        --url "https://jobs.example.com/postings/1234" \
        --profile internship_apply/profile.json

The agent fills every field it can map from the resume and profile. It never clicks a
final Submit / Apply / Send Application control on its own -- that action always needs
a human to look at the filled form and press it, or re-run with --confirm-submit after
reviewing on screen. Automating the actual submission is left out on purpose: most job
boards' terms of service prohibit automated applications, and a submitted application
is not reversible the way a filled-in field is.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from jev_ultrafast import Agent

# Labels that mark a point of no return. Matched case-insensitively against the button
# text the model is about to click. Extend this list before trusting a new site.
SUBMIT_PATTERN = re.compile(
    r"\b(submit|apply now|send application|finish application|complete application|"
    r"submit application|apply\b)\b",
    re.IGNORECASE,
)


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
        f"RESUME TEXT:\n{resume_text[:8000]}\n\n"
        "Do not click Submit, Apply, Send Application, Finish Application, or any other "
        "final-submission control. Once every field you can fill is filled, the task is "
        "complete even though the form has not been submitted."
    )


def action_label(page, action_id):
    for action in page["actions"]:
        if action["id"] == action_id:
            return action["label"]
    return ""


def run(url, profile_path, *, confirm_submit=False, record_dir=None):
    profile, resume_text = load_profile(profile_path)
    goal = build_goal(profile, resume_text)
    blanks = []

    with Agent(url, goal, record_dir=record_dir) as agent:
        while agent.state["status"] not in {"done", "blocked"}:
            agent.command("predict")
            decision = agent.state["decision"]
            page = agent.state["page"]

            if decision["choice"] == "DONE":
                agent.command("act", {"fingerprint": page["fingerprint"]})
                break

            if decision["operation"] == "CLICK":
                label = action_label(page, decision["choice"])
                if SUBMIT_PATTERN.search(label) and not confirm_submit:
                    print(f"\nStopped before clicking a submit control: \"{label}\"")
                    print("Review the filled form in the browser, then either:")
                    print("  - click it yourself, or")
                    print("  - re-run this command with --confirm-submit once you've checked it.")
                    agent.state["status"] = "blocked"
                    break

            snap = agent.command("act", {"fingerprint": page["fingerprint"]})
            step = snap["history"][-1] if snap["history"] else None
            if step and step["kind"] == "fill" and step["text"] is None:
                blanks.append(step["action"])
            if step:
                print(f"{step['elapsed_ms']:>6} ms  {step['kind']:<7} {step['action']}")

        final_url = agent.state["page"]["url"]

    print(f"\nStatus: {agent.state['status']}")
    print(f"Final page: {final_url}")
    if blanks:
        print("\nFields the agent could not fill from your resume/profile (fill these yourself):")
        for b in blanks:
            print(f"  - {b}")
    return agent.state["status"]
