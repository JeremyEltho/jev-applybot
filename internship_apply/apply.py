"""Fill one internship application from a resume and a Q&A profile, then stop before submit.

    uv run --env-file .env python -m internship_apply.apply \
        --url "https://company.wd5.myworkdayjobs.com/en-US/Careers/job/..." \
        --profile internship_apply/profile.json

The agent fills every field it can map from the resume and profile. It never clicks a
final Submit / Send Application control on its own -- that action always needs a human
to look at the filled form and press it, or a re-run with --confirm-submit after
reviewing on screen. The browser tab is left open when the run stops so you can do that.

Two things the engine hides from the model are handled here in plain code: a sign-in
wall (a visible password field) pauses the run for you to log in yourself, and a resume
file input gets the file from your profile attached to it directly.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import jev_ultrafast.agent as engine
from jev_ultrafast import Agent
from jev_ultrafast.browser import StalePage

from .browser_extras import file_inputs, set_file_input, sign_in_wall, wants_resume, workday_step
from .sites import detect_step, site_for, submit_pattern

# Kept for callers/tests that import it; runs use submit_pattern(site, extra) instead.
SUBMIT_PATTERN = submit_pattern()

MAX_UPLOADS = 3


def load_profile(path):
    path = Path(path)
    data = json.loads(path.read_text())
    resume_path = Path(data.get("resume_path", "resume.txt"))
    if not resume_path.is_absolute():
        resume_path = path.parent / resume_path
    resume_text = resume_path.read_text() if resume_path.exists() else ""
    if not resume_text.strip():
        print(f"warning: no resume text at {resume_path}; fields drawn from it will be left blank", file=sys.stderr)
    resume_file = None
    if data.get("resume_file"):
        candidate = Path(data["resume_file"])
        if not candidate.is_absolute():
            candidate = path.parent / candidate
        if candidate.is_file():
            resume_file = candidate
        else:
            print(f"warning: resume_file {candidate} not found; uploads will be skipped", file=sys.stderr)
    return data, resume_text, resume_file


def build_goal(profile, resume_text, site=None):
    facts = {k: v for k, v in profile.items() if k not in ("resume_path", "resume_file")}
    disclosures = facts.get("disclosures") or {}
    facts["disclosures"] = {k: v for k, v in disclosures.items() if not k.startswith("_")}
    hints = list((site or {}).get("hints", []))
    lines = [
        "Fill out this internship application completely and accurately using ONLY the "
        "candidate information given below. Never invent a fact that is not present in "
        "it -- if a required field has no matching information, leave it and move on "
        "rather than guessing.",
        "",
        f"CANDIDATE PROFILE (JSON):\n{json.dumps(facts, indent=2)}",
        "",
        f"RESUME TEXT:\n{resume_text[:8000]}",
        "",
        "For voluntary self-identification questions (gender, race or ethnicity, Hispanic or "
        "Latino, veteran status, disability status) use `disclosures`. When the value there is "
        "blank, choose the option that declines to answer (for example 'I do not wish to answer' "
        "or 'Decline to self-identify'); never guess these.",
        "Use `education` and `experience` entries for structured education and work-history "
        "sections, one entry per section, in the order given.",
        "If a resume file has already been attached to the page, do not try to attach it again.",
    ]
    if hints:
        lines += ["", "SITE NOTES:"] + [f"- {h}" for h in hints]
    lines += [
        "",
        "Do not click Submit, Send Application, Finish Application, or any other final-submission "
        "control. Once every field you can fill is filled and the review step is reached, the task "
        "is complete even though the form has not been submitted.",
    ]
    return "\n".join(lines)


def action_label(page, action_id):
    for action in page["actions"]:
        if action["id"] == action_id:
            return action["label"]
    return ""


def top_probabilities(probabilities, n=3):
    items = sorted(probabilities.items(), key=lambda kv: kv[1], reverse=True)[:n]
    return ", ".join(f"{k} {v:.2f}" for k, v in items)


class Applier:
    """One application run. Owns the loop, the guardrails, and the trace."""

    def __init__(self, url, profile_path, *, confirm_submit=False, record_dir=None, pause_below=0.0,
                 max_steps=200, block_labels=(), interactive=True):
        self.url = url
        self.confirm_submit = confirm_submit
        self.pause_below = pause_below
        self.interactive = interactive
        self.site = site_for(url)
        self.guard = submit_pattern(self.site, block_labels)
        self.profile, resume_text, self.resume_file = load_profile(profile_path)
        self.goal = build_goal(self.profile, resume_text, self.site)
        self.events = []
        self.blanks = []
        self.uploads = []
        self.step = None
        self.stopped_at = None
        engine.MAX_STEPS = max_steps
        self.agent = Agent(url, self.goal, record_dir=record_dir)

    # -- helpers ---------------------------------------------------------------------------

    def log(self, kind, **data):
        self.events.append({"t": round(time.time(), 3), "kind": kind, **data})

    def reobserve(self):
        agent = self.agent
        agent.state["decision"] = None
        agent.state["status"] = "ready"
        agent.state["page"] = agent.browser.observe(screenshot=agent.screenshots)
        return agent.state["page"]

    def current_step(self, page):
        return workday_step(self.agent.browser.evaluate) or detect_step(page.get("text", ""), self.site)

    def report_step(self, page):
        step = self.current_step(page)
        if step and step != self.step:
            self.step = step
            print(f"\n== {self.site['name']}: {step} ==")
            self.log("step", step=step)

    def ask(self, prompt):
        if not self.interactive:
            return ""
        try:
            return input(prompt).strip().lower()
        except EOFError:
            return ""

    # -- guardrails ------------------------------------------------------------------------

    def handle_sign_in(self, page):
        """A visible password field means the person must sign in. Credentials never pass through here."""
        if not sign_in_wall(self.agent.browser.evaluate):
            return False
        self.log("sign_in_wall", url=page["url"])
        print(f"\nA sign-in form is showing at {page['url']}")
        print(f"Switch to the Chrome tab titled \"{page.get('title', '')}\", sign in or create your account there,")
        if not self.interactive:
            print("then re-run this command. (Non-interactive mode: stopping here.)")
            self.stopped_at = "sign_in"
            return True
        self.ask("then press Enter here to continue... ")
        self.reobserve()
        return True

    def handle_upload(self, page):
        """Attach the resume to an empty file input. Once per step, capped overall."""
        if not self.resume_file or len(self.uploads) >= MAX_UPLOADS:
            return False
        target = wants_resume(file_inputs(self.agent.browser.evaluate))
        if not target:
            return False
        key = f"{page['url'].split('?')[0]}|{self.current_step(page) or ''}"
        if any(u["key"] == key for u in self.uploads):
            return False
        try:
            attached = set_file_input(self.agent.browser.call, self.resume_file, target["index"])
        except Exception as exc:  # the page can keep going without the file
            print(f"warning: could not attach resume: {exc}", file=sys.stderr)
            self.log("upload_failed", error=str(exc))
            return False
        self.uploads.append({"key": key, "input": target.get("name", ""), "file": attached})
        self.log("upload", input=target.get("name", ""), file=attached)
        print(f"   attached resume to file input \"{target.get('name') or target['index']}\"")
        time.sleep(0.5)  # let the site react to the file before the next observation
        self.reobserve()
        return True

    def guard_submit(self, decision, page):
        if decision["operation"] != "CLICK":
            return False
        label = action_label(page, decision["choice"])
        if not self.guard.match(label) or self.confirm_submit:
            return False
        print(f"\nStopped before clicking a submit control: \"{label}\"")
        print("The browser tab is still open. Review the filled form there, then either:")
        print("  - click that button yourself, or")
        print("  - re-run this command with --confirm-submit once you've checked it.")
        self.log("submit_guard", label=label)
        self.stopped_at = "submit_guard"
        return True

    def gate_confidence(self, decision, page):
        """Pause on low-confidence decisions when --pause-below is set."""
        if not self.pause_below:
            return False
        confidence = min(decision["confidence"], decision.get("target_confidence") or 1.0)
        if confidence >= self.pause_below:
            return False
        targeted = decision["operation"] in {"CLICK", "TYPE_TEXT", "SELECT"}
        label = action_label(page, decision["choice"]) if targeted else decision["operation"]
        print(f"\nLow confidence ({confidence:.2f}) on: {decision['operation']} -> \"{label}\"")
        print(f"   operation: {top_probabilities(decision['operation_probabilities'])}")
        if decision.get("target_probabilities"):
            print(f"   target:    {top_probabilities(decision['target_probabilities'])}")
        answer = self.ask("[Enter] do it · c continue without pausing · q quit: ")
        if answer == "q":
            self.stopped_at = "user_quit"
            return True
        if answer == "c":
            self.pause_below = 0.0
        return False

    # -- the loop --------------------------------------------------------------------------

    def run(self):
        agent = self.agent
        while agent.state["status"] not in {"done", "blocked"} and not self.stopped_at:
            page = agent.state["page"]
            self.report_step(page)
            if self.handle_sign_in(page) or self.handle_upload(page):
                continue
            try:
                agent.command("predict")
            except ValueError as exc:  # model-call budget
                print(f"\n{exc}")
                self.stopped_at = "budget"
                break
            decision = agent.state["decision"]
            page = agent.state["page"]
            if decision["choice"] == "DONE":
                agent.command("act", {"fingerprint": page["fingerprint"]})
                break
            if self.guard_submit(decision, page) or self.gate_confidence(decision, page):
                break
            try:
                snap = agent.command("act", {"fingerprint": page["fingerprint"]})
            except StalePage:
                self.reobserve()
                continue
            except ValueError as exc:  # action budget
                print(f"\n{exc}")
                self.stopped_at = "budget"
                break
            step = snap["history"][-1] if snap["history"] else None
            if step:
                if step["kind"] == "fill" and step["text"] is None:
                    self.blanks.append(step["action"])
                self.log("action", kind=step["kind"], label=step["action"], text=step["text"],
                         probability=step["probability"], confidence=step["confidence"])
                print(f"{step['elapsed_ms']:>6} ms  {step['kind']:<7} {step['action']}")
        return agent.state["status"]

    def summary(self):
        agent = self.agent
        print(f"\nStatus: {self.stopped_at or agent.state['status']}")
        print(f"Page: {agent.state['page']['url']}")
        if self.uploads:
            print(f"Resume attached {len(self.uploads)} time(s).")
        if self.blanks:
            print("\nFields the agent could not fill from your resume/profile (fill these yourself):")
            for b in self.blanks:
                print(f"  - {b}")

    def trace(self):
        snapshot = self.agent.snapshot()
        snapshot["page"] = {k: v for k, v in snapshot["page"].items() if k != "screenshot"}
        return {
            "url": self.url,
            "site": self.site["name"],
            "stopped_at": self.stopped_at,
            "status": self.agent.state["status"],
            "blanks": self.blanks,
            "uploads": self.uploads,
            "events": self.events,
            "agent": snapshot,
        }

    def finish(self, *, close, trace_path=None):
        if trace_path:
            Path(trace_path).write_text(json.dumps(self.trace(), indent=2, default=str))
            print(f"Trace written to {trace_path}")
        if close:
            self.agent.close()
        else:
            print("Browser tab left open for review.")


def run(url, profile_path, *, confirm_submit=False, record_dir=None, pause_below=0.0, max_steps=200,
        block_labels=(), interactive=True, close=False, trace_path=None):
    applier = Applier(url, profile_path, confirm_submit=confirm_submit, record_dir=record_dir,
                      pause_below=pause_below, max_steps=max_steps, block_labels=block_labels,
                      interactive=interactive)
    try:
        applier.run()
        applier.summary()
    finally:
        applier.finish(close=close, trace_path=trace_path)
    return applier.stopped_at or applier.agent.state["status"]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", required=True, help="The job posting / application URL")
    parser.add_argument("--profile", required=True, help="Path to a profile JSON (see profile.example.json)")
    parser.add_argument("--confirm-submit", action="store_true", help="Allow clicking the final submit control")
    parser.add_argument("--block-label", action="append", default=[], metavar="TEXT",
                        help="Extra button label to treat as final submission (repeatable)")
    parser.add_argument("--pause-below", type=float, default=0.0, metavar="P",
                        help="Pause for approval when the model's confidence is below P (0-1)")
    parser.add_argument("--max-steps", type=int, default=200, help="Action budget for the run (default 200)")
    parser.add_argument("--record-dir", default=None, help="Save a screenshot per step here")
    parser.add_argument("--trace", default=None, metavar="FILE", help="Write a JSON trace of the run here")
    parser.add_argument("--close", action="store_true", help="Close the browser tab when the run stops")
    parser.add_argument("--no-input", action="store_true", help="Never prompt; stop instead of pausing")
    args = parser.parse_args()
    run(args.url, args.profile, confirm_submit=args.confirm_submit, record_dir=args.record_dir,
        pause_below=args.pause_below, max_steps=args.max_steps, block_labels=args.block_label,
        interactive=not args.no_input, close=args.close, trace_path=args.trace)


if __name__ == "__main__":
    main()
