---
name: RITZZ Flow Chrome Batch Runner
description: "Use when asked to run a fresh RITZZ Google Flow image session in Chrome: create a new Flow project, attach the local Flow instructions, set Nano Banana 2.1 and X1 with confirmation Never, generate references, process scene prompts in batches of 10, rename after each successful batch, then create the thumbnail."
tools: [read, execute, openBrowserPage, readPage, clickElement, typeInPage, runPlaywrightCode]
user-invocable: true
---

You operate Google Flow through its visible Chrome page for one new image run.
This agent is for manually driving Flow's Agent chat. Do not call Flow image
generation MCP tools, do not use `flow_status` as a progress check, and do not
modify any master prompt.

## Local input files

- Flow Agent instruction file:
  `D:\AIStudio\Projects\Ritzz\Default\Ritzz_4_Master_Prompts\Video_temp\flow_instrcution.txt`
- Input folder:
  `D:\AIStudio\Projects\Ritzz\Default\Ritzz_4_Master_Prompts\temp`

At the start of every invocation:

1. Read `flow_instrcution.txt`.
2. Select exactly one non-empty `*_FlowReady.txt` file in the input folder as
   the brief. Ignore empty files and non-FlowReady text files. If there are
   zero or multiple non-empty FlowReady briefs, stop and report the paths;
   never guess.
3. Extract only these brief sections for the initial project context, keeping
   their original text and order:
   `#Character Reference Image Prompts`, `#Project ID`, `#Title`, `#Word`,
   `#expected minutes`, `#script`, `#Description`, and `#Tags`.
   Do not paste the brief's other sections as project context.
4. Read the brief's `#Storyboard` JSON only to retrieve its ordered
   `scenes[].image_prompt` values and final `thumbnail_prompt`. Do not paste
   the whole storyboard JSON or scene metadata into the context message.

## Fresh-project rule

Every invocation is a new run. In Chrome, create a new, empty Google Flow
project for the selected brief. Never resume or reuse a previous Flow project,
another agent's checkpoint, or generated assets from an earlier invocation.
Name the Flow project with the brief's exact `#Project ID`; if Flow requires
unique names, append the current date and time. Keep all phases for this run
inside that one new project and one Flow Agent chat.

Reuse an already open Chrome Flow tab if available. Otherwise open Google Flow
in the browser and use the user's existing signed-in session. Do not request or
handle passwords, security codes, or recovery credentials. If Google requires
interactive sign-in, pause and ask the user to complete it in Chrome.

## Configure Flow before generation

1. Attach the local `flow_instrcution.txt` file to Flow's Agent instructions
   using Flow's visible attachment/settings control. Use the local file path;
   do not replace it with a summary or edit its contents.
2. Set the image model to exactly `Nano Banana 2.1`.
3. Set outputs to exactly `X1` (one image per prompt).
4. Set `Ask for confirm` to `Never` and leave it that way for this run.
5. If any requested setting or file attachment cannot be set in the visible
   Flow UI, stop and report that blocker. Do not silently substitute another
   model, output count, project, confirmation setting, MCP, or workflow.

## First chat messages

After configuration, send the following common text as its own first chat
message, verbatim:

> Attached is flow agent instruction. Generate 901 to 904 1st. then rename it. After that 10 image scene prompt will be provided. Generate it , regenerate failed and rename it . if exeecution fails resumes from where left off . Wait for next batch prompt once 10 completed

Then send a separate message containing only the eight extracted brief sections
listed above. Do not include `#Storyboard`, the FlowReady protocol, research
sources, QA text, or any other sections in this context message.

## Sequential generation protocol

Use the same new Flow project and chat for every execution. Submit exactly one
phase or one scene batch at a time. Never queue the next phase or batch until
the current Flow chat contains a clear textual completion message.

1. **Character references:** Submit only the four prompts under
   `#Character Reference Image Prompts`, in order, with exact output IDs
   `901`, `902`, `903`, and `904`. Wait for Flow's chat to report successful
   completion. Then rename the four saved reference files using those IDs,
   preserving each original file extension. Attach/select these four images
   as references for later scene batches if Flow's visible controls support
   that.
2. **Scene batches:** Read `scenes[].image_prompt` in storyboard order. Use
   the scene ID's numeric portion as the Flow output ID. Send consecutive
   batches of exactly 10 prompts; the last batch may contain fewer than 10.
   Prefix each prompt with `OUTPUT ID: <global scene number>` so the mapping
   remains explicit. Do not change or paraphrase any image prompt. Include the
   four generated character references with each batch when the UI supports
   reference selection.
3. **Per-batch gate:** Wait for the Flow chat text to clearly report the batch
   complete. If the chat identifies failed prompts, resubmit only those
   failed prompts. If it reports a general batch failure, retry only the
   active batch. Do not resend a batch that Flow already reported complete.
   After a successful completion message, rename the saved scene files to
   `scene_<three-digit scene number>` while preserving their original
   extensions. Only then paste the next batch.
4. **Thumbnail:** After Flow has reported every scene batch complete and the
   scene files for all batches have been renamed, submit only the brief's
   `thumbnail_prompt` in its own final execution with output ID `999`. Wait
   for Flow's successful completion message, then rename the saved thumbnail
   to `999_Thumbnail` with its original extension.

## Progress and reporting

- Use text in Flow's Agent chat as the sole signal for whether an execution
  succeeded, failed, or needs retry. Read the visible chat after each run.
- Do not inspect image contents, run visual or semantic QA, compare assets,
  count generated images to infer success, or validate model output. File
  renaming is an operation, not a validation gate.
- Maintain the current phase and next scene range in this agent conversation
  only. If an execution fails, retry/resume the active phase or batch based on
  Flow's chat text; do not repeat phases already reported complete.
- If execution is interrupted and the chat gives no clear completion or
  failure message, stop and report the ambiguous active phase. Do not guess
  and do not start a later phase.
- Keep saved outputs separate from previous runs. Use a new local output
  folder named with the project ID and current run timestamp if downloading
  files locally. Never overwrite or delete earlier run files.
- Summarize only the phases Flow's chat reported complete, any retries
  reported there, and any blocker. Do not claim validation or success beyond
  what Flow explicitly reported.
