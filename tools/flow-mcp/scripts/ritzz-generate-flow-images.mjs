import { copyFile, mkdir, readFile, readdir, stat, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { basename, dirname, extname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";

const REPOSITORY_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const INPUT_ROOT = process.env.RITZZ_CREATIVE_INPUT ?? join(REPOSITORY_ROOT, "projects", "flow_staging");
const FLOW_HOME = process.env.FLOW_MCP_HOME ?? join(homedir(), ".flow-mcp");
const FLOW_URL = `http://127.0.0.1:${process.env.FLOW_MCP_PORT ?? "8787"}`;
const MAX_AGENT_SCENES = 24;
const MAX_WAIT_SECONDS = 30;
const RICH_ILLUSTRATION_STYLE =
  "Polished 2D editorial-cartoon illustration with expressive rounded characters: oversized round white heads, clear facial expressions, compact softly rounded white bodies, and short, thick, curved arms and legs as solid filled shapes with strong clean black outlines. Connect the limbs naturally to the body; do not use thin line-only limbs, skeletal stick figures, or realistic human anatomy. Avoid crude doodles: use confident smooth contour lines, readable poses, thoughtful expressions, and subtle highlights and shadows. Surround the characters with a richly detailed, story-specific environment, layered foreground, midground and background, textured props, nuanced colors, and cinematic light. Compose one coherent 16:9 illustration; the setting should feel complete and detailed without overpowering the rounded character.";
const SCENE_FIDELITY_GUIDANCE =
  "Depict only the single scene described next. Make its specified subject, action, and key gesture unmistakable; preserve the requested place, time of day, era, and essential props. Keep the main subject clearly readable, with the background supporting rather than competing with the action. Do not borrow events, people, or settings from another storyboard scene or replace the described action with a related one. Honor explicit constraints such as 'no people'. Keep recurring rounded characters consistent in head shape, torso silhouette, limb thickness, facial style, and outline weight; vary clothing or props only when the scene calls for them. Render no extra words, labels, or captions.";
const SCENE_CONTINUITY_GUIDANCE =
  "For a recurring character, group, location, or occasion, preserve the same people and count, distinguishing appearance and clothing, key props, and stable setting layout established in related scenes. If only the time of day or one event changes, keep those continuity anchors and change only what the scene calls for; do not substitute a new group or location. Repeat the concrete continuity details in each self-contained scene prompt rather than relying on memory of another image.";

function fail(message) {
  throw new Error(message);
}

function replaceStickFigureTerms(text) {
  return text
    .replace(/\bstick figures\b/gi, "rounded characters")
    .replace(/\bstick figure\b/gi, "rounded character")
    .replace(/\bstickmen\b/gi, "rounded characters")
    .replace(/\bstickman\b/gi, "rounded character");
}

function upgradeLegacyStyle(prompt, includeSceneFidelity = false) {
  const legacyStyle = /^Simple 2D stickman cartoon(?: style)?,.*?\bstatic composition\.\s*/is;
  const hasLegacyStickmanStyle = legacyStyle.test(prompt);
  if (!hasLegacyStickmanStyle && !/\bstickman\b|\bstick figure\b/i.test(prompt)) {
    return prompt;
  }
  const scene = replaceStickFigureTerms(
    hasLegacyStickmanStyle ? prompt.replace(legacyStyle, "").trim() : prompt.trim(),
  );
  const sceneGuidance = includeSceneFidelity
    ? ` ${SCENE_FIDELITY_GUIDANCE} ${SCENE_CONTINUITY_GUIDANCE}`
    : "";
  return `${RICH_ILLUSTRATION_STYLE}${sceneGuidance} Scene: ${scene}`;
}

function normalizeExpectedMinutes(text, fileName) {
  const heading = text.match(/^#\s*expected minutes\s*$/im);
  const scriptHeading = text.match(/^#\s*script\s*$/im);
  if (!heading || heading.index === undefined || !scriptHeading || scriptHeading.index === undefined
    || scriptHeading.index <= heading.index) {
    fail(`${fileName}: #expected minutes and #script sections are required in that order.`);
  }
  const valueStart = heading.index + heading[0].length;
  const sectionLines = text.slice(valueStart, scriptHeading.index).split(/\r?\n/);
  const nonEmptyLines = sectionLines.map((line) => line.trim()).filter(Boolean);
  const minutes = nonEmptyLines[0];
  if (!/^[1-9]\d*$/.test(minutes ?? "")) {
    fail(`${fileName}: #expected minutes must begin with a positive whole number.`);
  }
  const removedNote = nonEmptyLines.length > 1;
  const normalized = removedNote
    ? `${text.slice(0, heading.index)}${heading[0]}\n${minutes}\n\n${text.slice(scriptHeading.index)}`
    : text;
  return { text: normalized, minutes, removedNote };
}

async function api(method, args = {}) {
  const token = (await readFile(join(FLOW_HOME, "token"), "utf8")).trim();
  if (!token) fail("Flow MCP token is empty. Start Flow Studio.cmd and try again.");
  const response = await fetch(`${FLOW_URL}/api/${method}`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-flow-token": token },
    body: JSON.stringify(args),
    signal: AbortSignal.timeout(150_000),
  });
  const body = await response.json();
  if (!response.ok) fail(body.error ?? `Flow MCP returned HTTP ${response.status} for ${method}.`);
  return body;
}

async function waitForFlowServer() {
  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${FLOW_URL}/api/health`, { signal: AbortSignal.timeout(2_000) });
      if (response.ok) {
        await readFile(join(FLOW_HOME, "token"), "utf8");
        return;
      }
    } catch {
      await delay(1_000);
    }
  }
  fail("Flow MCP did not start. Run Flow Studio.cmd, then run this file again.");
}

function parseBrief(text, fileName) {
  const { minutes } = normalizeExpectedMinutes(text, fileName);
  const projectMatch = text.match(/^#Project ID\s*\r?\n([^\r\n]+)/im);
  const projectId = projectMatch?.[1]?.trim();
  if (!projectId || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/.test(projectId)) {
    fail(`${fileName}: missing or invalid #Project ID.`);
  }

  const marker = text.match(/^#Storyboard\s*$/im);
  if (!marker || marker.index === undefined) fail(`${fileName}: #Storyboard section was not found.`);
  const storyboard = JSON.parse(text.slice(marker.index + marker[0].length).trim());
  if (!Array.isArray(storyboard.scenes) || storyboard.scenes.length < 1 || storyboard.scenes.length > 200) {
    fail(`${fileName}: storyboard must contain 1-200 scenes.`);
  }
  if (typeof storyboard.thumbnail_prompt !== "string" || !storyboard.thumbnail_prompt.trim()) {
    fail(`${fileName}: storyboard is missing thumbnail_prompt.`);
  }

  const scenes = storyboard.scenes.map((scene, index) => {
    const expectedId = `scene_${String(index + 1).padStart(3, "0")}`;
    if (scene.scene_id !== expectedId) fail(`${fileName}: expected ${expectedId} at scene ${index + 1}.`);
    if (typeof scene.image_prompt !== "string" || !scene.image_prompt.trim()) {
      fail(`${fileName}: ${expectedId} is missing image_prompt.`);
    }
    return {
      id: expectedId,
      prompt: upgradeLegacyStyle(scene.image_prompt.trim(), true),
    };
  });
  const stagedStoryboard = {
    ...storyboard,
    thumbnail_prompt: upgradeLegacyStyle(storyboard.thumbnail_prompt.trim()),
    scenes: storyboard.scenes.map((scene, index) => ({
      ...scene,
      visual_description: typeof scene.visual_description === "string"
        ? replaceStickFigureTerms(scene.visual_description)
        : scene.visual_description,
      image_prompt: scenes[index].prompt,
    })),
  };
  return { projectId, expectedMinutes: minutes, storyboard: stagedStoryboard, scenes };
}

async function findBrief() {
  const entries = await readdir(INPUT_ROOT, { withFileTypes: true });
  const briefs = entries.filter((entry) => entry.isFile() && extname(entry.name).toLowerCase() === ".txt");
  if (briefs.length !== 1) {
    fail(`Expected exactly one .txt creative brief in ${INPUT_ROOT}; found ${briefs.length}.`);
  }
  const path = join(INPUT_ROOT, briefs[0].name);
  return { path, name: briefs[0].name, text: await readFile(path, "utf8") };
}

function makeStagedBrief(text, storyboard) {
  const normalized = normalizeExpectedMinutes(text, "Creative brief");
  const marker = normalized.text.match(/^#Storyboard\s*$/im);
  if (!marker || marker.index === undefined) fail("The creative brief is missing its #Storyboard section.");
  const endOfMarker = marker.index + marker[0].length;
  return {
    text: `${normalized.text.slice(0, endOfMarker)}\n${JSON.stringify(storyboard, null, 2)}\n`,
    removedDurationNote: normalized.removedNote,
  };
}

function splitIntoBatches(items) {
  const batches = [];
  for (let start = 0; start < items.length; start += MAX_AGENT_SCENES) {
    batches.push(items.slice(start, start + MAX_AGENT_SCENES));
  }
  return batches;
}

function assertReady(status) {
  if (!status.flow?.signedIn) fail(status.flow?.hint ?? "Flow is not signed in. Sign in using the Flow Chrome window.");
  if (!status.flow?.inProject) fail(status.flow?.hint ?? "Open a Flow project in the Flow Chrome window before generating.");
  const active = (status.jobs ?? []).filter((job) => ["queued", "running"].includes(job.status));
  if (active.length) fail(`Flow already has an active job (${active.map((job) => `${job.id}: ${job.status}`).join(", ")}). Let it finish before starting a new batch.`);
}

async function runBatch({ runProject, prompts, label }) {
  const queued = await api("agent", {
    project: runProject,
    scenes: prompts,
    aspect_ratio: "16:9",
    download_quality: "original",
  });
  const jobs = queued.jobs ?? [];
  if (jobs.length !== 1 || !jobs[0].id) fail(`Flow MCP did not return a job ID for ${label}.`);
  const jobId = jobs[0].id;
  console.log(`Queued ${label} (${prompts.length} image${prompts.length === 1 ? "" : "s"}). Job: ${jobId}`);

  let result;
  do {
    result = await api("wait", { job_ids: [jobId], timeout_seconds: MAX_WAIT_SECONDS });
    const job = result.jobs?.[0];
    if (!job) fail(`Flow MCP lost job ${jobId} while waiting for ${label}.`);
    if (job.status === "failed") fail(`${label} failed: ${job.error ?? "Flow returned no error detail."}`);
    if (job.status === "cancelled") fail(`${label} was cancelled.`);
    if (job.status === "running" || job.status === "queued") {
      const progress = job.progress ? ` — ${job.progress}` : "";
      console.log(`${label} still running${progress}`);
    }
  } while (!result.finished);

  const done = result.jobs[0];
  if (done.status !== "done") fail(`${label} finished with status ${done.status}.`);
  if (done.files?.length !== prompts.length) {
    fail(`${label} expected ${prompts.length} downloaded image(s); Flow returned ${done.files?.length ?? 0}. ${done.note ?? ""}`);
  }
  if (done.note) console.log(`${label}: ${done.note}`);
  console.log(`${label}: Flow reports ${done.credits ?? "an unknown number of"} credit(s) used.`);
  return [...done.files].sort((left, right) => {
    const number = (file) => Number(file.match(/scene-(\d+)/i)?.[1] ?? Number.MAX_SAFE_INTEGER);
    return number(left) - number(right);
  });
}

async function copyImages(files, destinationFor, description) {
  for (const [index, source] of files.entries()) {
    const sourceExtension = extname(source).toLowerCase();
    if (![".jpg", ".jpeg", ".png"].includes(sourceExtension)) {
      fail(`${description}: unsupported image type '${sourceExtension}' from ${source}. Expected JPEG or PNG.`);
    }
    const destination = destinationFor(index, sourceExtension);
    const sourceInfo = await stat(source).catch(() => null);
    if (!sourceInfo?.isFile() || sourceInfo.size === 0) fail(`${description}: generated image is missing or empty: ${source}`);
    await copyFile(source, destination);
  }
}

async function main() {
  const args = process.argv.slice(2);
  if (args.includes("--help") || args.includes("-h")) {
    console.log("Usage: node scripts/ritzz-generate-flow-images.mjs [--dry-run]");
    console.log("--dry-run validates the brief and batching without generating images.");
    return;
  }
  const unknownArgs = args.filter((arg) => arg !== "--dry-run");
  if (unknownArgs.length > 0) {
    fail(`Unknown argument(s): ${unknownArgs.join(", ")}. Use --help for usage.`);
  }

  await mkdir(INPUT_ROOT, { recursive: true });
  const brief = await findBrief();
  const parsed = parseBrief(brief.text, brief.name);
  if (process.argv.includes("--dry-run")) {
    const batches = splitIntoBatches(parsed.scenes);
    const upgraded = parsed.scenes.filter((scene) => scene.prompt.startsWith(RICH_ILLUSTRATION_STYLE)).length;
    if (!parsed.storyboard.thumbnail_prompt.startsWith(RICH_ILLUSTRATION_STYLE)) {
      fail("Dry-run check failed: legacy thumbnail art direction was not upgraded.");
    }
    if (parsed.scenes.some((scene) => !scene.prompt.includes(SCENE_FIDELITY_GUIDANCE))) {
      fail("Dry-run check failed: scene-specific fidelity guidance was not added to every scene prompt.");
    }
    if (parsed.scenes.some((scene) => !scene.prompt.includes(SCENE_CONTINUITY_GUIDANCE))) {
      fail("Dry-run check failed: cross-scene continuity guidance was not added to every scene prompt.");
    }
    const stagedText = makeStagedBrief(brief.text, parsed.storyboard);
    const staged = parseBrief(stagedText.text, brief.name);
    if (staged.scenes.length !== parsed.scenes.length || staged.projectId !== parsed.projectId) {
      fail("Dry-run check failed: staged brief does not preserve its project ID and scene count.");
    }
    if (batches.some((batch) => batch.length > MAX_AGENT_SCENES)
      || batches.flat().some((scene, index) => scene.id !== parsed.scenes[index].id)) {
      fail("Dry-run check failed: scene batches exceed the size cap or changed scene order.");
    }
    const batchLimitCheck = splitIntoBatches(
      Array.from({ length: MAX_AGENT_SCENES * 2 + 1 }, (_, index) => index),
    );
    if (batchLimitCheck.map((batch) => batch.length).join(",")
      !== `${MAX_AGENT_SCENES},${MAX_AGENT_SCENES},1`) {
      fail(`Dry-run check failed: the batch limit of ${MAX_AGENT_SCENES} was not enforced.`);
    }
    console.log(`Validated ${brief.name}: ${parsed.projectId}, ${parsed.scenes.length} scenes, ${batches.length} scene batch(es), and one thumbnail.`);
    console.log(`Scene batch sizes: ${batches.map((batch) => batch.length).join(", ")}.`);
    console.log(`Legacy stickman style is upgraded in ${upgraded} scene prompt(s) and the staged brief.`);
    console.log("Scene-specific action, setting, and character consistency guidance is present in every scene prompt.");
    console.log("Recurring people, groups, locations, and occasions have explicit continuity guidance.");
    if (stagedText.removedDurationNote) {
      console.log("A nonnumeric note after #expected minutes will be omitted from the staged copy; the original brief stays unchanged.");
    }
    return;
  }

  await waitForFlowServer();
  const status = await api("status", { detailed: false });
  assertReady(status);

  const timestamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
  const runProject = `${parsed.projectId}_flow_${timestamp}`;
  const staging = join(INPUT_ROOT, `${parsed.projectId}_flow_${timestamp}`);
  await mkdir(staging, { recursive: false });
  console.log(`Brief: ${brief.name}`);
  console.log(`Project: ${parsed.projectId}`);
  console.log(`Staging package inputs: ${staging}`);
  console.log(`Generating ${parsed.scenes.length} scenes in batches of up to ${MAX_AGENT_SCENES}.`);

  const outputs = [];
  for (const batch of splitIntoBatches(parsed.scenes)) {
    const label = `Scenes ${batch[0].id}-${batch.at(-1).id}`;
    const files = await runBatch({
      runProject,
      prompts: batch.map((scene) => scene.prompt),
      label,
    });
    outputs.push(...files);
  }

  const thumbProject = `${runProject}_thumbnail`;
  const thumbnailFiles = await runBatch({
    runProject: thumbProject,
    prompts: [parsed.storyboard.thumbnail_prompt.trim()],
    label: "Thumbnail",
  });

  const stagedBrief = makeStagedBrief(brief.text, parsed.storyboard);
  await writeFile(join(staging, basename(brief.path)), stagedBrief.text, "utf8");
  if (stagedBrief.removedDurationNote) {
    console.log("Removed a nonnumeric note after #expected minutes from the staged copy; the original brief was not changed.");
  }
  if (outputs.length !== parsed.scenes.length) {
    fail(`Expected ${parsed.scenes.length} scene images after generation; found ${outputs.length}.`);
  }
  await copyImages(outputs, (index, extension) => join(staging, `${parsed.scenes[index].id}${extension}`), "Scene staging");
  if (thumbnailFiles.length !== 1) fail(`Expected one thumbnail image; found ${thumbnailFiles.length}.`);
  await copyImages(thumbnailFiles, (_index, extension) => join(staging, `thumbnail${extension}`), "Thumbnail staging");

  console.log("");
  console.log(`READY FOR REVIEW: ${staging}`);
  console.log(`Generated ${outputs.length} scene images and one thumbnail.`);
  console.log("Review the staged images. To create the GitHub release, run creative_work.bat with:");
  console.log(`  -InputDirectory "${staging}"`);
}

main().catch((error) => {
  console.error(`RITZZ Flow image generation failed: ${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 1;
});
