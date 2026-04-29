// N5H Jarvis Mobile — Scriptable iPhone version

const fm = FileManager.iCloud();
const root = fm.joinPath(fm.documentsDirectory(), "alphie-n5h-wiki");

const today = new Date().toISOString().slice(0, 10);

const dirs = [
  "07-raw-materials/inbox",
  "07-raw-materials/extracted",
  "05-daily-notes",
  "09-outputs"
];

for (const d of dirs) {
  const p = fm.joinPath(root, d);
  if (!fm.fileExists(p)) fm.createDirectory(p, true);
}

function slugify(text) {
  return String(text)
    .toLowerCase()
    .replace(/https?:\/\//g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 60);
}

function frontmatter(name, id, type, status, tags, sources = []) {
  return `---
name: ${name}
id: ${id}
entity_type: ${type}
status: ${status}
tags: [${tags.join(", ")}]
links:
  -
sources:
${sources.length ? sources.map(s => `  - ${s}`).join("\n") : "  -"}
last_updated: ${today}
---`;
}

async function ask(title, message, placeholder = "") {
  const a = new Alert();
  a.title = title;
  a.message = message;
  a.addTextField(placeholder);
  a.addAction("Save");
  a.addCancelAction("Cancel");
  const r = await a.present();
  if (r === -1) return null;
  return a.textFieldValue(0);
}

async function choose() {
  const a = new Alert();
  a.title = "N5H Jarvis";
  a.message = "What do you want to do?";
  a.addAction("Capture raw research");
  a.addAction("Add daily note");
  a.addAction("Log candidate signal");
  a.addAction("Log client signal");
  a.addAction("Create follow-up");
  a.addCancelAction("Cancel");
  return await a.presentSheet();
}

async function captureRaw() {
  let input = args.plainTexts?.[0] || args.urls?.[0];

  if (!input) {
    input = await ask(
      "Capture raw research",
      "Paste a URL, transcript, LinkedIn note, X post, podcast note, screenshot description, or source text.",
      "Paste source here"
    );
  }

  if (!input) return;

  const id = `${today}-${slugify(input)}-${Date.now()}`;
  const rawPath = fm.joinPath(root, `07-raw-materials/inbox/${id}.md`);
  const extractedPath = fm.joinPath(root, `07-raw-materials/extracted/${id}-extracted.md`);

  const raw = `${frontmatter(
    `Raw Source ${id}`,
    id,
    "raw-source",
    "inbox",
    ["mobile-capture", "raw-source"],
    [input.startsWith("http") ? `url: ${input}` : "mobile-paste"]
  )}

# Raw Source — ${id}

## Source

${input}

## Capture context

- Captured from: iPhone
- Transcript status: unknown
- Related people: unknown
- Related clients: unknown
- Processing status: inbox

## Raw material

${input}

## Agent instruction

Preserve this raw material. Extract signal before filing. Do not invent.
`;

  const extracted = `${frontmatter(
    `Extracted Signal ${id}`,
    `${id}-extracted`,
    "extracted-note",
    "needs-review",
    ["mobile-capture", "extracted", "needs-review"],
    [`raw-source: 07-raw-materials/inbox/${id}.md`]
  )}

# Extracted Signal — ${id}

## Executive signal

Unknown until reviewed.

## People mentioned

- Unknown

## Companies mentioned

- Unknown

## Durable facts

- Unknown

## Recruiting relevance

- Unknown

## Follow-ups

- Review and file durable signal.

## Gaps

- Needs extraction.
`;

  fm.writeString(rawPath, raw);
  fm.writeString(extractedPath, extracted);

  await QuickLook.present(rawPath);
}

async function addDailyNote() {
  const note = await ask("Daily note", "What happened / what needs tracking?", "Type note");
  if (!note) return;

  const dailyPath = fm.joinPath(root, `05-daily-notes/${today}.md`);

  if (!fm.fileExists(dailyPath)) {
    fm.writeString(dailyPath, `${frontmatter(
      `Daily Note ${today}`,
      `daily-${today}`,
      "output",
      "open",
      ["daily-note", "n5h", "mobile"],
      ["mobile-entry"]
    )}

# Daily Note — ${today}

## Priorities

## Notes

`);
  }

  const existing = fm.readString(dailyPath);
  fm.writeString(dailyPath, `${existing}

### Mobile note — ${new Date().toLocaleTimeString()}

${note}
`);

  await QuickLook.present(dailyPath);
}

async function logSignal(type) {
  const name = await ask(
    `${type} signal`,
    `Who or what is this about?`,
    type === "candidate" ? "Candidate name" : "Client/company name"
  );
  if (!name) return;

  const signal = await ask("Signal", "What durable fact or observation should be captured?", "Signal");
  if (!signal) return;

  const id = slugify(name);
  const folder = type === "candidate" ? "04-candidates" : "03-clients";
  const filePath = fm.joinPath(root, `${folder}/${id}.md`);

  const entry = `

## Mobile update — ${today}

${signal}

### Source

- mobile-capture: ${today}
`;

  if (!fm.fileExists(filePath)) {
    fm.createDirectory(fm.joinPath(root, folder), true);
    fm.writeString(filePath, `${frontmatter(
      name,
      id,
      type,
      "unknown",
      [type, "mobile-created"],
      ["mobile-capture"]
    )}

# ${name}

## Summary

Unknown.

${entry}

## Gaps

- Confirm details.
- Add links to source material.
`);
  } else {
    const existing = fm.readString(filePath);
    fm.writeString(filePath, existing + entry);
  }

  await QuickLook.present(filePath);
}

async function createFollowUp() {
  const person = await ask("Follow-up", "Who do you need to follow up with?", "Name");
  if (!person) return;

  const context = await ask("Context", "Why are you following up?", "Context");
  if (!context) return;

  const outputPath = fm.joinPath(root, `09-outputs/${today}-${slugify(person)}-follow-up.md`);

  const body = `${frontmatter(
    `${person} Follow-up`,
    `${today}-${slugify(person)}-follow-up`,
    "output",
    "draft",
    ["follow-up", "mobile-draft"],
    ["mobile-capture"]
  )}

# Follow-up — ${person}

## Context

${context}

## Draft

Hey ${person},

Wanted to follow up on ${context}.

Best,
Alphie

## Notes

- Review before sending.
- Update candidate/client/contact file after sending.
`;

  fm.writeString(outputPath, body);
  await QuickLook.present(outputPath);
}

const choice = await choose();

if (choice === 0) await captureRaw();
if (choice === 1) await addDailyNote();
if (choice === 2) await logSignal("candidate");
if (choice === 3) await logSignal("client");
if (choice === 4) await createFollowUp();

Script.complete();
