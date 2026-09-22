"""Per-ATS knowledge: navigation hints for the goal, step names for progress display,
and the labels that mean "this sends the application" on each platform.

Nothing here is a selector or a scripted action. The agent still observes the page and
chooses; these are hints and guardrails around that choice.
"""

import re
from urllib.parse import urlparse

SITES = {
    "workday": {
        "name": "Workday",
        "hosts": ("myworkdayjobs.com", "myworkday.com", "workdayjobs.com"),
        # Visible headings of the application wizard, in order. Used only to report progress.
        "steps": [
            "My Information", "My Experience", "Application Questions",
            "Voluntary Disclosures", "Self Identify", "Review",
        ],
        # Buttons that move between steps. They are not final submission.
        "advance": ["Save and Continue", "Next", "Continue", "Review"],
        "submit": ["Submit"],
        "hints": [
            "This is a Workday application: a multi-step wizard (My Information, My Experience, "
            "Application Questions, Voluntary Disclosures, Self Identify, Review). Move between "
            "steps with the Save and Continue / Next button at the bottom; those buttons are not "
            "final submission.",
            "On the job posting, click Apply to start. If offered 'Use My Last Application', "
            "choose it. Otherwise choose 'Autofill with Resume' when a resume has been uploaded, "
            "else 'Apply Manually'.",
            "Dropdown fields (country, phone type, degree, field of study, school, gender, etc.) "
            "are buttons: click the button, then click the matching option in the list that "
            "opens. Typing the first letters filters the list.",
            "Date fields are split into a Month box and a Year box: type the two-digit month "
            "(MM) in the month box and the four-digit year in the year box.",
            "For 'Have you previously worked for this company?' answer No unless the profile says otherwise.",
            "Fields with a red error message need to be fixed before Save and Continue will work; "
            "read the message and correct that field.",
        ],
    },
    "greenhouse": {
        "name": "Greenhouse",
        "hosts": ("greenhouse.io",),
        "steps": [],
        "advance": [],
        "submit": ["Submit Application", "Submit application"],
        "hints": [
            "This is a Greenhouse application: a single page. Fill every field, then stop at the "
            "Submit Application button.",
            "If the form is embedded in an iframe on a company site and its fields are not "
            "visible, the direct boards.greenhouse.io URL for the posting is needed instead.",
        ],
    },
    "lever": {
        "name": "Lever",
        "hosts": ("lever.co",),
        "steps": [],
        "advance": [],
        "submit": ["Submit application", "Submit Application"],
        "hints": ["This is a Lever application: a single page ending in a Submit application button."],
    },
    "ashby": {
        "name": "Ashby",
        "hosts": ("ashbyhq.com",),
        "steps": [],
        "advance": [],
        "submit": ["Submit Application", "Submit application"],
        "hints": ["This is an Ashby application: a single page ending in a Submit Application button."],
    },
    "linkedin": {
        "name": "LinkedIn Easy Apply",
        "hosts": ("linkedin.com",),
        "steps": [],
        "advance": ["Next", "Review", "Continue"],
        "submit": ["Submit application", "Submit Application"],
        "hints": [
            "This is LinkedIn Easy Apply: a modal with several short pages. Use Next and Review "
            "to move forward; those are not final submission. The final button is Submit application.",
            "Uncheck 'Follow company' only if the profile says to.",
        ],
    },
}

GENERIC = {
    "name": "Unknown site",
    "hosts": (),
    "steps": [],
    "advance": [],
    "submit": [],
    "hints": [
        "If the application has several pages, use Next / Continue / Save and Continue to move "
        "between them; those are not final submission.",
    ],
}


def site_for(url):
    """Pick the site profile whose host suffix matches the URL, else GENERIC."""
    host = (urlparse(url).hostname or "").lower()
    for site in SITES.values():
        if any(host == h or host.endswith("." + h) for h in site["hosts"]):
            return site
    return GENERIC


# Labels that send the application on any site. Start-of-flow buttons ("Apply", "Apply Now",
# "Apply Manually", "Easy Apply") are deliberately absent: they open the form, they do not send it.
GENERIC_SUBMIT = [
    "Submit",
    "Submit Application",
    "Submit application",
    "Submit my application",
    "Send Application",
    "Send application",
    "Finish Application",
    "Complete Application",
    "Submit now",
]


def submit_pattern(site=None, extra=()):
    """Compile an anchored, case-insensitive matcher for final-submission button labels."""
    labels = list(GENERIC_SUBMIT) + list((site or GENERIC)["submit"]) + list(extra)
    escaped = sorted({re.escape(label.strip()) for label in labels if label.strip()}, key=len, reverse=True)
    return re.compile(r"^\s*(?:" + "|".join(escaped) + r")\s*$", re.IGNORECASE)


def detect_step(text, site):
    """Guess the current wizard step from visible page text.

    Workday lists every step name in its progress bar on every page, and repeats the
    current one as the page heading, so the step that appears most often is the current
    one. A single unambiguous winner is returned; ties or no matches return None.
    """
    counts = {}
    for step in site["steps"]:
        n = len(re.findall(r"(?<![\w])" + re.escape(step) + r"(?![\w])", text or "", re.IGNORECASE))
        if n:
            counts[step] = n
    if not counts:
        return None
    best = max(counts.values())
    winners = [s for s, n in counts.items() if n == best]
    return winners[0] if len(winners) == 1 else None
