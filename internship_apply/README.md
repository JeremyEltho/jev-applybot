# Internship application filler

Fills one job application form from your resume and a Q&A profile, using the same
Jev-driven click/type/select loop as the rest of this repo. It stops before the final
submit control — you review and press it yourself, or pass `--confirm-submit` once
you trust it on a given site.

## Setup

1. From the repo root: `uv sync`, then `cp .env.example .env` and fill in
   `TYPESAFE_API_KEY` and `TEXT_MODEL_API_KEY` (see the main README).
2. Copy `internship_apply/profile.example.json` to `internship_apply/profile.json`
   and fill in your real details.
3. Put your resume as plain text next to it (`internship_apply/resume.txt`), or point
   `resume_path` in the profile at wherever it lives. If you only have a PDF or DOCX,
   convert it to text first (`pdftotext resume.pdf resume.txt`, or open it and paste
   the text into a `.txt` file) — this tool does not parse PDFs itself.

## Run

```
uv run --env-file .env python -m internship_apply.apply \
  --url "https://jobs.example.com/postings/1234" \
  --profile internship_apply/profile.json
```

It prints each field it fills as it goes, then stops at the review screen and lists
any fields it could not fill (so you can fill those by hand before submitting).

## What it will not do

- It never clicks Submit / Apply / Send Application / Finish Application on its own.
  That match is a hardcoded pattern in `apply.py`, not a model decision, so it holds
  even if a prompt or page tries to talk it out of it.
- It never invents personal information. If a field isn't covered by your resume or
  profile, it's left blank and reported to you at the end.
- It does not search job boards or discover postings — you give it one URL at a time.

## Before you point this at a real job board

Read that board's terms of service. Many (Workday, Greenhouse, LinkedIn Easy Apply,
Handshake) explicitly prohibit automated or bot-submitted applications, separate from
whether this tool stops before the submit click. Using it to *fill* a form you'll
review and submit yourself is the safer reading; having it click submit at scale
across many postings is the kind of use those terms are written to catch.
