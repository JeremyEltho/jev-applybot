"""Offline tests for the internship_apply layer. No browser, no paid APIs."""

import json

from internship_apply import browser_extras
from internship_apply.apply import SUBMIT_PATTERN, build_goal, load_profile
from internship_apply.sites import GENERIC, SITES, detect_step, site_for, submit_pattern


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


# -- profile / goal ----------------------------------------------------------------------


def test_load_profile_reads_resume_relative_to_profile(tmp_path):
    path = write_profile(tmp_path, resume_text="Relevant experience.")
    profile, resume_text, resume_file = load_profile(path)
    assert profile["name"] == "Test Candidate"
    assert resume_text == "Relevant experience."
    assert resume_file is None


def test_load_profile_resolves_resume_file(tmp_path):
    (tmp_path / "resume.pdf").write_bytes(b"%PDF-1.4 fake")
    path = write_profile(tmp_path, resume_file="resume.pdf")
    _, _, resume_file = load_profile(path)
    assert resume_file == tmp_path / "resume.pdf"


def test_load_profile_tolerates_missing_files(tmp_path, capsys):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({"name": "No Resume", "resume_path": "missing.txt", "resume_file": "missing.pdf"}))
    _, resume_text, resume_file = load_profile(path)
    assert resume_text == "" and resume_file is None
    assert "warning" in capsys.readouterr().err


def test_build_goal_includes_profile_facts_and_resume():
    goal = build_goal({"name": "Ada", "answers": {"work_authorization": "Yes"}}, "Wrote software.")
    assert "Ada" in goal and "work_authorization" in goal and "Wrote software." in goal
    assert "resume_path" not in goal and "resume_file" not in goal


def test_build_goal_declines_blank_disclosures_and_hides_notes():
    goal = build_goal({"name": "Ada", "disclosures": {"_note": "internal", "gender": ""}}, "")
    assert "declines to answer" in goal
    assert "internal" not in goal


def test_build_goal_adds_site_notes_and_forbids_submit():
    goal = build_goal({"name": "Ada"}, "", SITES["workday"])
    assert "SITE NOTES" in goal and "Save and Continue" in goal
    assert "Do not click Submit" in goal


# -- sites -------------------------------------------------------------------------------


def test_site_for_matches_host_suffixes():
    assert site_for("https://acme.wd5.myworkdayjobs.com/en-US/Careers/job/123")["name"] == "Workday"
    assert site_for("https://boards.greenhouse.io/acme/jobs/1")["name"] == "Greenhouse"
    assert site_for("https://jobs.lever.co/acme/abc")["name"] == "Lever"
    assert site_for("https://jobs.ashbyhq.com/acme/abc")["name"] == "Ashby"
    assert site_for("https://www.linkedin.com/jobs/view/1")["name"] == "LinkedIn Easy Apply"
    assert site_for("https://careers.example.com/apply") is GENERIC
    # No accidental match on a look-alike host.
    assert site_for("https://notlever.co/x") is GENERIC


def test_submit_pattern_matches_final_submission_labels():
    guard = submit_pattern(SITES["workday"])
    for label in ["Submit", " Submit Application ", "Send application", "Finish Application", "submit my application"]:
        assert guard.match(label), label


def test_submit_pattern_does_not_match_start_or_navigation_buttons():
    guard = submit_pattern(SITES["workday"])
    for label in ["Apply", "Apply Now", "Apply Manually", "Easy Apply", "Autofill with Resume", "Save and Continue",
                  "Next", "Review", "Save draft", "Upload resume", "Submit feedback about this page"]:
        assert not guard.match(label), label


def test_submit_pattern_accepts_extra_labels_and_is_anchored():
    guard = submit_pattern(GENERIC, extra=["Send it"])
    assert guard.match("send it")
    assert not guard.match("Do not send it")
    assert SUBMIT_PATTERN.match("Submit Application")


def test_detect_step_picks_the_repeated_heading():
    site = SITES["workday"]
    progress_bar = ("1 My Information 2 My Experience 3 Application Questions "
                    "4 Voluntary Disclosures 5 Self Identify 6 Review")
    assert detect_step(progress_bar + "\nMy Experience\nWork Experience", site) == "My Experience"
    assert detect_step(progress_bar, site) is None  # all tied: ambiguous
    assert detect_step("Review\nplease review your application", site) == "Review"
    assert detect_step("nothing relevant", site) is None
    assert detect_step("My Experience", GENERIC) is None


# -- browser extras (fake evaluate/call) --------------------------------------------------


def test_sign_in_wall_reads_evaluate_result():
    assert browser_extras.sign_in_wall(lambda expr: True) is True
    assert browser_extras.sign_in_wall(lambda expr: False) is False

    def boom(expr):
        raise RuntimeError("navigating")

    assert browser_extras.sign_in_wall(boom) is False


def test_wants_resume_picks_first_empty_enabled_input():
    inputs = [
        {"index": 0, "name": "photo", "files": 1, "disabled": False},
        {"index": 1, "name": "cover", "files": 0, "disabled": True},
        {"index": 2, "name": "file-upload-input-ref", "files": 0, "disabled": False},
    ]
    assert browser_extras.wants_resume(inputs)["index"] == 2
    assert browser_extras.wants_resume([]) is None


def test_set_file_input_uses_cdp_on_the_requested_node(tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 fake")
    calls = []

    def call(method, **params):
        calls.append((method, params))
        if method == "DOM.getDocument":
            return {"root": {"nodeId": 1}}
        if method == "DOM.querySelectorAll":
            return {"nodeIds": [41, 42]}
        return {}

    attached = browser_extras.set_file_input(call, resume, index=1)
    assert attached == str(resume.resolve())
    assert calls[-1] == ("DOM.setFileInputFiles", {"files": [str(resume.resolve())], "nodeId": 42})


def test_set_file_input_rejects_missing_file_or_index(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError):
        browser_extras.set_file_input(lambda m, **p: {}, tmp_path / "nope.pdf")
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"x")

    def call(method, **params):
        return {"root": {"nodeId": 1}} if method == "DOM.getDocument" else {"nodeIds": []}

    with pytest.raises(IndexError):
        browser_extras.set_file_input(call, resume)


def test_workday_step_maps_page_marker():
    assert browser_extras.workday_step(lambda expr: "myExperiencePage") == "My Experience"
    assert browser_extras.workday_step(lambda expr: "somethingElsePage") is None
    assert browser_extras.workday_step(lambda expr: None) is None
