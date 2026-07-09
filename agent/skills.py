"""
agent/skills.py
===============
Wendy's skill library.

A "skill" is a named, reusable process (a structured prompt) the user can turn
on from the chat UI's ✨ Skills button. While a skill is active, its
instructions are injected into Wendy's system prompt, so she follows that
process until the user switches it off.

Two skills ship built-in (Grill Me, Write a PRD). You can also drop extra skill
files into an `agent/skills/` folder and they'll appear in the menu
automatically — either as `agent/skills/<id>.md` or `agent/skills/<id>/SKILL.md`.
That's the same `SKILL.md` format the `npx skills` ecosystem uses, so you can
paste in someone else's skill (e.g. Matt Pocock's) and it just works.

Skill file format (frontmatter optional):

    ---
    name: Grill Me
    description: Interview me relentlessly about a plan.
    ---
    <the process instructions the model should follow>
"""

import os
import re


# --- built-in skills ----------------------------------------------------
_BUILTIN = {
    "plan-feature": {
        "name": "Plan a Feature",
        "description": "Interview you about a feature, then write a PRD once we've reached a shared understanding.",
        "body": """You are running the PLAN A FEATURE process. It has two phases — first
GRILL, then write the PRD — and you decide when to move from one to the next.

━ PHASE 1 — GRILL ━
Interview the user relentlessly about the feature or plan at hand until you both
reach a shared, unambiguous understanding.
- Walk down each branch of the design tree, resolving dependencies between
  decisions one at a time. Do not move on from a decision until it is settled.
- Ask ONE focused question at a time (two only if tightly linked). Wait for the
  answer before asking the next. Never dump a long list of questions at once.
- Challenge vague or hand-wavy answers. Surface hidden assumptions, edge cases,
  failure modes, and trade-offs the user has not considered.
- If a question could be answered from what you already know about this project,
  do that and reason from it rather than asking the user.
- If the user has not said what to plan, ask what feature or plan we are working
  on before you start.

━ MOVING ON ━
- When there are no meaningful open questions left, tell the user you think you
  have enough, summarize the shared understanding as a tight bullet list, and
  ask them to confirm or add anything.
- If at any point the user says to write it up (e.g. "just write the PRD now"),
  move straight to Phase 2 — note any assumptions you had to make.

━ PHASE 2 — WRITE THE PRD ━
Once understanding is confirmed (or the user asks for it), write a Product
Requirements Document with these sections:
- Title and one-line summary
- Problem / motivation
- Goals and non-goals
- USER STORIES (the heart of it): each written as
  "As a <user>, I want <capability>, so that <benefit>", with 2-4 acceptance
  criteria per story.
- Major modules / components
- Dependencies and risks
- Open questions

Deliver the finished PRD as an artifact (use the ```artifact block) so the user
can read, edit, and download it.""",
    },
}


def _parse_md(text, fallback_id):
    """Parse a skill markdown file. Optional `--- ... ---` frontmatter supplies
    name/description; everything after it is the body. Falls back to the file
    id for the name if there's no frontmatter."""
    name = fallback_id.replace("-", " ").replace("_", " ").title()
    description = ""
    body = (text or "").strip()
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text or "", re.DOTALL)
    if m:
        front, body = m.group(1), m.group(2).strip()
        for line in front.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                k, v = k.strip().lower(), v.strip()
                if k == "name" and v:
                    name = v
                elif k == "description":
                    description = v
    return {"name": name, "description": description, "body": body}


def _load_folder():
    """Load any extra skills from agent/skills/ (optional)."""
    out = {}
    folder = os.path.join(os.path.dirname(__file__), "skills")
    if not os.path.isdir(folder):
        return out
    for entry in sorted(os.listdir(folder)):
        path = os.path.join(folder, entry)
        try:
            if entry.endswith(".md") and os.path.isfile(path):
                sid = entry[:-3]
                with open(path, encoding="utf-8") as f:
                    out[sid] = _parse_md(f.read(), sid)
            elif os.path.isdir(path):
                skill_md = os.path.join(path, "SKILL.md")
                if os.path.exists(skill_md):
                    with open(skill_md, encoding="utf-8") as f:
                        out[entry] = _parse_md(f.read(), entry)
        except Exception as e:
            print(f"skills: could not load {entry}: {e}")
    return out


def _all():
    skills = dict(_BUILTIN)
    skills.update(_load_folder())   # folder files can add to / override built-ins
    return skills


def list_skills():
    """Return [{id, name, description}] for the picker menu."""
    return [
        {"id": sid, "name": s["name"], "description": s.get("description", "")}
        for sid, s in _all().items()
    ]


def get_skill(skill_id):
    return _all().get(skill_id)


def skill_prompt(skill_id):
    """Text to inject into the system prompt while this skill is active."""
    s = get_skill(skill_id)
    if not s:
        return ""
    return (
        f"\n\n--- ACTIVE SKILL: {s['name']} ---\n"
        f"The user has switched on the \"{s['name']}\" skill. Follow this process "
        f"for this and following turns until they turn it off:\n\n"
        f"{s['body']}\n"
    )