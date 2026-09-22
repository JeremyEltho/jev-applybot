"""Offline tests for the internship_apply profile/goal logic. No browser, no paid APIs."""

import json

from internship_apply.apply import SUBMIT_PATTERN, build_goal, load_profile


def write_profile(tmp_path, resume_text="Built things. Shipped things.", **overrides):
    profile = {
        "name": "Test Candidate",
        "email": "test@example.com",
        "resume_path": "resume.txt",
        "answers": {"work_authorization": "Yes"},
        **overrides,
    }
    (tmp_path / "resume.txt").write_text(resume_text)
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile))
    return path


def test_load_profile_reads_resume_relative_to_profile(tmp_path):
    path = write_profile(tmp_path, resume_text="Relevant experience.")
    profile, resume_text = load_profile(path)
    assert profile["name"] == "Test Candidate"
    assert resume_text == "Relevant experience."


def test_load_profile_tolerates_missing_resume(tmp_path, capsys):
    profile = {"name": "No Resume", "resume_path": "missing.txt"}
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile))
    _, resume_text = load_profile(path)
    assert resume_text == ""
    assert "warning" in capsys.readouterr().err


def test_build_goal_includes_profile_facts_and_resume():
    goal = build_goal({"name": "Ada", "answers": {"work_authorization": "Yes"}}, "Wrote software.")
    assert "Ada" in goal
    assert "work_authorization" in goal
    assert "Wrote software." in goal
    assert "resume_path" not in goal


def test_build_goal_forbids_clicking_submit_controls():
    goal = build_goal({"name": "Ada"}, "")
    assert "Submit" in goal and "not click" in goal.lower()


def test_submit_pattern_matches_common_apply_buttons():
    for label in ["Submit Application", "Apply Now", "Send application", "Finish Application"]:
        assert SUBMIT_PATTERN.search(label), label


def test_submit_pattern_does_not_match_unrelated_buttons():
    for label in ["Save draft", "Next", "Upload resume", "Add another education entry"]:
        assert not SUBMIT_PATTERN.search(label), label
