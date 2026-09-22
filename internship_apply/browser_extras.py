"""Things the model is never shown, handled directly in code.

The engine's DOM snapshot deliberately omits password and file inputs, so the agent
cannot see a sign-in wall or a resume upload box. This module looks for those with
plain DOM queries and either hands control to the person (sign-in) or does the
deterministic thing itself (set the file on the input). No model call is involved.

Every function takes the browser's `evaluate` / `call` as arguments so it can be
tested without a browser.
"""

from pathlib import Path

VISIBLE_PASSWORD = """(() => {
  const vis = e => e.checkVisibility({checkOpacity:true, checkVisibilityCSS:true}) &&
    !e.closest('[aria-hidden="true"],[inert]');
  return [...document.querySelectorAll('input[type="password"]')].some(vis);
})()"""

FILE_INPUTS = """(() => [...document.querySelectorAll('input[type="file"]')].map((e, i) => ({
  index: i,
  name: e.getAttribute('aria-label') || e.getAttribute('name') || e.id ||
        (e.labels && e.labels[0] ? e.labels[0].innerText.trim() : '') ||
        e.getAttribute('data-automation-id') || '',
  accept: e.getAttribute('accept') || '',
  files: e.files ? e.files.length : 0,
  disabled: e.disabled,
})))()"""

WORKDAY_PAGE = """(() => {
  const e = document.querySelector('[data-automation-id$="Page"]');
  return e ? e.getAttribute('data-automation-id') : null;
})()"""

# Workday's per-step page markers, mapped to the step names the person sees.
WORKDAY_PAGE_STEPS = {
    "contactInformationPage": "My Information",
    "myExperiencePage": "My Experience",
    "applicationQuestionsPage": "Application Questions",
    "voluntaryDisclosuresPage": "Voluntary Disclosures",
    "selfIdentificationPage": "Self Identify",
    "reviewPage": "Review",
}


def sign_in_wall(evaluate):
    """True when a visible password field is on the page: the person must sign in."""
    try:
        return bool(evaluate(VISIBLE_PASSWORD))
    except Exception:
        return False


def file_inputs(evaluate):
    """All file inputs on the page, hidden ones included (Workday hides its behind a drop zone)."""
    try:
        return evaluate(FILE_INPUTS) or []
    except Exception:
        return []


def wants_resume(inputs):
    """The first empty, enabled file input, or None. One is enough for an application."""
    for entry in inputs:
        if not entry.get("files") and not entry.get("disabled"):
            return entry
    return None


def set_file_input(call, path, index=0):
    """Attach a local file to the index-th file input via CDP. Works on hidden inputs."""
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Resume file not found: {path}")
    root = call("DOM.getDocument", depth=0)["root"]["nodeId"]
    nodes = call("DOM.querySelectorAll", nodeId=root, selector='input[type="file"]')["nodeIds"]
    if index >= len(nodes):
        raise IndexError(f"No file input at index {index} (found {len(nodes)})")
    call("DOM.setFileInputFiles", files=[str(path)], nodeId=nodes[index])
    return str(path)


def workday_step(evaluate):
    """The Workday wizard step from the page's data-automation-id marker, or None."""
    try:
        marker = evaluate(WORKDAY_PAGE)
    except Exception:
        return None
    return WORKDAY_PAGE_STEPS.get(marker)
